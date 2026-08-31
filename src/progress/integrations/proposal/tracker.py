"""Proposal integration business logic (spec 06 / spec proposal).

The tracker owns the four lifecycle hooks. Per spec proposal:

- :meth:`sync` upserts :class:`ProposalTrackerState` rows (one per enabled
  kind) and GCs rows for kinds removed from config (CASCADE drops the
  associated :class:`Proposal` rows).
- :meth:`run(*, concurrency=1)` for each enabled kind: clones or fetches the
  upstream proposal repo, runs the first-run or incremental check, parses
  each changed/new proposal file, applies status normalization, calls AI to
  generate analysis, upserts :class:`Proposal` snapshot rows, then filters
  via :func:`should_notify` and emits ProposalEvents for the notifiable subset.

Per spec proposal §11 the snapshot update (always, for every parsable change)
is decoupled from the notify filter (only the notifiable subset becomes a
report row + event).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import fnmatch
import logging
from pathlib import Path
import re
import shutil
import stat
from typing import TYPE_CHECKING

import aiohttp

from progress.cli.ai import AnalysisResult, build_model_string, get_agent, run_extraction
from progress.cli.git import (
    GitHubClient,
    create_github_client,
    parse_repo_url,
)
from progress.cli.git.local import (
    GIT_TIMEOUT,
    cleanup_git_locks,
    clone,
    fetch,
    get_diff_name_status,
    get_file_creation_time,
    get_file_diff,
    get_head_commit,
    reset_hard,
)
from progress.cli.notifications.events import NotificationEvent, ProposalEvent
from progress.cli.reports.prompts import render_prompt
from progress.config.root import AnalysisConfig, CoreConfig
from progress.db import get_config
from progress.errors import ProgressException, ProposalParseException
from progress.integrations.base import (
    Components,
    ReportSection,
    RunResult,
    SyncResult,
    strip_unknown_config_keys,
)
from progress.integrations.proposal.config import ProposalIntegrationConfig
from progress.integrations.proposal.models import Proposal, ProposalTrackerState
from progress.integrations.proposal.parsers import (
    ProposalParseResult,
    get_parser,
)
from progress.integrations.proposal.statuses import (
    TERMINAL_STATUSES,
    ProposalStatus,
    normalize,
    select_template,
    should_notify,
)
from progress.integrations.registry import register
from progress.integrations.repo.analysis import truncate_diff
from progress.observability import record_business_event, report_severe
from progress.utils.markdown import downgrade_headings
from progress.utils.timezone import now_utc

if TYPE_CHECKING:
    from progress.cli.reports.pipeline import IntegrationReport

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProposalKindConfig:
    """Hard-coded per-kind repo/branch/dir/file-pattern (spec proposal §1)."""

    kind: str
    repo_url: str
    branch: str
    subdirectory: str
    file_pattern: str
    tracker_url: str


_KIND_CONFIGS: dict[str, ProposalKindConfig] = {
    "eip": ProposalKindConfig(
        kind="eip",
        repo_url="https://github.com/ethereum/EIPs.git",
        branch="master",
        subdirectory="EIPS",
        file_pattern="eip-*.md",
        tracker_url="https://github.com/ethereum/EIPs",
    ),
    "erc": ProposalKindConfig(
        kind="erc",
        repo_url="https://github.com/ethereum/ercs.git",
        branch="master",
        subdirectory="ERCS",
        file_pattern="erc-*.md",
        tracker_url="https://github.com/ethereum/ercs",
    ),
    "pep": ProposalKindConfig(
        kind="pep",
        repo_url="https://github.com/python/peps.git",
        branch="main",
        subdirectory="",
        file_pattern="pep-*.rst",
        tracker_url="https://github.com/python/peps",
    ),
    "rfc": ProposalKindConfig(
        kind="rfc",
        repo_url="https://github.com/rust-lang/rfcs.git",
        branch="master",
        subdirectory="text",
        file_pattern="*.md",
        tracker_url="https://github.com/rust-lang/rfcs",
    ),
    "dep": ProposalKindConfig(
        kind="dep",
        repo_url="https://github.com/django/deps.git",
        branch="main",
        subdirectory="",
        file_pattern="*.rst",
        tracker_url="https://github.com/django/deps",
    ),
}

_DEP_FALLBACK_PATTERN = "*.md"
_PROPOSAL_FALLBACK_TITLE = "Proposal Updates"
_CORRUPT_HEAD_PLACEHOLDER = ".invalid"
CLONE_RETRIES: int = 3
CLONE_BACKOFF_BASE_SECONDS: float = 3.0


def _normalize_status(raw_status: str, kind: str, file_path: str) -> str:
    """Normalize a raw status with observability on the ``unknown`` sink.

    Wraps :func:`normalize` so a fall-through to ``unknown`` (empty/misspelled
    raw status, or a parser bug) is never silent: it emits a warning log and a
    ``progress.proposal.status_unknown`` business event carrying ``kind``,
    ``raw_status`` and ``file_name`` for triage.
    """
    normalized = normalize(raw_status, kind)
    if normalized == ProposalStatus.UNKNOWN.value:
        logger.warning(
            "proposal status normalized to unknown: kind=%s raw_status=%r file=%s",
            kind,
            raw_status,
            file_path,
        )
        record_business_event(
            "progress.proposal.status_unknown",
            attributes={"kind": kind, "raw_status": raw_status, "file_name": file_path},
        )
    return normalized


@dataclass
class ProposalReport:
    """In-memory intermediate result produced by ``check`` (spec proposal §14.1)."""

    kind: str
    number: str
    title: str | None
    old_status: str | None
    new_status: str
    file_path: str
    file_url: str
    commit_hash: str
    analysis_summary: str | None = None
    analysis_detail: str | None = None


@register("proposal")
class ProposalIntegration:
    """Track proposal repositories via git-diff incremental detection."""

    name = "proposal"
    config_schema = ProposalIntegrationConfig
    models_module = "progress.integrations.proposal.models"

    def __init__(self) -> None:
        self._ctx: Components | None = None
        self._cfg: CoreConfig | None = None
        self._gh: GitHubClient | None = None
        self._plugin_cfg: ProposalIntegrationConfig = ProposalIntegrationConfig()

    async def setup(self, ctx: Components) -> None:
        self._ctx = ctx
        self._cfg = ctx.cfg
        self._plugin_cfg = await self._load_plugin_config()
        token = self._cfg.github.gh_token.get_secret_value() if self._cfg else ""
        proxy = self._cfg.github.proxy or None if self._cfg else None
        if token and isinstance(ctx.session, aiohttp.ClientSession):
            try:
                self._gh = await create_github_client(
                    ctx.session,
                    oauth_token=token,
                    proxy=proxy,
                )
            except ProgressException as e:
                logger.warning("GitHub client unavailable; RFC PR title resolution will be skipped: %s", e)
                report_severe(e)
                self._gh = None
        else:
            self._gh = None

    async def sync(self) -> SyncResult:
        result = SyncResult()
        desired_kinds = set(self._plugin_cfg.trackers)
        existing = {row.kind: row async for row in ProposalTrackerState.all()}

        for kind in desired_kinds:
            if kind not in existing:
                await ProposalTrackerState.create(kind=kind)
                result.created += 1

        for kind, row in existing.items():
            if kind not in desired_kinds:
                await row.delete()
                result.deleted += 1

        return result

    async def run(self, *, concurrency: int = 1) -> RunResult:
        result = RunResult(name="proposal")
        if self._cfg is None or self._ctx is None:
            return result

        kinds = [k for k in self._plugin_cfg.trackers if k in _KIND_CONFIGS]
        sem = asyncio.Semaphore(max(1, concurrency))

        async def _bounded(kind: str) -> None:
            async with sem:
                await self._run_one_kind(kind, result)

        tasks = [asyncio.create_task(_bounded(kind)) for kind in kinds]
        for task in asyncio.as_completed(tasks):
            try:
                await task
            except ProgressException as e:
                logger.warning("proposal kind tracking failed: %s", e)
                report_severe(e)
                result.errors.append(e)
                result.status = "partial"
            except Exception as e:
                logger.exception("proposal kind tracking crashed")
                wrapped = ProgressException(f"unexpected error in proposal kind: {e}")
                result.errors.append(wrapped)
                result.status = "partial"

        if result.errors and not result.reports and not result.events:
            result.status = "failed"
        elif result.errors:
            result.status = "partial"
        return result

    async def _run_one_kind(self, kind: str, result: RunResult) -> None:
        try:
            reports = await self._check_kind(kind)
        except ProgressException as e:
            logger.warning("proposal check failed for kind %s: %s", kind, e)
            raise

        notifiable = [r for r in reports if should_notify(r.old_status, r.new_status)]
        if not notifiable:
            logger.info("proposal kind %s: %d parsed, 0 notifiable", kind, len(reports))
            return

        logger.info("proposal kind %s: %d parsed, %d notifiable", kind, len(reports), len(notifiable))
        notifiable.sort(key=lambda r: (r.kind, _numeric_or_zero(r.number)))
        section = self._build_kind_section(kind, notifiable)
        result.reports.append(section)
        for report in notifiable:
            result.events.append(self._build_event(report))

    async def _check_kind(self, kind: str) -> list[ProposalReport]:
        """Run the check algorithm for one kind (spec proposal §5)."""
        kind_cfg = _KIND_CONFIGS[kind]
        tracker_state = await self._get_or_create_tracker(kind)
        parser = get_parser(kind)

        repo_path = await self._clone_or_update(kind_cfg)
        head_commit = await self._get_head_safely(repo_path)
        if not head_commit:
            return []

        if tracker_state.last_seen_commit is None:
            reports = await self._first_run_check(
                kind=kind,
                kind_cfg=kind_cfg,
                parser=parser,
                repo_path=repo_path,
                head_commit=head_commit,
            )
        elif head_commit == tracker_state.last_seen_commit:
            tracker_state.last_check_time = now_utc()
            await tracker_state.save()
            return []
        else:
            reports = await self._incremental_check(
                kind=kind,
                kind_cfg=kind_cfg,
                parser=parser,
                repo_path=repo_path,
                old_commit=tracker_state.last_seen_commit,
                new_commit=head_commit,
            )

        tracker_state.last_seen_commit = head_commit
        tracker_state.last_check_time = now_utc()
        await tracker_state.save()
        return reports

    async def _get_or_create_tracker(self, kind: str) -> ProposalTrackerState:
        state = await ProposalTrackerState.filter(kind=kind).first()
        if state is None:
            state = await ProposalTrackerState.create(kind=kind)
        return state

    async def _clone_or_update(self, kind_cfg: ProposalKindConfig) -> Path:
        """Clone or fetch+reset the proposal repo, with corrupt-HEAD self-heal."""
        state_home = self._cfg.state_home if self._cfg else "data"
        slug = _sanitize_slug(kind_cfg.repo_url)
        dest = Path(state_home) / "proposal_repos" / slug

        if dest.is_dir() and (dest / ".git").is_dir():
            try:
                await fetch(dest)
                await reset_hard(dest, "FETCH_HEAD")
                head = await self._get_head_safely(dest)
                if head and _CORRUPT_HEAD_PLACEHOLDER not in head:
                    return dest
                logger.warning("corrupt HEAD detected for %s; recloning", kind_cfg.repo_url)
            except ProgressException as e:
                logger.warning("fetch+reset failed for %s; recloning: %s", kind_cfg.repo_url, e)
                report_severe(e)
            await _rmtree_async(dest)

        token = self._cfg.github.gh_token.get_secret_value() if self._cfg else ""
        clone_url = _inject_token(kind_cfg.repo_url, token)
        await cleanup_git_locks(dest) if dest.is_dir() else None
        clone_timeout = GIT_TIMEOUT * 2
        last_error: Exception | None = None
        for attempt in range(CLONE_RETRIES):
            try:
                await clone(
                    clone_url,
                    dest,
                    branch=kind_cfg.branch,
                    depth=None,
                    single_branch=True,
                    timeout=clone_timeout,
                )
                return dest
            except (ProgressException, Exception) as e:
                last_error = e
                if attempt + 1 < CLONE_RETRIES:
                    delay = CLONE_BACKOFF_BASE_SECONDS * (2**attempt)
                    logger.warning(
                        "clone attempt %d/%d failed for %s: %s; retrying in %.1fs",
                        attempt + 1,
                        CLONE_RETRIES,
                        kind_cfg.kind,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
        raise ProgressException(f"clone failed for {kind_cfg.kind} after {CLONE_RETRIES} attempts: {last_error}")

    async def _first_run_check(
        self,
        *,
        kind: str,
        kind_cfg: ProposalKindConfig,
        parser,
        repo_path: Path,
        head_commit: str,
    ) -> list[ProposalReport]:
        """First-run: parse all files, upsert all, return 1 report (newest file)."""
        proposal_dir = repo_path / kind_cfg.subdirectory if kind_cfg.subdirectory else repo_path
        if not proposal_dir.is_dir():
            return []
        matching_files = sorted(proposal_dir.rglob(kind_cfg.file_pattern))
        if kind == "dep":
            matching_files.extend(sorted(proposal_dir.rglob(_DEP_FALLBACK_PATTERN)))
        if not matching_files:
            return []

        newest_file: Path | None = None
        newest_created_at: str = ""
        for file_path in matching_files:
            try:
                text = file_path.read_text(encoding="utf-8")
            except OSError as e:
                logger.debug("failed to read %s: %s", file_path, e)
                report_severe(e)
                continue
            try:
                parsed = parser(text, _relative_path(file_path, repo_path))
            except ProposalParseException as e:
                record_business_event(
                    "progress.proposal.parse_failed",
                    attributes={"kind": kind},
                )
                logger.debug("parse failed for %s: %s", file_path, e)
                report_severe(e)
                continue
            record_business_event(
                "progress.proposal.parsed",
                attributes={"kind": kind},
            )
            normalized_status = _normalize_status(parsed.raw_status, kind, parsed.file_path)
            await self._upsert_proposal(
                kind=kind,
                parsed=parsed,
                normalized_status=normalized_status,
                tracker_kind=kind,
            )
            created_at = await get_file_creation_time(repo_path, _relative_path(file_path, repo_path))
            if created_at and created_at > newest_created_at:
                newest_created_at = created_at
                newest_file = file_path

        if newest_file is None:
            return []
        text = newest_file.read_text(encoding="utf-8")
        try:
            parsed = parser(text, _relative_path(newest_file, repo_path))
        except ProposalParseException as e:
            record_business_event(
                "progress.proposal.parse_failed",
                attributes={"kind": kind},
            )
            logger.debug("re-parse failed for newest %s: %s", newest_file, e)
            report_severe(e)
            return []
        record_business_event(
            "progress.proposal.parsed",
            attributes={"kind": kind},
        )
        parsed = await self._resolve_rfc_title(kind, parsed)
        normalized_status = _normalize_status(parsed.raw_status, kind, parsed.file_path)
        await self._upsert_proposal(
            kind=kind,
            parsed=parsed,
            normalized_status=normalized_status,
            tracker_kind=kind,
        )
        analysis = await self._analyze_proposal(
            kind=kind,
            parsed=parsed,
            old_status=None,
            new_status=normalized_status,
            repo_path=repo_path,
            file_path=_relative_path(newest_file, repo_path),
            old_commit=None,
            new_commit=head_commit,
            kind_cfg=kind_cfg,
        )
        report = ProposalReport(
            kind=kind,
            number=parsed.number,
            title=parsed.title,
            old_status=None,
            new_status=normalized_status,
            file_path=_relative_path(newest_file, repo_path),
            file_url=_build_file_url(kind_cfg, head_commit, _relative_path(newest_file, repo_path)),
            commit_hash=head_commit,
            analysis_summary=(
                downgrade_headings(analysis.summary) or None if (analysis.summary or analysis.detail) else None
            ),
            analysis_detail=downgrade_headings(analysis.detail) or None if analysis.detail else None,
        )
        return [report]

    async def _incremental_check(
        self,
        *,
        kind: str,
        kind_cfg: ProposalKindConfig,
        parser,
        repo_path: Path,
        old_commit: str,
        new_commit: str,
    ) -> list[ProposalReport]:
        """Incremental check: git diff name-status, Pass1 + Pass2 (spec proposal §5.1)."""
        name_status = await get_diff_name_status(repo_path, old_commit, new_commit)
        filtered = _filter_files(name_status, kind_cfg)
        moved_numbers = _detect_moves(filtered)

        reports: list[ProposalReport] = []
        for status, path in filtered:
            if status.startswith("D"):
                continue
            report = await self._handle_changed(
                kind=kind,
                kind_cfg=kind_cfg,
                parser=parser,
                repo_path=repo_path,
                path=path,
                old_commit=old_commit,
                new_commit=new_commit,
            )
            if report is not None:
                reports.append(report)

        for status, path in filtered:
            if not status.startswith("D"):
                continue
            number = _extract_number_from_path(path, kind)
            if number and number in moved_numbers:
                continue
            report = await self._handle_deleted(
                kind=kind,
                kind_cfg=kind_cfg,
                repo_path=repo_path,
                path=path,
                old_commit=old_commit,
                new_commit=new_commit,
            )
            if report is not None:
                reports.append(report)

        return reports

    async def _handle_changed(
        self,
        *,
        kind: str,
        kind_cfg: ProposalKindConfig,
        parser,
        repo_path: Path,
        path: str,
        old_commit: str,
        new_commit: str,
    ) -> ProposalReport | None:
        """Pass 1: handle a changed/added file (spec proposal §7)."""
        file_full = repo_path / path
        try:
            text = file_full.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("failed to read %s: %s", path, e)
            report_severe(e)
            return None
        try:
            parsed = parser(text, path)
        except ProposalParseException as e:
            record_business_event(
                "progress.proposal.parse_failed",
                attributes={"kind": kind},
            )
            logger.warning("parse failed for %s: %s", path, e)
            report_severe(e)
            return None
        record_business_event(
            "progress.proposal.parsed",
            attributes={"kind": kind},
        )

        parsed = await self._resolve_rfc_title(kind, parsed)
        new_status = _normalize_status(parsed.raw_status, kind, parsed.file_path)
        old_status = await self._lookup_old_status(kind, parsed.number)

        analysis = await self._analyze_proposal(
            kind=kind,
            parsed=parsed,
            old_status=old_status,
            new_status=new_status,
            repo_path=repo_path,
            file_path=path,
            old_commit=old_commit,
            new_commit=new_commit,
            kind_cfg=kind_cfg,
        )
        await self._upsert_proposal(
            kind=kind,
            parsed=parsed,
            normalized_status=new_status,
            tracker_kind=kind,
        )
        return ProposalReport(
            kind=kind,
            number=parsed.number,
            title=parsed.title,
            old_status=old_status,
            new_status=new_status,
            file_path=path,
            file_url=_build_file_url(kind_cfg, new_commit, path),
            commit_hash=new_commit,
            analysis_summary=(
                downgrade_headings(analysis.summary) or None if (analysis.summary or analysis.detail) else None
            ),
            analysis_detail=downgrade_headings(analysis.detail) or None if analysis.detail else None,
        )

    async def _handle_deleted(
        self,
        *,
        kind: str,
        kind_cfg: ProposalKindConfig,
        repo_path: Path,
        path: str,
        old_commit: str,
        new_commit: str,
    ) -> ProposalReport | None:
        """Pass 2: handle a deleted file (spec proposal §8)."""
        number = _extract_number_from_path(path, kind)
        if not number:
            return None
        existing = await Proposal.filter(tracker_id=await self._tracker_id(kind), number=number).first()
        if existing is None:
            logger.debug("delete for unknown proposal %s/%s ignored", kind, number)
            return None
        old_status = existing.status
        if old_status in TERMINAL_STATUSES:
            new_status = old_status
        else:
            new_status = ProposalStatus.WITHDRAWN.value
            existing.status = new_status
            await existing.save()
        return ProposalReport(
            kind=kind,
            number=number,
            title=existing.title,
            old_status=old_status,
            new_status=new_status,
            file_path=path,
            file_url=_build_file_url(kind_cfg, old_commit, path),
            commit_hash=new_commit,
            analysis_summary=None,
            analysis_detail=None,
        )

    async def _resolve_rfc_title(self, kind: str, parsed: ProposalParseResult) -> ProposalParseResult:
        """Resolve Rust RFC title from PR (spec proposal §12)."""
        if kind != "rfc" or self._gh is None:
            return parsed
        pr_number = parsed.extra.get("pr_number")
        if not isinstance(pr_number, int):
            return parsed
        kind_cfg = _KIND_CONFIGS["rfc"]
        try:
            ref = parse_repo_url(kind_cfg.repo_url)
        except ValueError:
            return parsed
        try:
            title = await self._gh.get_pull_request_title(ref, pr_number)
            if title:
                parsed.title = title
        except ProgressException as e:
            logger.warning("RFC PR title lookup failed for #%d: %s", pr_number, e)
            report_severe(e)
        return parsed

    async def _analyze_proposal(
        self,
        *,
        kind: str,
        parsed: ProposalParseResult,
        old_status: str | None,
        new_status: str,
        repo_path: Path,
        file_path: str,
        old_commit: str | None,
        new_commit: str,
        kind_cfg: ProposalKindConfig,
    ) -> AnalysisResult:
        """Run AI analysis for one proposal change (spec proposal §13)."""
        cfg = self._cfg.analysis if self._cfg else AnalysisConfig()
        template_name = select_template(old_status, new_status)
        content_source = parsed.full_text
        if template_name == "proposal_content_modified_prompt.j2" and old_commit:
            try:
                raw_diff = await get_file_diff(repo_path, old_commit, new_commit, file_path)
                content_source = truncate_diff(raw_diff, source=f"proposal {file_path}").text
            except ProgressException as e:
                logger.warning("file diff failed for %s: %s", file_path, e)
                report_severe(e)
                content_source = parsed.full_text

        prompt = render_prompt(
            template_name,
            kind=kind,
            number=parsed.number,
            title=parsed.title or "",
            old_status=old_status or "",
            new_status=new_status,
            proposal_text=content_source,
            language=cfg.language,
        )
        try:
            return await _invoke_agent(prompt, cfg)
        except (ProgressException, Exception) as e:
            logger.warning("proposal AI analysis failed for %s/%s: %s", kind, parsed.number, e)
            report_severe(e)
            return AnalysisResult(summary="", detail="")

    async def _upsert_proposal(
        self,
        *,
        kind: str,
        parsed: ProposalParseResult,
        normalized_status: str,
        tracker_kind: str,
    ) -> None:
        """Upsert the Proposal snapshot row (spec proposal §11)."""
        tracker_id = await self._tracker_id(tracker_kind)
        await Proposal.update_or_create(
            tracker_id=tracker_id,
            number=parsed.number,
            defaults={
                "title": parsed.title,
                "raw_status": parsed.raw_status,
                "status": normalized_status,
            },
        )

    async def _lookup_old_status(self, kind: str, number: str) -> str | None:
        tracker_id = await self._tracker_id(kind)
        existing = await Proposal.filter(tracker_id=tracker_id, number=number).first()
        return existing.status if existing else None

    async def _tracker_id(self, kind: str) -> int:
        state = await ProposalTrackerState.filter(kind=kind).first()
        if state is None:
            state = await ProposalTrackerState.create(kind=kind)
        return state.id

    async def _get_head_safely(self, repo_path: Path) -> str | None:
        try:
            head = await get_head_commit(repo_path)
            return head or None
        except ProgressException as e:
            report_severe(e)
            return None

    def _build_kind_section(self, kind: str, reports: list[ProposalReport]) -> ReportSection:
        kind_cfg = _KIND_CONFIGS.get(kind)
        tracker_url = kind_cfg.tracker_url if kind_cfg else ""
        return ReportSection(
            title=kind.upper(),
            content="",
            payload={
                "kind": kind,
                "tracker_url": tracker_url,
                "reports": [
                    {
                        "kind": r.kind,
                        "number": r.number,
                        "title": r.title,
                        "old_status": r.old_status,
                        "new_status": r.new_status,
                        "file_path": r.file_path,
                        "file_url": r.file_url,
                        "commit_hash": r.commit_hash,
                        "analysis_summary": r.analysis_summary,
                        "analysis_detail": r.analysis_detail,
                    }
                    for r in reports
                ],
            },
        )

    def _build_event(self, report: ProposalReport) -> ProposalEvent:
        return ProposalEvent(
            proposal_kind=report.kind,
            number=_numeric_or_zero(report.number),
            title=report.title or "",
            status=report.new_status,
            url=report.file_url,
            summary=report.analysis_summary or "",
            file_path=report.file_path,
        )

    async def _load_plugin_config(self) -> ProposalIntegrationConfig:
        raw = await get_config("proposal")
        if not raw:
            return ProposalIntegrationConfig()

        raw, _ = strip_unknown_config_keys(raw, ProposalIntegrationConfig)
        try:
            return ProposalIntegrationConfig.model_validate(raw)
        except Exception as e:
            logger.warning("invalid proposal plugin config; using defaults: %s", e)
            report_severe(e)
            return ProposalIntegrationConfig()

    async def build_notification(
        self,
        *,
        result: RunResult,
        reports: list[IntegrationReport],
    ) -> list[NotificationEvent]:
        """Author the aggregated proposal notification (spec 10).

        One notification per run covering every notifiable proposal across all
        kinds. Mirrors the legacy behavior: a single notification listing up to
        five proposal file names (plus a ``more_count``) and linking to the
        published report. The AI title/summary/markpost URL come from the
        pipeline's :class:`IntegrationReport`.
        """
        if not reports:
            return []
        filenames: list[str] = []
        proposals: list[dict[str, str]] = []
        for section in result.reports:
            kind = section.payload.get("kind") or ""
            for item in section.payload.get("reports", []):
                file_path = item.get("file_path") or ""
                if file_path:
                    filenames.append(Path(file_path).name)
                    proposals.append(
                        {
                            "kind": kind.upper(),
                            "number": str(item.get("number") or ""),
                            "title": item.get("title") or "",
                            "old_status": item.get("old_status") or "",
                            "new_status": item.get("new_status") or "",
                            "file_url": item.get("file_url") or "",
                            "file_name": Path(file_path).name,
                        }
                    )
        if not filenames:
            return []
        shown = filenames[:5]
        more_count = max(0, len(filenames) - len(shown))
        integration_report = reports[0]
        return [
            NotificationEvent(
                kind="proposal",
                title=integration_report.title,
                summary=integration_report.summary,
                markpost_url=integration_report.markpost_url,
                total_batches=integration_report.total_batches,
                data={
                    "filenames": shown,
                    "more_count": more_count,
                    "total": len(filenames),
                    "proposals": proposals,
                },
            )
        ]

    async def teardown(self) -> None:
        self._gh = None
        self._ctx = None
        self._cfg = None


async def _invoke_agent(prompt: str, cfg: AnalysisConfig) -> AnalysisResult:
    model_string = build_model_string(cfg)
    if not model_string:
        return AnalysisResult(summary="", detail="")
    api_key = cfg.api_key.get_secret_value() if cfg.api_key else None
    agent = get_agent(AnalysisResult, model=model_string, api_key=api_key, base_url=cfg.base_url or None)
    result = await run_extraction(agent, prompt)
    if isinstance(result, AnalysisResult):
        return result
    return AnalysisResult.model_validate(result)


def _filter_files(
    name_status: list[tuple[str, str]],
    kind_cfg: ProposalKindConfig,
) -> list[tuple[str, str]]:
    """Filter git diff entries by directory + basename pattern (spec proposal §5.3)."""

    result: list[tuple[str, str]] = []
    for status, path in name_status:
        if kind_cfg.subdirectory and not (
            path == kind_cfg.subdirectory or path.startswith(kind_cfg.subdirectory + "/")
        ):
            continue
        basename = path.rsplit("/", 1)[-1]
        if not (
            fnmatch.fnmatch(basename, kind_cfg.file_pattern)
            or (kind_cfg.kind == "dep" and fnmatch.fnmatch(basename, _DEP_FALLBACK_PATTERN))
        ):
            continue
        result.append((status, path))
    return result


def _detect_moves(filtered: list[tuple[str, str]]) -> set[str]:
    """Detect moved proposals by number (spec proposal §5.4)."""
    added_numbers: set[str] = set()
    for status, path in filtered:
        if not status.startswith("D"):
            kind_guess = _guess_kind_from_path(path)
            if kind_guess:
                number = _extract_number_from_path(path, kind_guess)
                if number:
                    added_numbers.add(number)
    if not added_numbers:
        return set()
    moved: set[str] = set()
    for status, path in filtered:
        if not status.startswith("D"):
            continue
        kind_guess = _guess_kind_from_path(path)
        if kind_guess:
            number = _extract_number_from_path(path, kind_guess)
            if number and number in added_numbers:
                moved.add(number)
    return moved


def _guess_kind_from_path(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1].lower()
    if "eip-" in name:
        return "eip"
    if "erc-" in name:
        return "erc"
    if "pep-" in name:
        return "pep"
    if "rfcs" in path.lower():
        return "rfc"
    if "deps" in path.lower():
        return "dep"
    return None


def _extract_number_from_path(path: str, kind: str) -> str:
    """Extract the proposal number from a path/filename (best-effort)."""

    name = path.rsplit("/", 1)[-1]
    patterns = [
        re.compile(r"^eip-(\d+)\.md$", re.IGNORECASE),
        re.compile(r"^erc-(\d+)\.md$", re.IGNORECASE),
        re.compile(r"^pep-(\d+)\.rst$", re.IGNORECASE),
        re.compile(r"^(\d+)-", re.IGNORECASE),
        re.compile(r"^(\d+)"),
    ]
    for pattern in patterns:
        match = pattern.search(name)
        if match:
            return str(int(match.group(1)))
    match = re.search(r"\d+", name)
    return str(int(match.group(0))) if match else ""


def _build_file_url(kind_cfg: ProposalKindConfig, commit: str, file_path: str) -> str:
    """Build a GitHub blob URL for a proposal file at a specific commit."""
    base = kind_cfg.repo_url.rstrip("/").removesuffix(".git")
    return f"{base}/blob/{commit}/{file_path}"


def _relative_path(file_path: Path, base: Path) -> str:
    try:
        return file_path.relative_to(base).as_posix()
    except ValueError:
        return file_path.as_posix()


def _sanitize_slug(url: str) -> str:
    last = url.rstrip("/").rsplit("/", 1)[-1]
    return last.removesuffix(".git") or "repo"


def _inject_token(url: str, token: str) -> str:
    if not token or not url.startswith("https://"):
        return url
    return f"https://x-access-token:{token}@{url[len('https://') :]}"


def _numeric_or_zero(value: str) -> int:

    match = re.search(r"\d+", value or "")
    return int(match.group(0)) if match else 0


async def _rmtree_async(path: Path) -> None:
    loop = asyncio.get_running_loop()

    def _remove() -> None:
        def _onerror(func, filepath, exc_info):
            try:
                Path(filepath).chmod(stat.S_IWRITE)
                func(filepath)
            except OSError:
                pass

        if path.exists():
            shutil.rmtree(path, onexc=_onerror)

    await loop.run_in_executor(None, _remove)


__all__ = ["ProposalIntegration", "ProposalKindConfig", "ProposalReport"]
