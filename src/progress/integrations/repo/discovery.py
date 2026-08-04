"""Owner auto-discovery logic for the repo integration (spec repo §7).

For each enabled GitHub owner, enumerate their repos, identify newly-created
ones (using the ``created_at`` high-water mark), fetch each new repo's README,
analyze it via AI, and emit a :class:`DiscoveredRepoEvent`.

Key rules (spec repo §7):
- First run (watermark None) → report only the single newest repo.
- Incremental → report all repos with ``created_at > watermark``.
- Watermark is always advanced to the newest ``created_at`` seen (even with
  no candidates), guaranteeing no duplicate discovery on the next run.
- Discovered repos are NOT auto-inserted into the Repository table; only an
  event is emitted. Repos already in the Repository table are deduped.
- Forks are filtered out. Repos without a README (404 or fetch failure) are
  skipped (per spec repo §7.3 404 is not logged as a warning).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING

from progress.cli.git.url import parse_repo_url
from progress.cli.notifications.events import DiscoveredRepoEvent
from progress.errors import GitHubNotFoundException, ProgressException
from progress.integrations.repo.analysis import analyze_readme, truncate_readme
from progress.utils.timezone import parse_created_at

if TYPE_CHECKING:
    from progress.cli.git import GitHubClient, RepositoryInfo
    from progress.config.root import AnalysisConfig

logger = logging.getLogger(__name__)


@dataclass
class OwnerDiscoveryResult:
    """Outcome of discovering new repos for one owner (spec repo §7)."""

    events: list[DiscoveredRepoEvent]
    newest_created_at: datetime | None


def normalize_watermark(value: object) -> datetime | None:
    """Normalize a stored ``last_tracked_repo`` watermark to UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        return parse_created_at(value)
    return None


async def discover_owner_repos(
    *,
    gh: GitHubClient,
    owner_name: str,
    owner_type: str,
    watermark: str | None = None,
) -> list[RepositoryInfo]:
    """Enumerate owner's non-fork repos (spec repo §7.2 / §7.4)."""
    repos: list[RepositoryInfo] = []
    try:
        async for repo in gh.list_owner_repos(owner_name, owner_type=owner_type, watermark=watermark):
            if repo.fork:
                continue
            repos.append(repo)
    except ProgressException as e:
        logger.warning("owner repo enumeration failed for %s: %s", owner_name, e)
        return []
    return repos


def select_candidates(
    repos: list[RepositoryInfo],
    watermark: datetime | None,
) -> tuple[list[RepositoryInfo], datetime | None]:
    """Apply the first-run vs incremental selection rule (spec repo §7.2).

    Returns ``(candidates, newest_created_at)``. The newest watermark is
    advanced to the newest repo in the *full* list (not just candidates),
    guaranteeing no duplicate discovery next run.
    """
    parsed: list[tuple[datetime, RepositoryInfo]] = []
    for repo in repos:
        created = parse_created_at(repo.created_at)
        if created is None:
            continue
        parsed.append((created, repo))
    if not parsed:
        return [], None
    parsed.sort(key=lambda pair: pair[0])
    newest = parsed[-1][0]
    if watermark is None:
        return [parsed[-1][1]], newest
    candidates = [repo for created, repo in parsed if created > watermark]
    return candidates, newest


async def process_new_repo(
    *,
    repo: RepositoryInfo,
    gh: GitHubClient,
    known_repo_urls: set[str],
    analysis_cfg: AnalysisConfig,
) -> DiscoveredRepoEvent | None:
    """Process a single candidate repo (spec repo §7.3).

    Returns ``None`` when the repo should be skipped (already tracked, no
    README, README fetch failure other than 404).
    """

    if repo.html_url and repo.html_url in known_repo_urls:
        return None

    try:
        ref = parse_repo_url(repo.html_url or repo.full_name)
        try:
            readme = await gh.get_readme(ref)
        except GitHubNotFoundException:
            return None
        except ProgressException as e:
            logger.warning("README fetch failed for %s: %s", repo.full_name, e)
            return None
    except ValueError:
        return None

    readme_text, _truncated = truncate_readme(readme)
    analysis = await analyze_readme(
        repo_name=repo.full_name,
        description=repo.description,
        readme=readme_text,
        cfg=analysis_cfg,
    )
    created = parse_created_at(repo.created_at)
    discovered_at = created.strftime("%Y-%m-%d %H:%M:%S") if created else ""
    return DiscoveredRepoEvent(
        owner=repo.owner,
        name=repo.full_name,
        url=repo.html_url,
        description=repo.description or "",
        readme_summary=analysis.summary,
        readme_detail=analysis.detail,
        discovered_at=discovered_at,
    )


__all__ = [
    "OwnerDiscoveryResult",
    "discover_owner_repos",
    "normalize_watermark",
    "parse_created_at",
    "process_new_repo",
    "select_candidates",
]
