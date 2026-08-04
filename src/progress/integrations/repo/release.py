"""Release tracking logic for the repo integration (spec repo §6).

Releases are tracked via the GitHub Releases API. The release checkpoint
(``last_release_tag`` / ``last_release_commit_hash`` / ``last_release_check_time``)
is **independent** from the commit checkpoint (spec repo §2): a check may
advance either one without affecting the other.

Algorithm (spec repo §6.2):
1. Query all releases (GitHub API already filters draft/prerelease).
2. Empty list → ``None``.
3. Normalize the checkpoint timestamp (string / naive datetime → aware UTC).
4. First run → candidate = the latest single release by ``published_at``.
5. Incremental → candidates = all releases with ``published_at > checkpoint``.
6. Hydrate each candidate with its commit SHA.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING

from progress.cli.git.local import get_diff
from progress.errors import ProgressException
from progress.integrations.repo.analysis import TruncatedDiff, truncate_diff
from progress.observability import record_business_event

if TYPE_CHECKING:
    from pathlib import Path

    from progress.cli.git import GitHubClient, RepoRef

logger = logging.getLogger(__name__)

_PUBLISHED_AT_FORMATS: tuple[str, ...] = (
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S+00:00",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S",
)


@dataclass
class ReleaseRecord:
    """One hydrated release ready for analysis (spec repo §6.2)."""

    tag: str
    name: str
    notes: str
    published_at: str
    url: str
    commit_hash: str | None = None
    diff_text: str | None = None
    ai_summary: str = ""
    ai_detail: str = ""


@dataclass
class ReleaseCheckResult:
    """Outcome of one repo's release check (spec repo §6)."""

    candidates: list[ReleaseRecord] = field(default_factory=list)
    latest_tag: str | None = None
    latest_commit_hash: str | None = None
    truncated: bool = False
    total_available: int = 0


