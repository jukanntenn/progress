"""Report generation pipeline (spec 09).

The legacy ``reporting.py`` God function is replaced by a staged pipeline,
invoked **once per integration** that produced reports:

    collect_outcome  → render_sections → render_aggregated
    → generate_title_summary → inject_summary → persist → publish_batches

Each stage is independently testable; ``run()`` only orchestrates.
Failures are collected into ``ReportOutcome`` rather than silently swallowed.

Per spec 09's landing matrix, each integration's reports become **one**
aggregated ``Report`` row (no per-item rows). ``report_type`` and
``commit_count`` semantics are integration-specific (see ``_REPORT_TYPE_MAP`` /
``_commit_count_for``). Per spec 09, every MarkPost batch dispatches one
``ReportEvent`` (carrying ``batch_index`` / ``total_batches`` / etc.) collected
into ``ReportOutcome.events`` for the notification pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any

import aiohttp
from pydantic import ValidationError
from tortoise.transactions import in_transaction

from progress.cli.ai import (
    TitleSummary,
    build_model_string,
    get_agent,
    run_extraction,
)
from progress.cli.notifications.events import ReportEvent, ReportRepo
from progress.cli.notifications.status import status_label
from progress.cli.outcome import RunOutcome
from progress.cli.reports.markpost import MarkpostClient, MarkpostError, split_batches, split_sections
from progress.cli.reports.prompts import render_prompt
from progress.config.root import CoreConfig, MarkpostConfig, WebConfig
from progress.db.models.batch import Batch
from progress.db.models.report import Report
from progress.errors import ProgressException
from progress.integrations.base import ReportSection
from progress.integrations.registry import discover_integrations
from progress.observability import record_business_event
from progress.utils.i18n import gettext as _, ngettext, npgettext, pgettext
from progress.utils.markdown import downgrade_headings
from progress.utils.templating import create_environment
from progress.utils.timezone import format_now_local

logger = logging.getLogger(__name__)

DEFAULT_TITLE = "Progress Report"
MAX_DIFF_LENGTH: int = 100_000
TRUNCATE_CHARS: int = 200
BATCH_MARGIN: float = 0.9
MAX_LIST_REPOS = 5
MAX_FAILED_REPOS = 5
MAX_SKIPPED_REPOS = 5
_REPORTS_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "reports"

_REPORT_TYPE_MAP: dict[str, str] = {
    "repo": "repo_update",
    "proposal": "proposal",
    "changelog": "changelog",
    "feed": "feed",
}


def _report_type_for(integration_name: str) -> str:
    """Map an integration name to its persisted ``report_type`` (spec 09)."""
    return _REPORT_TYPE_MAP.get(integration_name, "aggregated")


def _commit_count_for(integration_name: str, report_type: str, sections: list[ReportSection]) -> int:
    """Per-integration commit_count semantics (spec 09 landing matrix).

    - repo (repo_update): sum of payload's ``commit_count`` across sections
    - repo (repo_new):    0 (discovery carries no commits)
    - proposal:           number of notifiable reports (len(sections))
    - changelog:          total new versions (sum of payload's ``new_entries`` length)
    - feed:               total entries across sections (sum of payload's
      ``entries`` length)
    - others:             len(sections)
    """
    if integration_name == "repo":
        if report_type == "repo_new":
            return 0
        return sum(int(s.payload.get("commit_count", 0) or 0) for s in sections)
    if integration_name == "changelog":
        return sum(len(s.payload.get("new_entries", []) or []) for s in sections)
    if integration_name == "feed":
        return sum(len(s.payload.get("entries", []) or []) for s in sections)
    return len(sections)


def _collect_integration_template_dirs() -> list[Path]:
    """Collect ``templates/`` directories from all registered integrations."""

    dirs: list[Path] = [_REPORTS_TEMPLATE_DIR]
    for name in discover_integrations():
        integration_templates = Path(__file__).resolve().parents[2] / "integrations" / name / "templates"
        if integration_templates.is_dir():
            dirs.append(integration_templates)
    return dirs


_env: Any = None


def _get_env() -> Any:
    """Lazily build the Jinja2 environment on first render.

    Building at import time creates an import-order hazard: ``pipeline.py``
    may be imported (transitively) before any integration has registered, so
    :func:`discover_integrations` would return an empty result and the
    integration section templates would never be found. Deferring to first
    render sidesteps the whole ordering problem.
    """
    global _env
    if _env is None:
        env = create_environment(_collect_integration_template_dirs(), autoescape=False)
        env.globals.update({"_": _, "ngettext": ngettext, "npgettext": npgettext, "pgettext": pgettext})  # ty:ignore[no-matching-overload]
        env.globals.update({"status_label": status_label})  # ty:ignore[no-matching-overload]
        _env = env
    return _env


@dataclass
class Section:
    """A rendered section from one integration."""

    integration_name: str
    content: str
    title: str = ""
    status: str = "success"


@dataclass
class ReportContext:
    """Pipeline context for one integration: outcome + rendered sections + metadata.

    ``report_type`` discriminates an integration's own section kinds. The repo
    integration produces two distinct report types (``repo_update`` for tracked
    repo commits/releases and ``repo_new`` for discovered repositories); each
    becomes its own ``ReportContext`` so they aggregate and notify independently
    (spec 09 landing matrix). Other integrations emit exactly one report type.
    """

    outcome: RunOutcome
    integration_name: str
    report_type: str
    sections_input: list[ReportSection] = field(default_factory=list)
    repo_statuses: dict[str, str] = field(default_factory=dict)
    rendered_sections: list[Section] = field(default_factory=list)
    generation_time: str = ""


@dataclass
class BatchUrl:
    """A published batch URL."""

    seq: int
    url: str


@dataclass
class IntegrationReport:
    """One aggregated ``Report`` produced by the pipeline for one integration.

    Per spec 09/10, this is the per-integration hand-off to the notification
    pipeline: an integration's ``build_notification`` hook receives the list of
    ``IntegrationReport`` instances it produced (one per report_type) and uses
    the AI-generated ``title``/``summary`` plus the published ``markpost_url``
    (first batch URL when split across batches) to author its notification(s).
    """

    integration_name: str
    report_type: str
    report_id: int
    title: str = DEFAULT_TITLE
    summary: str = ""
    markpost_url: str = ""
    batch_index: int = 0
    total_batches: int = 1


@dataclass
class ReportOutcome:
    """Result of the report pipeline (structured, not silently swallowed).

    ``by_integration`` records one :class:`IntegrationReport` per aggregated
    ``Report`` row the pipeline persisted, in run order. Each entry carries its
    own AI title/summary and markpost URL, so a downstream
    ``build_notification`` hook can author per-integration notifications without
    the legacy last-integration-wins collapse.

    ``events`` collects the ``ReportEvent`` instances produced by
    ``publish_batches`` — one per MarkPost batch. These are appended to the
    ``RunOutcome`` by the core orchestrator for the notification pipeline.
    """

    status: str = "success"
    report_ids: list[int] = field(default_factory=list)
    by_integration: list[IntegrationReport] = field(default_factory=list)
    batches: list[BatchUrl] = field(default_factory=list)
    errors: list[ProgressException] = field(default_factory=list)
    events: list[ReportEvent] = field(default_factory=list)

    def add_error(self, error: ProgressException) -> None:
        self.errors.append(error)
        if self.status == "success":
            self.status = "partial"


def collect_outcome(outcome: RunOutcome, *, generation_time: str) -> list[ReportContext]:
    """Stage 1: build one ``ReportContext`` per (integration, report_type) pair.

    Most integrations produce a single report type and yield one context. The
    repo integration is special-cased: its sections carry a per-section
    ``report_type`` payload (``repo_update`` for tracked commits/releases,
    ``repo_new`` for discovered repositories), so it is split into one context
    per report type. Each context aggregates and notifies independently (the
    repo integration emits up to two notifications per run).
    """
    contexts: list[ReportContext] = []
    for name, result in outcome.results.items():
        if not result.reports:
            continue
        if name == "repo":
            for report_type, sections in _group_repo_sections(result.reports):
                contexts.append(
                    ReportContext(
                        outcome=outcome,
                        integration_name=name,
                        report_type=report_type,
                        sections_input=sections,
                        repo_statuses={s.title: s.payload.get("status") or result.status for s in sections},
                        generation_time=generation_time,
                    )
                )
            continue
        contexts.append(
            ReportContext(
                outcome=outcome,
                integration_name=name,
                report_type=_report_type_for(name),
                sections_input=list(result.reports),
                repo_statuses={section.title: result.status for section in result.reports},
                generation_time=generation_time,
            )
        )
    return contexts


def _group_repo_sections(sections: list[ReportSection]) -> list[tuple[str, list[ReportSection]]]:
    """Group repo sections by their ``report_type`` payload, preserving order.

    Falls back to ``repo_update`` when a section does not declare a report_type
    (defensive — the repo tracker always sets it). Only groups that have at
    least one section are returned.
    """
    groups: dict[str, list[ReportSection]] = {}
    order: list[str] = []
    for section in sections:
        report_type = section.payload.get("report_type") or "repo_update"
        if report_type not in groups:
            groups[report_type] = []
            order.append(report_type)
        groups[report_type].append(section)
    return [(rt, groups[rt]) for rt in order]


def render_sections(ctx: ReportContext) -> list[Section]:
    """Stage 2: render each section via the integration's own Jinja2 template.

    Per spec 09, the template lookup convention is ``{integration_name}_report.j2``
    inside the integration's own ``templates/`` directory. ``section.payload`` is
    expanded into template variables.
    """
    sections: list[Section] = []
    for sec in ctx.sections_input:
        if sec.payload.get("status") == "skipped":
            continue
        template_name = _pick_section_template(ctx.integration_name, sec)
        try:
            rendered = (
                _get_env()
                .get_template(template_name)
                .render(
                    section=sec,
                    result=ctx.outcome.results.get(ctx.integration_name),
                    integration_name=ctx.integration_name,
                    **sec.payload,
                )
            )
        except Exception as e:
            # A failed render silently falls back to ``sec.content`` (empty for
            # repo sections) — without this event, template/variable bugs show
            # up only as mysteriously blank sections with no signal.
            logger.warning("failed to render section for %s: %s", ctx.integration_name, e, exc_info=True)
            record_business_event(
                "progress.report.section_render_failed",
                attributes={
                    "integration": ctx.integration_name,
                    "template": template_name,
                    "section": sec.title,
                    "reason": type(e).__name__,
                },
            )
            rendered = sec.content
        else:
            record_business_event(
                "progress.report.section_rendered",
                attributes={
                    "integration": ctx.integration_name,
                    "template": template_name,
                    "status": sec.payload.get("status") or "success",
                    "empty": str(not rendered.strip()),
                },
            )
        sections.append(
            Section(
                integration_name=ctx.integration_name,
                content=rendered,
                title=sec.title,
                status=sec.payload.get("status") or "success",
            )
        )
    ctx.rendered_sections = sections
    return sections


def _pick_section_template(integration_name: str, section: ReportSection | None = None) -> str:
    """Resolve the section template name via naming convention.

    An integration may emit sections of more than one ``report_type`` (e.g. the
    repo integration emits both per-repo ``repo_update`` sections and owner
    discovery ``repo_new`` sections, spec 09 landing matrix). Each distinct
    ``report_type`` declared in a section's payload selects its own template
    ``{report_type}_report.j2``; absent a ``report_type`` the integration's
    default ``{integration_name}_report.j2`` applies.
    """
    report_type = section.payload.get("report_type") if section is not None else None
    if report_type:
        return f"{report_type}_report.j2"
    return f"{integration_name}_report.j2"


def render_aggregated(
    ctx: ReportContext,
    *,
    total_batches: int = 1,
    batch_index: int = 0,
    batch_sections: list[Section] | None = None,
    batch_repo_statuses: dict[str, str] | None = None,
) -> str:
    """Stage 3: aggregate all of this integration's sections into one markdown string.

    When ``batch_sections`` is provided, only those sections are rendered
    (used for per-batch rendering). Otherwise all ``ctx.rendered_sections``
    are used (full aggregated report for AI summary generation).
    """
    sections = batch_sections if batch_sections is not None else ctx.rendered_sections
    if not sections:
        return ""
    rendered_reports = [s.content for s in sections]
    repo_statuses = batch_repo_statuses if batch_repo_statuses is not None else ctx.repo_statuses
    env = _get_env()
    template_name = f"aggregated_{ctx.integration_name}.j2"
    try:
        template = env.get_template(template_name)
    except Exception:
        template = env.get_template("aggregated.j2")
    return template.render(
        rendered_reports=rendered_reports,
        repo_statuses=repo_statuses,
        report_type=ctx.report_type,
        generation_time=ctx.generation_time,
        total_batches=total_batches,
        batch_index=batch_index,
    )


async def generate_title_summary(
    aggregated: str,
    cfg: CoreConfig,
    *,
    session: aiohttp.ClientSession | None = None,
) -> TitleSummary:
    """Stage 4: ask the AI for a title + summary; fall back on failure.

    Per spec 09, AI failure must NOT block the pipeline — return a downgraded
    ``TitleSummary`` with the default title and an empty summary.
    """
    model_string = build_model_string(cfg.analysis)
    if not model_string:
        logger.info("AI analysis not configured; using default title")
        return TitleSummary(title=DEFAULT_TITLE, summary="")
    try:
        api_key = cfg.analysis.api_key.get_secret_value() if cfg.analysis.api_key else None
        agent = get_agent(TitleSummary, model=model_string, api_key=api_key, base_url=cfg.analysis.base_url or None)
        prompt = render_prompt(
            "title_summary_prompt.j2",
            aggregated_content=aggregated,
            language=cfg.language,
        )
        result = await run_extraction(agent, prompt)
        if isinstance(result, TitleSummary):
            return result
        return TitleSummary.model_validate(result)
    except (ProgressException, ValidationError) as e:
        logger.warning("AI title/summary generation failed (downgraded): %s", e)
        return TitleSummary(title=DEFAULT_TITLE, summary="")


def inject_summary(aggregated: str, summary: str) -> str:
    """Stage 5: prepend the AI summary (heading-downgraded) to the aggregated content.

    The AI summary's headings are downgraded so they never collide with the
    report's own h2 structure. ``full_content = f"{summary}\\n\\n{aggregated}"``
    when summary is non-empty; otherwise the bare aggregated content. The result
    is what gets persisted as ``Report.content``.
    """
    summary = downgrade_headings((summary or "").strip())
    if not summary:
        return aggregated
    return f"{summary}\n\n{aggregated}"


async def persist(
    ctx: ReportContext,
    full_content: str,
    title_summary: TitleSummary,
) -> int:
    """Stage 6: persist one aggregated ``Report`` row (transactional, spec 09)."""
    commit_count = _commit_count_for(ctx.integration_name, ctx.report_type, ctx.sections_input)
    async with in_transaction():
        report = await Report.create(
            report_type=ctx.report_type,
            repo_id=None,
            title=title_summary.title,
            commit_hash="",
            commit_count=commit_count,
            content=full_content,
        )
    return report.id


def _build_oversize_stub(web_base_url: str, report_id: int) -> str:
    """Build the WebUI back-link stub body for an oversize report (spec 09)."""
    return (
        f"> ⚠️ {_('This content is too large to publish here. ')}"
        f"[{_('View the complete report in the WebUI')}]({web_base_url.rstrip('/')}/report/{report_id})."
    )


async def publish_batches(
    report_id: int,
    aggregated: str,
    summary: str,
    title: str,
    ctx: ReportContext,
    markpost_cfg: MarkpostConfig,
    web_cfg: WebConfig,
) -> list[BatchUrl]:
    """Stage 7: split into batches and upload to MarkPost if enabled (spec 09).

    - ``BATCH_MARGIN = 0.9`` effective limit reserves 10% for summary/template overhead.
    - Each batch dispatches one ``ReportEvent`` (collected into ``ctx.events`` via
      the returned outcome).
    - Oversize handling: a rendered batch that exceeds ``max_batch_size`` is never
      silently dropped. When ``web.base_url`` is configured it degrades to a WebUI
      back-link stub (full content always lives in ``Report.content``); otherwise
      the batch is recorded with an empty URL and the outcome is marked partial.
    - Batch row semantics: >1 URL → ``Batch`` rows + ``Report.markpost_url=None``;
      ==1 URL → write ``Report.markpost_url`` directly, no Batch rows.
    - ``Batch.title`` carries the clean title (no ``(n/m)`` suffix).
    """
    if not markpost_cfg.enabled:
        return []
    client = MarkpostClient(markpost_cfg)
    effective_limit = int(client.max_batch_size * BATCH_MARGIN)
    batches = split_batches(aggregated, effective_limit)
    if not batches:
        return []

    web_base_url = web_cfg.base_url.strip() if web_cfg.base_url else ""
    urls: list[BatchUrl] = []
    total_batches = len(batches)
    for seq, body in enumerate(batches):
        batch_title_clean = title
        body_to_upload = body
        body_size = len(body.encode("utf-8"))
        if body_size > client.max_batch_size:
            record_business_event(
                "progress.markpost.batch_oversize",
                attributes={
                    "report_id": str(report_id),
                    "batch_index": str(seq),
                    "total_batches": str(total_batches),
                    "body_size": str(body_size),
                    "max_batch_size": str(client.max_batch_size),
                },
            )
            if web_base_url:
                body_to_upload = _build_oversize_stub(web_base_url, report_id)
            else:
                logger.error(
                    "report %s batch %d/%d exceeds max_batch_size (%d > %d) and "
                    "web.base_url is unset; recording empty batch",
                    report_id,
                    seq + 1,
                    total_batches,
                    body_size,
                    client.max_batch_size,
                )
                urls.append(BatchUrl(seq=seq, url=""))
                continue
        batch_title_dispatch = batch_title_clean
        if total_batches > 1:
            batch_title_dispatch = f"{batch_title_clean} ({seq + 1}/{total_batches})"
        url = await client.upload(body_to_upload, title=batch_title_dispatch)
        urls.append(BatchUrl(seq=seq, url=url))

    await _persist_batch_rows(report_id, title, urls)
    return urls


async def _persist_batch_rows(report_id: int, clean_title: str, urls: list[BatchUrl]) -> None:
    """Per spec 09: >1 URL → Batch rows; ==1 URL → Report.markpost_url direct."""
    if not urls:
        return
    if len(urls) == 1:
        await Report.filter(id=report_id).update(markpost_url=urls[0].url)
        return
    await Batch.filter(report_id=report_id).delete()
    rows = [Batch(report_id=report_id, title=clean_title, markpost_url=url.url, seq=url.seq) for url in urls]
    await Batch.bulk_create(rows)


def _format_generation_time(cfg: CoreConfig) -> str:
    """Format now in the configured core timezone for the report footer.

    Thin wrapper over :func:`progress.utils.timezone.format_now_local`. Kept as
    a call-site local for readability where ``cfg`` is already in scope.
    """
    return format_now_local(cfg.timezone)


async def run(
    outcome: RunOutcome,
    cfg: CoreConfig,
    *,
    session: aiohttp.ClientSession | None = None,
) -> ReportOutcome:
    """Orchestrate the full pipeline. Only orchestrates — no business logic.

    Iterates each integration that produced reports, running the staged
    pipeline once per integration. ``ReportOutcome.events`` collects every
    ``ReportEvent`` produced across all integrations' batches.
    """
    result = ReportOutcome()
    try:
        generation_time = _format_generation_time(cfg)
        contexts = collect_outcome(outcome, generation_time=generation_time)
        for ctx in contexts:
            await _run_one_integration(ctx, cfg, session=session, outcome=result)
    except ProgressException as e:
        result.add_error(e)
        if result.status == "success":
            result.status = "partial"
    except Exception as e:
        result.add_error(ProgressException(f"report pipeline failed: {e}"))
        result.status = "failed"
    return result


async def run_for_integration(
    outcome: RunOutcome,
    cfg: CoreConfig,
    integration_name: str,
    *,
    session: aiohttp.ClientSession | None = None,
) -> ReportOutcome:
    """Run the report pipeline for a single integration.

    Filters ``collect_outcome`` to contexts matching ``integration_name`` and
    runs only those. Returns a :class:`ReportOutcome` scoped to that integration.
    """
    result = ReportOutcome()
    try:
        generation_time = _format_generation_time(cfg)
        all_contexts = collect_outcome(outcome, generation_time=generation_time)
        contexts = [ctx for ctx in all_contexts if ctx.integration_name == integration_name]
        for ctx in contexts:
            await _run_one_integration(ctx, cfg, session=session, outcome=result)
    except ProgressException as e:
        result.add_error(e)
        if result.status == "success":
            result.status = "partial"
    except Exception as e:
        result.add_error(ProgressException(f"report pipeline failed for {integration_name}: {e}"))
        result.status = "failed"
    return result


async def _run_one_integration(
    ctx: ReportContext,
    cfg: CoreConfig,
    *,
    session: aiohttp.ClientSession | None = None,
    outcome: ReportOutcome,
) -> None:
    """Run the staged pipeline for one (integration, report_type) context.

    Records the produced :class:`IntegrationReport` (AI title/summary +
    markpost URL + batch split) on ``outcome.by_integration`` so a downstream
    ``build_notification`` hook can author per-integration notifications.
    """
    try:
        render_sections(ctx)
        if not ctx.rendered_sections:
            return

        # Generate full aggregated report for AI summary
        full_aggregated = render_aggregated(ctx)
        title_summary = await generate_title_summary(full_aggregated, cfg, session=session)

        # Persist full content to database (for WebUI)
        full_content = inject_summary(full_aggregated, title_summary.summary)
        report_id = await persist(ctx, full_content, title_summary)
        outcome.report_ids.append(report_id)
        logger.info(
            "report persisted: integration=%s report_type=%s report_id=%d title=%s",
            ctx.integration_name,
            ctx.report_type,
            report_id,
            title_summary.title,
        )

        markpost_url = ""
        total_batches = 1
        if cfg.markpost.enabled:
            try:
                client = MarkpostClient(cfg.markpost)
                effective_limit = int(client.max_batch_size * BATCH_MARGIN)
                section_batches = split_sections(ctx.rendered_sections, effective_limit)
                total_batches = len(section_batches)

                urls: list[BatchUrl] = []
                for batch_index, batch_sections in enumerate(section_batches):
                    # The summary grid (✅/❌/➖ counts + repo list) is a global
                    # status view of the whole run, so every batch renders it from
                    # the full ``ctx.repo_statuses`` — which includes skipped
                    # repos that ``render_sections`` deliberately omits from the
                    # section bodies. Rebuilding it from ``batch_sections`` (as the
                    # per-batch notification payload below does) dropped every ➖
                    # repo from the published MarkPost page while the DB copy kept
                    # them, producing the "➖ 0 / missing repos" discrepancy.
                    batch_aggregated = render_aggregated(
                        ctx,
                        total_batches=total_batches,
                        batch_index=batch_index,
                        batch_sections=batch_sections,
                        batch_repo_statuses=ctx.repo_statuses,
                    )

                    # Per-batch notification payload lists only the repos carried
                    # by this batch's sections (titles+status from render_sections).
                    batch_repo_statuses = {bs.title: bs.status for bs in batch_sections}

                    record_business_event(
                        "progress.report.publish_split",
                        attributes={
                            "integration": ctx.integration_name,
                            "report_type": ctx.report_type,
                            "total_sections": str(len(ctx.sections_input)),
                            "batch_index": str(batch_index),
                            "total_batches": str(total_batches),
                            "batch_repo_statuses_count": str(len(batch_repo_statuses)),
                            "ctx_repo_statuses_count": str(len(ctx.repo_statuses)),
                        },
                    )

                    # Prepend summary to each batch body
                    batch_body = inject_summary(batch_aggregated, title_summary.summary)

                    # Upload to MarkPost
                    batch_title = title_summary.title
                    if total_batches > 1:
                        batch_title = f"{title_summary.title} ({batch_index + 1}/{total_batches})"

                    body_to_upload = batch_body
                    body_size = len(batch_body.encode("utf-8"))
                    web_base_url = cfg.web.base_url.strip() if cfg.web.base_url else ""

                    if body_size > client.max_batch_size:
                        record_business_event(
                            "progress.markpost.batch_oversize",
                            attributes={
                                "report_id": str(report_id),
                                "report_type": ctx.report_type,
                                "batch_index": str(batch_index),
                                "total_batches": str(total_batches),
                                "body_size": str(body_size),
                                "max_batch_size": str(client.max_batch_size),
                            },
                        )
                        if web_base_url:
                            body_to_upload = _build_oversize_stub(web_base_url, report_id)
                        else:
                            logger.error(
                                "report %s batch %d/%d exceeds max_batch_size (%d > %d) and "
                                "web.base_url is unset; recording empty batch and marking partial",
                                report_id,
                                batch_index + 1,
                                total_batches,
                                body_size,
                                client.max_batch_size,
                            )
                            urls.append(BatchUrl(seq=batch_index, url=""))
                            outcome.add_error(
                                ProgressException(
                                    f"report {report_id} batch {batch_index + 1}/{total_batches} "
                                    f"exceeds max_batch_size and web.base_url is unset"
                                )
                            )
                            continue

                    url = await client.upload(body_to_upload, title=batch_title)
                    record_business_event(
                        "progress.markpost.published",
                        attributes={
                            "report_id": str(report_id),
                            "report_type": ctx.report_type,
                        },
                    )
                    urls.append(BatchUrl(seq=batch_index, url=url))

                    # Collect per-batch event: derive commit count directly from the
                    # batch's own sections (their titles map back to sections_input).
                    batch_input_sections = [
                        s for s in ctx.sections_input if s.title in {bs.title for bs in batch_sections}
                    ]
                    batch_commit_count = _commit_count_for(
                        ctx.integration_name,
                        ctx.report_type,
                        batch_input_sections,
                    )
                    batch_repo_status_list = [
                        ReportRepo(name=name, status=status) for name, status in batch_repo_statuses.items()
                    ]
                    outcome.events.append(
                        ReportEvent(
                            title=f"{_('Progress Report for Open Source Projects')}"
                            + (f" ({batch_index + 1}/{total_batches})" if total_batches > 1 else ""),
                            summary=_("This report covered {count} projects with {commits} commits total").format(
                                count=len(batch_sections), commits=batch_commit_count
                            ),
                            report_url=url,
                            repos=batch_repo_status_list,
                            batch_index=batch_index,
                            total_batches=total_batches,
                            batch_commit_count=batch_commit_count,
                            batch_repo_statuses=batch_repo_status_list,
                        )
                    )

                await _persist_batch_rows(report_id, title_summary.title, urls)
                outcome.batches.extend(urls)
                total_batches = max(1, len(urls))
                markpost_url = urls[0].url if urls else ""
                logger.info(
                    "markpost published: integration=%s report_type=%s report_id=%d batches=%d",
                    ctx.integration_name,
                    ctx.report_type,
                    report_id,
                    len(urls),
                )
            except MarkpostError as e:
                reason = str(e)[:100]
                record_business_event(
                    "progress.markpost.failed",
                    attributes={
                        "report_id": str(report_id),
                        "report_type": ctx.report_type,
                        "reason": reason,
                    },
                )
                logger.error(
                    "markpost upload failed: report_id=%d report_type=%s reason=%s",
                    report_id,
                    ctx.report_type,
                    reason,
                )
                outcome.add_error(ProgressException(reason))
            except ProgressException as e:
                outcome.add_error(e)
        outcome.by_integration.append(
            IntegrationReport(
                integration_name=ctx.integration_name,
                report_type=ctx.report_type,
                report_id=report_id,
                title=title_summary.title,
                summary=title_summary.summary,
                markpost_url=markpost_url,
                total_batches=total_batches,
            )
        )
    except ProgressException as e:
        outcome.add_error(e)
    except Exception as e:
        outcome.add_error(ProgressException(f"integration {ctx.integration_name} report pipeline failed: {e}"))


__all__ = [
    "BATCH_MARGIN",
    "MAX_DIFF_LENGTH",
    "MAX_FAILED_REPOS",
    "MAX_LIST_REPOS",
    "MAX_SKIPPED_REPOS",
    "TRUNCATE_CHARS",
    "BatchUrl",
    "IntegrationReport",
    "ReportContext",
    "ReportOutcome",
    "Section",
    "collect_outcome",
    "generate_title_summary",
    "inject_summary",
    "persist",
    "publish_batches",
    "render_aggregated",
    "render_sections",
    "run",
    "run_for_integration",
]
