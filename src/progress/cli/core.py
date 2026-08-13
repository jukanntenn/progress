"""CLI business orchestration entry points (spec 05).

``run()`` is the e2e-callable thick entry: it owns the lifespan and dispatches
to each integration's ``setup → sync → run → teardown`` hooks. Per spec 05/06,
this function **only orchestrates**; business logic lives in each integration's
tracker and in ``cli/reports/`` / ``cli/notifications/``.

Per spec 06/10, two pipelines run after the integrations:

- **reports pipeline** (``cli/reports/pipeline.run``): consumes
  ``RunResult.reports``, aggregates + AI title/summary + persists + optional
  MarkPost publish. Produces ``ReportEvent`` instances appended to the outcome
  via :meth:`RunOutcome.add_report_events`.
- **notifications pipeline**: each producer builds its own notification events
  and streams them through an ``asyncio.Queue`` to a consumer that dispatches
  concurrently (spec 10 parallel channels preserved per event).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from progress.cli.lifespan import lifespan
from progress.cli.notifications.config import NotificationConfig, build_channels
from progress.cli.notifications.dispatcher import Dispatcher
from progress.cli.notifications.events import NotificationEvent
from progress.cli.notifications.renderer import JinjaRenderer
from progress.cli.outcome import RunOutcome
from progress.cli.reports.pipeline import run as run_reports, run_for_integration
from progress.errors import ProgressException
from progress.integrations.base import Components, Integration, RunResult
from progress.integrations.registry import discover_integrations
from progress.observability import mark_span_outcome, observe_span, record_business_event

if TYPE_CHECKING:
    import aiohttp

    from progress.cli.reports.pipeline import IntegrationReport, ReportOutcome
    from progress.config.root import CoreConfig

logger = logging.getLogger(__name__)


async def run(
    cfg: CoreConfig,
    *,
    config_path: str | None = None,
    trackers_only: bool = False,
) -> RunOutcome:
    """Run the full tracking pipeline.

    e2e tests call this directly: ``outcome = await run(cfg, config_path=...)``.
    """
    async with lifespan(cfg, component="cli", config_path=config_path) as ctx:
        assert ctx.cfg is not None
        cfg = ctx.cfg
        integrations = [cls() for cls in discover_integrations().values()]
        integration_names = [i.name for i in integrations]
        logger.info("run started: integrations=%s trackers_only=%s", integration_names, trackers_only)
        record_business_event(
            "progress.run.started",
            attributes={"component": "cli", "integrations": ",".join(integration_names)},
        )

        for integration in integrations:
            await integration.setup(ctx)

        outcome = RunOutcome()
        queue: asyncio.Queue[Any] = asyncio.Queue()

        async def _producer(integration: Integration) -> None:
            integration_name = integration.name
            try:
                async with observe_span(
                    f"progress.integration.{integration_name}",
                    attributes={"integration": integration_name},
                ):
                    result = await _run_integration(integration, cfg)
                    # integrations swallow their own errors and surface them via
                    # RunResult.status; mirror that onto the span so a partial/
                    # failed run is visible in traces (observe_span only marks
                    # ERROR when an exception actually escapes).
                    mark_span_outcome(
                        result.status,
                        error_message=f"integration {integration_name} failed",
                    )
                outcome.add(integration_name, result)
                record_business_event(
                    "progress.integration.run",
                    attributes={
                        "integration": integration_name,
                        "status": result.status,
                        "reports": str(len(result.reports)),
                        "events": str(len(result.events)),
                    },
                )
                logger.info(
                    "integration %s done: status=%s reports=%d events=%d",
                    integration_name,
                    result.status,
                    len(result.reports),
                    len(result.events),
                )

                if not trackers_only:
                    try:
                        report_outcome = await _run_reports_for_integration(
                            outcome, cfg, integration_name, session=ctx.session
                        )
                    except Exception as e:
                        logger.exception("report pipeline failed for %s", integration_name)
                        outcome.errors.append(ProgressException(f"report pipeline failed for {integration_name}: {e}"))
                        report_outcome = None

                    if report_outcome is not None:
                        outcome.add_report_events(report_outcome.events)

                    integration_reports: list[Any] = []
                    if report_outcome is not None:
                        integration_reports = report_outcome.by_integration
                    try:
                        events = await _build_notification_events(integration, outcome, integration_reports)
                        for event in events:
                            await queue.put(event)
                    except Exception as e:
                        logger.warning("build_notification failed for %s: %s", integration_name, e)
            except ProgressException as e:
                outcome.add(
                    integration_name, RunResult(name=integration_name, status="failed", summary=str(e), errors=[e])
                )
            except Exception as e:
                logger.exception("integration %s raised unexpected error", integration_name)
                wrapped = ProgressException(f"unexpected error in {integration_name}: {e}")
                outcome.add(
                    integration_name,
                    RunResult(name=integration_name, status="failed", summary=str(e), errors=[wrapped]),
                )

        async def _consumer() -> None:

            notification_cfg = cfg.notification
            channels = build_channels(notification_cfg, session=ctx.session)
            if not channels:
                logger.info("no enabled notification channels; skipping dispatch")
                while True:
                    event = await queue.get()
                    if event is None:
                        break
                return

            renderer = JinjaRenderer(cfg)
            dispatcher = Dispatcher(channels, renderer)
            active_producers = len(integrations)
            while active_producers > 0:
                event = await queue.get()
                if event is None:
                    active_producers -= 1
                    continue
                try:
                    dispatch_outcome = await dispatcher.dispatch(event)
                    for result in dispatch_outcome.results:
                        kind = getattr(event, "kind", "unknown")
                        if result.ok:
                            record_business_event(
                                "progress.notifications.sent",
                                attributes={"channel": result.channel, "event_kind": kind},
                            )
                        else:
                            record_business_event(
                                "progress.notifications.failed",
                                attributes={"channel": result.channel, "event_kind": kind},
                            )
                    if not dispatch_outcome.ok:
                        for error in dispatch_outcome.errors:
                            logger.warning("notification send error: %s", error)
                except Exception as e:
                    logger.warning("dispatch failed for %s: %s", type(event).__name__, e)

        async with observe_span(
            "progress.run",
            attributes={"integrations": ",".join(integration_names)},
        ):
            producers = [asyncio.create_task(_producer(i)) for i in integrations]

            async def _with_sentinel(p: asyncio.Task[Any], integration: Integration) -> None:
                await p
                await queue.put(None)

            consumer = asyncio.create_task(_consumer())
            sentinels = [
                asyncio.create_task(_with_sentinel(p, i)) for p, i in zip(producers, integrations, strict=True)
            ]
            await asyncio.gather(*producers)
            await asyncio.gather(*sentinels)
            await queue.put(None)
            await consumer

        logger.info("run completed: exit_code=%s", outcome.exit_code)
        _log_run_summary(outcome)
        record_business_event(
            "progress.run.completed",
            attributes={"exit_code": str(outcome.exit_code)},
        )

        for integration in integrations:
            try:
                await integration.teardown()
            except Exception as e:
                logger.warning("integration %s teardown failed: %s", integration.name, e)

        return outcome


async def _run_reports_for_integration(
    outcome: RunOutcome,
    cfg: CoreConfig,
    integration_name: str,
    *,
    session: aiohttp.ClientSession | None = None,
) -> ReportOutcome:
    """Run the reports pipeline scoped to a single integration.

    Delegates to :func:`progress.cli.reports.pipeline.run_for_integration`
    (T9 per-integration report pipeline).
    """

    report_outcome = await run_for_integration(outcome, cfg, integration_name, session=session)
    if report_outcome.errors:
        for error in report_outcome.errors:
            logger.warning("report generation error for %s: %s", integration_name, error)
    for report_id in report_outcome.report_ids:
        record_business_event("progress.reports.generated", attributes={"report_id": str(report_id)})
    outcome.add_report_events(report_outcome.events)
    return report_outcome


async def _build_notification_events(
    integration: Integration,
    outcome: RunOutcome,
    integration_reports: list[Any],
) -> list[NotificationEvent]:
    """Ask one integration to author its notification events.

    Extracted from the old ``_collect_notification_events`` so the producer
    coroutine can call it inline (T9 streaming).
    """
    result = outcome.results.get(integration.name)
    if result is None:
        return []
    try:
        produced = await integration.build_notification(result=result, reports=integration_reports)
    except Exception as e:
        logger.warning("integration %s build_notification failed: %s", integration.name, e)
        return []
    # ``build_notification`` is contractually typed to return list[NotificationEvent]
    # (base.py); trust that contract rather than re-filtering, which previously
    # raised NameError because NotificationEvent was only imported under TYPE_CHECKING.
    return list(produced)


async def _run_reports(ctx: Components, outcome: RunOutcome, cfg: CoreConfig) -> ReportOutcome:
    """Run the reports pipeline and collect produced ReportEvents into outcome.

    Returns the :class:`ReportOutcome` so :func:`run_notifications` can hand
    each integration its per-report-type :class:`IntegrationReport` list when
    authoring notifications.
    """

    report_outcome = await run_reports(outcome, cfg, session=ctx.session)
    if report_outcome.errors:
        for error in report_outcome.errors:
            logger.warning("report generation error: %s", error)
    for report_id in report_outcome.report_ids:
        record_business_event("progress.reports.generated", attributes={"report_id": str(report_id)})
    outcome.add_report_events(report_outcome.events)
    return report_outcome


async def run_notifications(
    outcome: RunOutcome,
    cfg: CoreConfig,
    *,
    integrations: list[Integration],
    report_outcome: ReportOutcome,
    session: aiohttp.ClientSession | None = None,
) -> None:
    """Author and dispatch one aggregated notification per integration.

    Per spec 10, each integration is the sole author of its own notifications:
    after the reports pipeline has run, every integration's
    :meth:`~progress.integrations.base.Integration.build_notification` hook is
    invoked with its own ``RunResult`` and the pipeline's per-report-type
    :class:`IntegrationReport` list. Only the resulting
    :class:`~progress.cli.notifications.events.NotificationEvent` instances are
    dispatched to channels. Per-item business events
    (``ProposalEvent`` / ``ChangelogEvent`` / ``DiscoveredRepoEvent`` /
    ``ReportEvent``) remain on ``RunOutcome`` for snapshots/observability but
    are NOT dispatched here.
    """

    events = await _collect_notification_events(integrations, outcome, report_outcome)
    if not events:
        return

    notification_cfg: NotificationConfig = cfg.notification
    channels = build_channels(notification_cfg, session=session)
    if not channels:
        logger.info("no enabled notification channels; skipping dispatch")
        return

    renderer = JinjaRenderer(cfg)
    dispatcher = Dispatcher(channels, renderer)
    logger.info("dispatching %d notification event(s)", len(events))
    for event in events:
        try:
            dispatch_outcome = await dispatcher.dispatch(event)
        except Exception as e:
            logger.warning("notification dispatch failed for %s: %s", type(event).__name__, e)
            continue
        for result in dispatch_outcome.results:
            kind = getattr(event, "kind", "unknown")
            if result.ok:
                record_business_event(
                    "progress.notifications.sent",
                    attributes={"channel": result.channel, "event_kind": kind},
                )
            else:
                record_business_event(
                    "progress.notifications.failed",
                    attributes={"channel": result.channel, "event_kind": kind},
                )
        if not dispatch_outcome.ok:
            for error in dispatch_outcome.errors:
                logger.warning("notification send error: %s", error)


async def _collect_notification_events(
    integrations: list[Integration],
    outcome: RunOutcome,
    report_outcome: ReportOutcome,
) -> list[NotificationEvent]:
    """Ask each integration to author its notification(s).

    Groups the pipeline's :class:`IntegrationReport` entries by integration name
    and passes each integration its own list alongside its ``RunResult``. An
    integration that produced no persisted reports gets an empty list and is
    expected to return no notifications (the default hook behavior).
    """

    by_integration: dict[str, list[IntegrationReport]] = {}
    for integration_report in report_outcome.by_integration:
        by_integration.setdefault(integration_report.integration_name, []).append(integration_report)

    events: list[NotificationEvent] = []
    for integration in integrations:
        name = integration.name
        integration_reports = by_integration.get(name, [])
        result = outcome.results.get(name)
        if result is None:
            continue
        try:
            produced = await integration.build_notification(result=result, reports=integration_reports)
        except Exception as e:
            logger.warning("integration %s build_notification failed: %s", name, e)
            continue
        events.extend(event for event in produced if isinstance(event, NotificationEvent))
    return events


async def _run_integration(integration: Integration, cfg: CoreConfig) -> RunResult:
    """Run sync + run for one integration, collecting errors per spec 05/06."""
    async with observe_span(
        f"progress.integration.{integration.name}",
        attributes={"integration": integration.name},
    ):
        try:
            await integration.sync()
            return await integration.run(concurrency=cfg.analysis.concurrency)
        except ProgressException as e:
            logger.warning("integration %s failed: %s", integration.name, e)
            return RunResult(name=integration.name, status="failed", summary=str(e), errors=[e])
        except Exception as e:
            logger.exception("integration %s raised unexpected error", integration.name)
            wrapped = ProgressException(f"unexpected error in {integration.name}: {e}")
            return RunResult(name=integration.name, status="failed", summary=str(e), errors=[wrapped])


def _log_run_summary(outcome: RunOutcome) -> None:
    """Emit one structured line summarizing each integration's outcome.

    A single INFO line per run makes the overall health (and which integration
    degraded) visible without grepping through per-repo DEBUG noise.
    """
    parts = []
    for name, result in outcome.results.items():
        parts.append(f"{name}[status={result.status} reports={len(result.reports)} events={len(result.events)}]")
    summary = " ".join(parts) if parts else "(no integrations)"
    logger.info("run summary: %s", summary)


__all__ = [
    "_build_notification_events",
    "_run_reports_for_integration",
    "run",
    "run_notifications",
]