def parse_published_at(value: str | None) -> datetime | None:
    """Parse a ``published_at`` timestamp into a timezone-aware UTC datetime.

    Returns ``None`` if parsing fails (per spec repo §6.2 such releases are
    skipped by the caller).
    """
    if not value:
        return None
    for fmt in _PUBLISHED_AT_FORMATS:
        try:
            parsed = datetime.strptime(value, fmt)  # noqa: DTZ007
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def normalize_checkpoint_timestamp(value: object) -> datetime | None:
    """Normalize a stored checkpoint timestamp to a UTC datetime (spec repo §6.2).

    Accepts ``datetime`` (naive → forced UTC) or ISO string. Returns ``None``
    if parsing fails.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        return parse_published_at(value)
    return None


async def check_releases(
    *,
    ref: RepoRef,
    gh: GitHubClient,
    repos_dir: Path,
    last_release_tag: str | None,
    last_release_commit_hash: str | None,
    last_release_check_time: object,
    max_incremental_lookback_releases: int = 3,
) -> ReleaseCheckResult | None:
    """Run the release check for one repo (spec repo §6.2).

    Returns ``None`` when there are no releases to process (empty list).
    Otherwise returns a :class:`ReleaseCheckResult` with hydrated candidates
    (each candidate's commit SHA resolved separately; failure does NOT block).

    Two paths only: first run (no checkpoint → latest single release) and
    incremental (``published_at > checkpoint``). An empty ``candidates`` list
    means "checked successfully, no new releases" — callers advance the
    checkpoint timestamp. ``None`` return means the check could not run
    (empty repo / listing error) — callers must NOT advance the checkpoint.
    """
    all_releases = await _collect_releases(ref, gh)
    if not all_releases:
        return None

    candidates: list[ReleaseRecord] = []
    truncated = False
    total_available = 0
    checkpoint_dt = normalize_checkpoint_timestamp(last_release_check_time)
    if checkpoint_dt is None:
        latest = max(all_releases, key=lambda r: r.published_at or "")
        candidates = [latest] if (latest.published_at) else []
    else:
        for release in all_releases:
            published = parse_published_at(release.published_at)
            if published is None:
                continue
            if published > checkpoint_dt:
                candidates.append(release)
        candidates.sort(key=lambda r: r.published_at or "", reverse=True)
        total_available = len(candidates)
        if len(candidates) > max_incremental_lookback_releases:
            truncated = True
            candidates = candidates[:max_incremental_lookback_releases]

    if not candidates:
        return ReleaseCheckResult(
            candidates=[],
            latest_tag=last_release_tag,
            latest_commit_hash=last_release_commit_hash,
            total_available=total_available,
        )

    dest = repos_dir / f"{ref.owner}_{ref.name}"
    for candidate in candidates:
        await _hydrate_candidate(
            ref=ref,
            gh=gh,
            candidate=candidate,
            dest=dest,
            last_release_commit_hash=last_release_commit_hash,
        )

    candidates.sort(key=lambda r: r.published_at or "", reverse=True)
    latest = candidates[0]
    return ReleaseCheckResult(
        candidates=candidates,
        latest_tag=latest.tag,
        latest_commit_hash=latest.commit_hash,
        truncated=truncated,
        total_available=total_available,
    )


async def _collect_releases(ref: RepoRef, gh: GitHubClient) -> list[ReleaseRecord]:
    """Fetch all releases and hydrate to :class:`ReleaseRecord` (spec repo §6.2).

    Per spec §6.2 step 6, releases with an unparsable ``published_at`` are
    skipped entirely (they cannot be compared against the checkpoint).
    """
    records: list[ReleaseRecord] = []
    try:
        async for release in gh.iter_releases(ref):
            published = release.published_at or ""
            if not published:
                continue
            if parse_published_at(published) is None:
                logger.debug("release %s has unparsable published_at %r; skipped", release.tag, published)
                continue
            records.append(
                ReleaseRecord(
                    tag=release.tag,
                    name=release.name or "",
                    notes=release.body or "",
                    published_at=published,
                    url=release.url,
                )
            )
    except (ProgressException, Exception) as e:
        logger.warning("release listing failed for %s: %s", ref.slug, e)
        record_business_event(
            "progress.git.release_listing_failed",
            attributes={"repo": ref.slug, "owner": ref.owner, "reason": type(e).__name__},
        )
        return []
    return records


async def _hydrate_candidate(
    *,
    ref: RepoRef,
    gh: GitHubClient,
    candidate: ReleaseRecord,
    dest: Path,
    last_release_commit_hash: str | None,
) -> None:
    """Resolve commit SHA + diff for one candidate (spec repo §6.2/6.4).

    Per spec §6.4 diff is only computed for incremental checks with a known
    previous release commit. Failure does NOT block — commit_hash/diff stay None.
    """
    try:
        candidate.commit_hash = await gh.get_release_commit_sha(ref, candidate.tag)
    except ProgressException as e:
        logger.warning("release commit SHA lookup failed for %s@%s: %s", ref.slug, candidate.tag, e)
        candidate.commit_hash = None

    if last_release_commit_hash and candidate.commit_hash and dest.is_dir():
        try:
            raw_diff = await get_diff(
                dest,
                last_release_commit_hash,
                candidate.commit_hash,
            )
            truncated = truncate_diff(raw_diff, source=f"release {ref.slug}@{candidate.tag}")
            candidate.diff_text = truncated.text
        except (ProgressException, Exception) as e:
            logger.warning(
                "release diff failed for %s@%s: %s",
                ref.slug,
                candidate.tag,
                e,
                extra={
                    "repo": ref.slug,
                    "tag": candidate.tag,
                    "old_hash": last_release_commit_hash,
                    "new_hash": candidate.commit_hash,
                },
            )
            record_business_event(
                "progress.git.diff_failed",
                attributes={
                    "reason": "other",
                    "repo": ref.slug,
                    "stage": "release",
                    "tag": candidate.tag,
                },
            )
            candidate.diff_text = None


def truncate_release_diff(diff_text: str | None) -> TruncatedDiff:
    """Truncate release diff per spec repo §6.6."""
    if not diff_text:
        return TruncatedDiff(text="", truncated=False, original_length=0, analyzed_length=0)
    return truncate_diff(diff_text)


__all__ = [
    "ReleaseCheckResult",
    "ReleaseRecord",
    "check_releases",
    "normalize_checkpoint_timestamp",
    "parse_published_at",
    "truncate_release_diff",
]
