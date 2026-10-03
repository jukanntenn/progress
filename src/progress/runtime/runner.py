"""runner entry: the thin event-driven pipeline driver (PRFC phase 2).

``RunnerHandle.run_once`` drives the catalog: every integration runs its
sync/run between the ``integration/pre-run`` waterfall and the
``integration/post-run`` parallel dispatch, then (unless trackers-only) its
reports assemble through the ``report/assemble`` waterfall (core action =
the reports pipeline), announce via ``report/generated``, author
notifications through the ``notification/build`` serial dispatch, and
stream out through ``notification/dispatch`` — per integration as it
completes, the streaming semantics preserved. The runner fiber itself stays
ACTIVE: the pipeline runs on demand (``progress run``) or on schedule
(phase 4), never inside ``apply``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from progress.cli.outcome import RunOutcome
from progress.cli.reports.pipeline import run_for_integration
from progress.errors import ProgressException
from progress.integrations.base import Integration, RunResult
from progress.kernel import Definition, Entry
from progress.observability import mark_span_outcome, observe_span, record_business_event, report_severe
from progress.runtime.catalog import (
    AssemblePayload,
    BuildPayload,
    PostRunPayload,
    PreRunPayload,
    ReportGeneratedPayload,
    RunCompletedPayload,
    RunStartedPayload,
)

if TYPE_CHECKING:
    from progress.config.root import CoreConfig

logger = logging.getLogger(__name__)


class RunnerService(Definition):
    service_name = "runner"


class RunnerHandle:
    """The runner service value (``ctx.runner``); ``run_once`` drives events."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    async def run_once(self, *, trackers_only: bool = False) -> RunOutcome:
        integrations: list[Integration] = list(self.ctx.integrations.instances)
        names = [i.name for i in integrations]
        cfg = self.ctx.config  # noqa: F841
        logger.info("run started: integrations=%s trackers_only=%s", names, trackers_only)
        record_business_event(
            "progress.run.started",
            attributes={"component": "cli", "integrations": ",".join(names)},
        )
        await self.ctx.emit("run/started", RunStartedPayload(integration_names=names, trackers_only=trackers_only))

        outcome = RunOutcome()
        queue: asyncio.Queue[Any] = asyncio.Queue()

        async with observe_span("progress.run", attributes={"integrations": ",".join(names)}):
            producers = [asyncio.create_task(self._producer(i, outcome, queue, trackers_only)) for i in integrations]

            async def _sentinel(task: asyncio.Task[None]) -> None:
                await task
                await queue.put(None)

            sentinels = [asyncio.create_task(_sentinel(p)) for p in producers]
            consumer = asyncio.create_task(self._consumer(queue, len(integrations)))
            await asyncio.gather(*producers)
            await asyncio.gather(*sentinels)
            await queue.put(None)
            await consumer

        logger.info("run completed: exit_code=%s", outcome.exit_code)
        self._log_summary(outcome)
        record_business_event("progress.run.completed", attributes={"exit_code": str(outcome.exit_code)})
        await self.ctx.emit("run/completed", RunCompletedPayload(outcome=outcome))
        return outcome

    async def _producer(
        self,
        integration: Integration,
        outcome: RunOutcome,
        queue: asyncio.Queue[Any],
        trackers_only: bool,
    ) -> None:
        name = integration.name
        try:
            pre = PreRunPayload(name=name)
            await self.ctx.waterfall("integration/pre-run", pre)
            if pre.vetoed:
                logger.info("integration %s skipped by pre-run policy: %s", name, pre.reason)
                outcome.add(name, RunResult(name=name, status="skipped", summary=f"pre-run veto: {pre.reason}"))
                return

            async with observe_span(f"progress.integration.{name}", attributes={"integration": name}):
                result = await self._run_integration(integration, self.ctx.config)
                mark_span_outcome(result.status, error_message=f"integration {name} failed")
            outcome.add(name, result)
            await self.ctx.parallel("integration/post-run", PostRunPayload(name=name, result=result))
            record_business_event(
                "progress.integration.run",
                attributes={
                    "integration": name,
                    "status": result.status,
                    "reports": str(len(result.reports)),
                    "events": str(len(result.events)),
                },
            )
            logger.info(
                "integration %s done: status=%s reports=%d events=%d",
                name,
                result.status,
                len(result.reports),
                len(result.events),
            )

            if trackers_only:
                return

            report_outcome = await self._assemble_reports(name, outcome)
            await self._build_and_queue_notifications(integration, outcome, report_outcome, queue)
        except ProgressException as e:
            outcome.add(name, RunResult(name=name, status="failed", summary=str(e), errors=[e]))
        except Exception as e:
            logger.exception("integration %s raised unexpected error", name)
            wrapped = ProgressException(f"unexpected error in {name}: {e}")
            outcome.add(name, RunResult(name=name, status="failed", summary=str(e), errors=[wrapped]))

    async def _run_integration(self, integration: Integration, cfg: CoreConfig) -> RunResult:
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

    async def _assemble_reports(self, name: str, outcome: RunOutcome) -> Any:
        payload = AssemblePayload(name=name, outcome=outcome, session=self.ctx.http)

        async def _default() -> None:
            report_outcome = await run_for_integration(outcome, self.ctx.config, name, session=self.ctx.http)
            if report_outcome.errors:
                for error in report_outcome.errors:
                    logger.warning("report generation error for %s: %s", name, error)
            payload.report_outcome = report_outcome

        try:
            await self.ctx.waterfall_default("report/assemble", payload, default=_default)
        except Exception as e:
            logger.exception("report pipeline failed for %s", name)
            outcome.errors.append(ProgressException(f"report pipeline failed for {name}: {e}"))
            return None
        report_outcome = getattr(payload, "report_outcome", None)
        if report_outcome is None:
            return None
        for report_id in report_outcome.report_ids:
            record_business_event("progress.reports.generated", attributes={"report_id": str(report_id)})
        await self.ctx.emit("report/generated", ReportGeneratedPayload(name=name, report_outcome=report_outcome))
        return report_outcome

    async def _build_and_queue_notifications(
        self,
        integration: Integration,
        outcome: RunOutcome,
        report_outcome: Any,
        queue: asyncio.Queue[Any],
    ) -> None:
        result = outcome.results.get(integration.name)
        if result is None:
            return
        reports = list(report_outcome.by_integration) if report_outcome is not None else []
        payload = BuildPayload(name=integration.name, result=result, reports=reports)
        try:
            await self.ctx.serial("notification/build", payload)
        except Exception as e:
            logger.warning("notification build failed for %s: %s", integration.name, e)
            report_severe(e)
            return
        for event in payload.out:
            await queue.put(event)

    async def _consumer(self, queue: asyncio.Queue[Any], producer_count: int) -> None:
        active = producer_count
        while active > 0:
            event = await queue.get()
            if event is None:
                active -= 1
                continue
            try:
                await self.ctx.parallel("notification/dispatch", event)
            except Exception as e:
                logger.warning("dispatch failed for %s: %s", type(event).__name__, e)
                report_severe(e)

    def _log_summary(self, outcome: RunOutcome) -> None:
        parts = []
        for name, result in outcome.results.items():
            parts.append(f"{name}[status={result.status} reports={len(result.reports)} events={len(result.events)}]")
        logger.info("run summary: %s", " ".join(parts) or "(no integrations)")


def make_runner_entry() -> Entry:
    async def _apply(ctx: Any, config: Any) -> None:
        handle = RunnerHandle(ctx=ctx)

        async def _dispatch_event(event: Any) -> None:
            dispatch_outcome = await ctx.notifications.dispatch(event)
            for result in dispatch_outcome.results:
                kind = getattr(event, "kind", "unknown")
                if result.ok:
                    record_business_event(
                        "progress.notifications.sent", attributes={"channel": result.channel, "event_kind": kind}
                    )
                else:
                    record_business_event(
                        "progress.notifications.failed", attributes={"channel": result.channel, "event_kind": kind}
                    )
            if not dispatch_outcome.ok:
                for error in dispatch_outcome.errors:
                    logger.warning("notification send error: %s", error)

        ctx.on("notification/dispatch", _dispatch_event)
        ctx.provide(RunnerService, handle)

    return Entry(id="runner", plugin=_apply, inject=["config", "http", "integrations", "notifications"])


__all__ = ["RunnerHandle", "RunnerService", "make_runner_entry"]
