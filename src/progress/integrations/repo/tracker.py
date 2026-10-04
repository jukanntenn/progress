"""Repo integration business logic (spec 06 / spec repo).

The tracker owns the four lifecycle hooks defined by the :class:`Integration`
protocol (spec repo §4):

- :meth:`setup` — receives :class:`Components` (cfg + aiohttp session) and
  loads the ``section="repo"`` plugin config.
- :meth:`sync` — upserts :class:`Repository` / :class:`GitHubOwner` rows from
  the ``section="repo"`` config; GCs rows that no longer appear in config.
- :meth:`run(*, concurrency=1)` — for each enabled repo: release tracking +
  commit diff analysis (with AI); for each enabled owner: discover newly
  created repos. Produces ``reports`` (→ reports pipeline) and ``events``
  (→ notifications dispatcher).
- :meth:`teardown` — releases references; aiohttp session is owned by lifespan.

Per spec 02 zero-config: empty GitHub token still runs sync (no GitHub API
needed) but skips release tracking and owner discovery.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiohttp

from progress.cli.git import CommitMessage, GitHubClient, RepoRef, create_github_client, get_head_commit, parse_repo_url
from progress.cli.notifications.events import DiscoveredRepoEvent, NotificationEvent
from progress.config.root import AnalysisConfig, CoreConfig
from progress.db import get_config
from progress.errors import ProgressException
from progress.integrations.base import (
    Components,
    ReportSection,
    RunResult,
    SyncResult,
    strip_unknown_config_keys,
)
from progress.integrations.registry import register
from progress.integrations.repo.analysis import (
    analyze_commit_diff,
    analyze_release,
    truncate_diff,
)
from progress.integrations.repo.commit import (
    DiffResult,
    clone_or_fetch,
    compute_diff,
    is_empty_diff,
)
from progress.integrations.repo.config import (
    RepoIntegrationConfig,
    derive_repo_name,
    normalize_repo_url,
)
from progress.integrations.repo.discovery import (
    OwnerDiscoveryResult,
    discover_owner_repos,
    normalize_watermark,
    process_new_repo,
    select_candidates,
)
from progress.integrations.repo.models import GitHubOwner, Repository
from progress.integrations.repo.release import (
    ReleaseCheckResult,
    check_releases,
)
from progress.observability import record_business_event, report_severe
from progress.utils.markdown import downgrade_headings, render_markdown
from progress.utils.timezone import now_utc

if TYPE_CHECKING:
    from progress.cli.reports.pipeline import IntegrationReport

logger = logging.getLogger(__name__)


_DIFF_FAILURE_BAD_OBJECT_MARKERS = (
    "bad object",
    "bad revision",
    "unknown revision",
    "could not get object info",
    "not our ref",
)


def _classify_diff_failure(message: str) -> str:
    """Coarse reason tag for a git diff failure, used as a metric attribute.

    ``bad_object`` covers the recurring shallow-clone checkpoint case (the stored
    ``old_hash`` was GC'd); everything else collapses to ``other``.
    """
    lowered = message.lower()
    return "bad_object" if any(m in lowered for m in _DIFF_FAILURE_BAD_OBJECT_MARKERS) else "other"


@register("repo")
class RepoIntegration:
    """Track GitHub repositories: clone, diff, persist report, advance checkpoint."""

    name = "repo"
    config_schema = RepoIntegrationConfig
    models_module = "progress.integrations.repo.models"

    def __init__(self) -> None:
        self._ctx: Components | None = None
        self._cfg: CoreConfig | None = None
        self._gh: GitHubClient | None = None
        self._plugin_cfg: RepoIntegrationConfig = RepoIntegrationConfig()

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
                logger.warning("GitHub client unavailable; repo run will skip API calls: %s", e)
                report_severe(e)
                self._gh = None
        else:
            logger.warning(
                "github.gh_token not set; release tracking and owner discovery disabled (spec 02 zero-config)"
            )

    async def sync(self) -> SyncResult:
        result = SyncResult()
        plugin_cfg = self._plugin_cfg

        desired_repo_urls = {normalize_repo_url(item.url) for item in plugin_cfg.repos}
        existing_repos = {r.url: r async for r in Repository.all()}

        for cfg_item in plugin_cfg.repos:
            normalized = normalize_repo_url(cfg_item.url)
            row = existing_repos.get(normalized)
            derived_name = derive_repo_name(cfg_item.url)
            if row is None:
                await Repository.create(
                    url=normalized,
                    name=derived_name,
                    branch=cfg_item.branch,
                    enabled=cfg_item.enabled,
                    track_commits=cfg_item.track_commits,
                    track_releases=cfg_item.track_releases,
                )
                result.created += 1
            else:
                changed = False
                if row.name != derived_name:
                    row.name = derived_name
                    changed = True
                if row.branch != cfg_item.branch:
                    row.branch = cfg_item.branch
                    changed = True
                if row.enabled != cfg_item.enabled:
                    row.enabled = cfg_item.enabled
                    changed = True
                if row.track_commits != cfg_item.track_commits:
                    row.track_commits = cfg_item.track_commits
                    changed = True
                if row.track_releases != cfg_item.track_releases:
                    row.track_releases = cfg_item.track_releases
                    changed = True
                if changed:
                    await row.save()
                    result.updated += 1

        for url, row in existing_repos.items():
            if url not in desired_repo_urls:
                await row.delete()
                result.deleted += 1

        desired_owner_keys = {(item.type, item.name) for item in plugin_cfg.owners}
        existing_owners = {(o.owner_type, o.name): o async for o in GitHubOwner.all()}
        for item in plugin_cfg.owners:
            key = (item.type, item.name)
            row = existing_owners.get(key)
            if row is None:
                await GitHubOwner.create(
                    owner_type=item.type,
                    name=item.name,
                    enabled=item.enabled,
                )
                result.created += 1
            elif row.enabled != item.enabled:
                row.enabled = item.enabled
                await row.save()
                result.updated += 1

        for key, row in existing_owners.items():
            if key not in desired_owner_keys:
                await row.delete()
                result.deleted += 1

        return result

    async def run(self, *, concurrency: int = 1) -> RunResult:
        result = RunResult(name="repo")
        if self._cfg is None or self._ctx is None:
            return result

        repos_dir = Path(self._cfg.state_home) / "repos"
        repos_dir.mkdir(parents=True, exist_ok=True)

        await self._run_repo_checks(result, repos_dir, concurrency=concurrency)
        await self._run_owner_discovery(result)

        if result.errors and not result.reports and not result.events:
            result.status = "failed"
        elif result.errors:
            result.status = "partial"
        return result

    async def _run_repo_checks(
        self,
        result: RunResult,
        repos_dir: Path,
        *,
        concurrency: int,
    ) -> None:
        enabled_repos = [repo async for repo in Repository.filter(enabled=True)]
        if not enabled_repos:
            return
        logger.info("checking %d repositories (concurrency=%d)", len(enabled_repos), concurrency)

        sem = asyncio.Semaphore(max(1, concurrency))

        async def _bounded(repo_row: Repository) -> None:
            async with sem:
                await self._run_one_repo(repo_row, repos_dir, result)

        tasks = [asyncio.create_task(_bounded(repo)) for repo in enabled_repos]
        for task in asyncio.as_completed(tasks):
            try:
                await task
            except ProgressException as e:
                logger.warning("repo tracking failed: %s", e)
                report_severe(e)
                record_business_event("progress.repos.checked", attributes={"status": "failed"})
                result.errors.append(e)
                result.status = "partial"
            except Exception as e:
                logger.exception("repo tracking crashed")
                record_business_event("progress.repos.checked", attributes={"status": "failed"})
                wrapped = ProgressException(f"unexpected error tracking repo: {e}")
                result.errors.append(wrapped)
                result.status = "partial"

    async def _run_one_repo(self, repo_row: Repository, repos_dir: Path, result: RunResult) -> None:
        try:
            ref = parse_repo_url(repo_row.url)
        except ValueError as e:
            raise ProgressException(f"invalid repo url {repo_row.url!r}: {e}") from e
        repo_label = repo_row.name or ref.slug
        logger.info("repo %s: processing (branch=%s)", repo_label, repo_row.branch)
        dest = repos_dir / f"{ref.owner}_{ref.name}"
        token = self._cfg.github.gh_token.get_secret_value() if self._cfg else ""

        await clone_or_fetch(
            ref=ref,
            dest=dest,
            branch=repo_row.branch,
            token=token,
            state_home=self._cfg.state_home if self._cfg else "data",
            lookback=self._plugin_cfg.first_run_lookback_commits,
        )

        release_result: ReleaseCheckResult | None = None
        if repo_row.track_releases:
            release_result = await self._check_releases_for_repo(ref, repo_row, dest)
        else:
            release_result = ReleaseCheckResult(
                latest_tag=repo_row.last_release_tag,
                latest_commit_hash=repo_row.last_release_commit_hash,
            )
        commit_failed_reason: str | None = None
        if repo_row.track_commits:
            try:
                commit_result = await self._compute_commit_diff(dest, repo_row)
            except ProgressException as e:
                if "unreachable" in str(e).lower() and "advancing checkpoint" in str(e).lower():
                    logger.warning(
                        "checkpoint object unreachable for %s; advancing checkpoint and using HEAD-relative diff",
                        repo_row.url,
                        extra={"repo": repo_row.name or ref.slug, "old_hash": repo_row.last_commit_hash},
                    )
                    record_business_event(
                        "progress.git.checkpoint_advanced",
                        attributes={"repo": repo_row.name or ref.slug, "reason": "unreachable_base"},
                    )
                    repo_row.last_commit_hash = None
                    commit_result = await self._compute_commit_diff(dest, repo_row)
                else:
                    logger.warning(
                        "commit diff failed for %s: %s",
                        repo_row.url,
                        e,
                        extra={
                            "repo": repo_row.name or ref.slug,
                            "old_hash": repo_row.last_commit_hash,
                            "reason": _classify_diff_failure(str(e)),
                        },
                    )
                    record_business_event(
                        "progress.git.diff_failed",
                        attributes={
                            "reason": _classify_diff_failure(str(e)),
                            "repo": repo_row.name or ref.slug,
                            "stage": "commit",
                        },
                    )
                    report_severe(e)
                    commit_result = None
                    commit_failed_reason = str(e)
                    result.errors.append(e)
                    if result.status == "success":
                        result.status = "partial"
        else:
            commit_result = None
            commit_failed_reason = None
            repo_row.last_commit_hash = await _get_head_safely(dest)
            repo_row.last_check_time = now_utc()
            await repo_row.save(update_fields=["last_commit_hash", "last_check_time", "updated_at"])

        has_commits = commit_result is not None and not is_empty_diff(commit_result)
        has_releases = release_result is not None and bool(release_result.candidates)
        if not has_commits and not has_releases and not commit_failed_reason:
            logger.info("repo %s: no changes since last run (skipped)", repo_label)
            record_business_event(
                "progress.repos.checked",
                attributes={"status": "skipped", "repo": repo_row.name or ref.slug},
            )
            # Emit a minimal skipped section so the report/notification pipelines
            # see an explicit per-repo status instead of an absent report.
            result.reports.append(
                ReportSection(
                    title=repo_row.name or ref.slug,
                    content="",
                    payload={
                        "report_type": "repo_update",
                        "status": "skipped",
                        "repo_name": repo_row.name or ref.slug,
                        "repo_web_url": repo_row.url,
                        "branch": repo_row.branch,
                        "commit_count": 0,
                        "commits": [],
                        "analysis_summary": "",
                        "analysis_detail": "",
                        "truncated": False,
                        "original_diff_length": 0,
                        "analyzed_diff_length": 0,
                        "releases": None,
                    },
                )
            )
            return

        section = await self._build_repository_section(
            repo_row=repo_row,
            ref=ref,
            dest=dest,
            commit_result=commit_result,
            release_result=release_result,
            commit_failed_reason=commit_failed_reason,
        )
        commit_n = commit_result.commit_count if commit_result else 0
        release_n = len(release_result.candidates) if release_result and release_result.candidates else 0
        if section is not None:
            result.reports.append(section)
            logger.info(
                "repo %s: %d %s, %d %s tracked",
                repo_row.name,
                commit_n,
                "commit" if commit_n == 1 else "commits",
                release_n,
                "release" if release_n == 1 else "releases",
            )
        # Emit the true per-repo outcome: diff_failed when the commit diff raised
        # (e.g. a GC'd checkpoint 'bad object'), success otherwise. Previously this
        # always reported success, hiding recurring failures from the dashboard.
        record_business_event(
            "progress.repos.checked",
            attributes={
                "status": "diff_failed" if commit_failed_reason else "success",
                "repo": repo_row.name or ref.slug,
                "commit_count": str(commit_n),
                "release_count": str(release_n),
            },
        )

        await self._advance_commit_checkpoint(repo_row, commit_result, dest)
        await self._advance_release_checkpoint(repo_row, release_result)

    async def _check_releases_for_repo(
        self,
        ref: RepoRef,
        repo_row: Repository,
        dest: Path,
    ) -> ReleaseCheckResult | None:
        if self._gh is None:
            return None
        try:
            return await check_releases(
                ref=ref,
                gh=self._gh,
                repos_dir=dest.parent,
                last_release_tag=repo_row.last_release_tag,
                last_release_commit_hash=repo_row.last_release_commit_hash,
                last_release_check_time=repo_row.last_release_check_time,
                max_incremental_lookback_releases=(
                    self._plugin_cfg.max_incremental_lookback_releases if self._plugin_cfg else 3
                ),
            )
        except Exception as e:
            logger.warning("release check failed for %s; continuing to commit analysis: %s", ref.slug, e)
            report_severe(e)
            record_business_event(
                "progress.git.release_listing_failed",
                attributes={
                    "repo": ref.slug,
                    "owner": ref.owner,
                    "reason": type(e).__name__,
                },
            )
            return None

    async def _compute_commit_diff(self, dest: Path, repo_row: Repository) -> DiffResult | None:
        lookback = max(1, self._plugin_cfg.first_run_lookback_commits)
        return await compute_diff(dest=dest, old_hash=repo_row.last_commit_hash, lookback=lookback)

    async def _build_repository_section(
        self,
        *,
        repo_row: Repository,
        ref: RepoRef,
        dest: Path,
        commit_result: DiffResult | None,
        release_result: ReleaseCheckResult | None,
        commit_failed_reason: str | None = None,
    ) -> ReportSection | None:
        cfg = self._cfg.analysis if self._cfg else AnalysisConfig()

        analysis_summary = ""
        analysis_detail = ""
        commit_count = 0
        commit_messages: list[CommitMessage] = []
        truncated_flag = False
        original_diff_length = 0
        analyzed_diff_length = 0
        current_commit = repo_row.last_commit_hash or ""

        if commit_result is not None and not is_empty_diff(commit_result):
            truncated = truncate_diff(commit_result.diff, source=f"commit {repo_row.name or ref.slug}")
            commit_count = commit_result.commit_count
            commit_messages = list(commit_result.commit_messages)
            current_commit = commit_result.previous_commit
            truncated_flag = truncated.truncated
            original_diff_length = truncated.original_length
            analyzed_diff_length = truncated.analyzed_length
            if truncated.truncated:
                # A length distribution here would have surfaced the "100016"
                # double-truncation artifact (Bug 3) at a glance.
                record_business_event(
                    "progress.diff.truncated",
                    attributes={
                        "repo": repo_row.name or ref.slug,
                        "original_length": str(original_diff_length),
                        "analyzed_length": str(analyzed_diff_length),
                    },
                )
            # analysis_prompt expects the original list[str] shape; rebuild it
            # from the structured CommitMessage so the AI prompt contract is
            # unchanged even though the template now consumes structured commits.
            commit_messages_text = [f"{c.subject}\n{c.body}".strip() for c in commit_messages]
            ai_result = await analyze_commit_diff(
                repo_name=repo_row.name or ref.slug,
                branch=repo_row.branch,
                diff_text=commit_result.diff,
                commit_messages=commit_messages_text,
                truncated=truncated,
                cfg=cfg,
            )
            analysis_summary = downgrade_headings(ai_result.summary)
            analysis_detail = downgrade_headings(ai_result.detail)

        releases_payload: list[dict[str, Any]] | None = None
        if release_result is not None and release_result.candidates:
            releases_payload = []
            for candidate in release_result.candidates:
                ai_result = await analyze_release(
                    repo_name=ref.slug,
                    branch=repo_row.branch,
                    tag=candidate.tag,
                    name=candidate.name,
                    notes=candidate.notes,
                    published_at=candidate.published_at,
                    commit_hash=candidate.commit_hash,
                    diff_text=candidate.diff_text,
                    cfg=cfg,
                )
                candidate.ai_summary = downgrade_headings(ai_result.summary)
                candidate.ai_detail = downgrade_headings(ai_result.detail)
                # Sanitize release notes to balanced, allowlisted HTML before template
                # interpolation. GitHub release bodies are untrusted; rendering them via
                # render_markdown normalizes the markup to the allowlist (details/summary
                # are kept and rebalanced by the sanitizer), closing the XSS vector of
                # shipping raw, potentially-unbalanced notes inside the template's outer
                # release <details>.
                notes_html = render_markdown(candidate.notes or "")
                releases_payload.append(
                    {
                        "tag": candidate.tag,
                        "name": candidate.name,
                        "notes_html": notes_html,
                        "published_at": candidate.published_at,
                        "url": candidate.url,
                        "ai_summary": candidate.ai_summary,
                        "ai_detail": candidate.ai_detail,
                    }
                )

        if release_result is not None and release_result.truncated:
            record_business_event(
                "progress.releases.truncated",
                attributes={
                    "repo": repo_row.name or ref.slug,
                    "available": str(release_result.total_available),
                    "shown": str(len(release_result.candidates)),
                },
            )

        payload: dict[str, Any] = {
            "repo_name": repo_row.name or ref.slug,
            "repo_web_url": repo_row.url,
            "branch": repo_row.branch,
            "commit_count": commit_count,
            "current_commit": current_commit,
            "previous_commit": repo_row.last_commit_hash,
            # Structured (subject, body) pairs for the report template; replaces the
            # old bare-string ``commit_messages`` field that forced the template to
            # guess single- vs multi-line from a ``"\n" in message`` check.
            "commits": [{"subject": c.subject, "body": c.body} for c in commit_messages],
            "analysis_summary": analysis_summary,
            "analysis_detail": analysis_detail,
            "truncated": truncated_flag,
            "original_diff_length": original_diff_length,
            "analyzed_diff_length": analyzed_diff_length,
            "releases_truncated": release_result.truncated if release_result else False,
            "releases_total_available": release_result.total_available if release_result else 0,
            "releases": releases_payload,
        }
        if commit_failed_reason:
            payload["status"] = "failed"
            payload["failure_reason"] = commit_failed_reason
        else:
            payload["status"] = "success"
        return ReportSection(title=payload["repo_name"], content="", payload=payload)

    async def _advance_commit_checkpoint(
        self,
        repo_row: Repository,
        commit_result: DiffResult | None,
        dest: Path,
    ) -> None:
        if commit_result is None or is_empty_diff(commit_result):
            return
        new_head = await _get_head_safely(dest)
        if not new_head:
            return
        repo_row.last_commit_hash = new_head
        repo_row.last_check_time = now_utc()
        await repo_row.save()

    async def _advance_release_checkpoint(
        self,
        repo_row: Repository,
        release_result: ReleaseCheckResult | None,
    ) -> None:
        if release_result is None:
            return
        if release_result.candidates:
            repo_row.last_release_tag = release_result.latest_tag
            repo_row.last_release_commit_hash = release_result.latest_commit_hash
        repo_row.last_release_check_time = now_utc()
        await repo_row.save()

    async def _run_owner_discovery(self, result: RunResult) -> None:
        if self._gh is None:
            return
        known_repo_urls = {repo.url async for repo in Repository.all()}
        async for owner in GitHubOwner.filter(enabled=True):
            try:
                discovery = await self._discover_for_owner(owner, known_repo_urls)
            except ProgressException as e:
                logger.warning("owner discovery failed for %s: %s", owner.name, e)
                report_severe(e)
                result.errors.append(e)
                result.status = "partial"
                continue
            except Exception as e:
                logger.exception("owner discovery crashed for %s", owner.name)
                record_business_event(
                    "progress.repos.discovery_failed",
                    attributes={"owner": owner.name, "reason": type(e).__name__},
                )
                wrapped = ProgressException(f"unexpected error discovering {owner.name}: {e}")
                result.errors.append(wrapped)
                result.status = "partial"
                continue

            result.events.extend(discovery.events)
            if discovery.events:
                result.reports.append(self._build_discovery_section(owner.name, discovery.events))
            for _event in discovery.events:
                record_business_event("progress.repos.discovered", attributes={"owner": owner.name})

    async def _discover_for_owner(
        self,
        owner: GitHubOwner,
        known_repo_urls: set[str],
    ) -> OwnerDiscoveryResult:
        gh = self._gh
        if gh is None:
            return OwnerDiscoveryResult(events=[], newest_created_at=None)
        watermark = normalize_watermark(owner.last_tracked_repo)
        repos = await discover_owner_repos(
            gh=gh,
            owner_name=owner.name,
            owner_type=owner.owner_type,
            watermark=str(watermark) if watermark else None,
        )
        candidates, newest = select_candidates(repos, watermark)
        events: list[DiscoveredRepoEvent] = []
        for candidate in candidates:
            event = await process_new_repo(
                repo=candidate,
                gh=gh,
                known_repo_urls=known_repo_urls,
                analysis_cfg=self._cfg.analysis if self._cfg else AnalysisConfig(),
            )
            if event is not None:
                events.append(event)
                if event.url:
                    known_repo_urls.add(event.url)

        owner.last_check_time = now_utc()
        if newest is not None:
            owner.last_tracked_repo = newest
        await owner.save()
        return OwnerDiscoveryResult(events=events, newest_created_at=newest)

    def _build_discovery_section(self, owner_name: str, events: list[DiscoveredRepoEvent]) -> ReportSection:
        return ReportSection(
            title=f"Discovered repos under {owner_name}",
            content="",
            payload={
                "report_type": "repo_new",
                "status": "success",
                "owner": owner_name,
                "new_repos": [
                    {
                        "name": e.name,
                        "url": e.url,
                        "description": e.description,
                        "readme_summary": e.readme_summary,
                        "readme_detail": e.readme_detail,
                        "discovered_at": e.discovered_at,
                    }
                    for e in events
                ],
            },
        )

    async def _load_plugin_config(self) -> RepoIntegrationConfig:
        raw = await get_config("repo")
        if not raw:
            return RepoIntegrationConfig()

        raw, _ = strip_unknown_config_keys(raw, RepoIntegrationConfig)
        try:
            return RepoIntegrationConfig.model_validate(raw)
        except Exception as e:
            logger.warning("invalid repo plugin config; falling back to defaults: %s", e)
            report_severe(e)
            return RepoIntegrationConfig()

    async def build_notification(
        self,
        *,
        result: RunResult,
        reports: list[IntegrationReport],
    ) -> list[NotificationEvent]:
        """Author the repo integration's notifications (spec 10).

        Up to two notifications per run, one per report type:

        - ``repo_update``: tracked repos' commits/releases. Carries the stats
          grid payload (``repo_statuses``, ``total_commits``) the Feishu/email
          templates render as the 4-column metrics + Failed/Skipped boxes.
        - ``discovered_repo``: newly discovered repos under tracked owners.
          Carries the discovered repo list (name/url, top-5 + more_count).

        The AI title/summary/markpost URL come from the matching
        :class:`IntegrationReport` produced by the pipeline.
        """
        if not reports:
            return []
        update_sections = [s for s in result.reports if s.payload.get("report_type") != "repo_new"]
        discovery_sections = [s for s in result.reports if s.payload.get("report_type") == "repo_new"]
        events: list[NotificationEvent] = []

        update_report = next((r for r in reports if r.report_type == "repo_update"), None)
        if update_report and update_sections:
            repo_statuses = {s.title: s.payload.get("status") or result.status for s in update_sections}
            repo_urls = {s.title: s.payload.get("repo_web_url") or "" for s in update_sections}
            total_commits = sum(int(s.payload.get("commit_count", 0) or 0) for s in update_sections)
            repos_with_updates = sum(
                1
                for s in update_sections
                if int(s.payload.get("commit_count", 0) or 0) > 0 or s.payload.get("releases")
            )
            events.append(
                NotificationEvent(
                    kind="repo_update",
                    title=update_report.title,
                    summary=update_report.summary,
                    markpost_url=update_report.markpost_url,
                    batch_index=update_report.batch_index,
                    total_batches=update_report.total_batches,
                    data={
                        "repo_statuses": repo_statuses,
                        "repo_urls": repo_urls,
                        "total_commits": total_commits,
                        "total_repos": len(repo_statuses),
                        "repos_with_updates": repos_with_updates,
                    },
                )
            )

        new_report = next((r for r in reports if r.report_type == "repo_new"), None)
        if new_report and discovery_sections:
            discovered: list[dict[str, str]] = []
            for section in discovery_sections:
                discovered.extend(section.payload.get("new_repos") or [])
            if discovered:
                events.append(
                    NotificationEvent(
                        kind="discovered_repo",
                        title=new_report.title,
                        summary=new_report.summary,
                        markpost_url=new_report.markpost_url,
                        total_batches=new_report.total_batches,
                        data={"repos": discovered},
                    )
                )
        return events

    async def teardown(self) -> None:
        self._gh = None
        self._ctx = None
        self._cfg = None


async def _get_head_safely(dest: Path) -> str | None:

    try:
        return await get_head_commit(dest)
    except ProgressException as e:
        report_severe(e)
        return None


__all__ = ["RepoIntegration"]
