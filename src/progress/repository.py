"""Repository manager - unified management of all repository operations."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .analyzer import ClaudeCodeAnalyzer
from .config import Config
from .consts import parse_repo_name
from .db import UTC
from .enums import Protocol
from .github import GitHubClient, normalize_repo_url
from .models import Repository
from .reporter import MarkdownReporter
from .utils import get_now

logger = logging.getLogger(__name__)


def _get_database():
    """Get database instance (lazy import)."""
    from . import db

    return db.database


@dataclass
class SyncResult:
    """Synchronization result."""

    created: int
    updated: int
    deleted: int

    def __str__(self):
        return (
            f"Created: {self.created}, Updated: {self.updated}, Deleted: {self.deleted}"
        )


@dataclass
class RepositoryReport:
    """Repository check report."""

    repo_name: str
    repo_slug: str
    repo_web_url: str
    branch: str
    commit_count: int
    current_commit: str
    previous_commit: str | None
    commit_messages: list[str]
    analysis_markdown: str
    truncated: bool
    original_diff_length: int
    analyzed_diff_length: int

    @property
    def content(self) -> str:
        if hasattr(self, "_content"):
            return self._content
        return self.analysis_markdown

    @content.setter
    def content(self, value: str):
        self._content = value


@dataclass
class CheckAllResult:
    """Check all repositories result."""

    reports: list[RepositoryReport]
    total_commits: int
    repo_statuses: dict[str, str]

    def get_status_count(self) -> tuple[int, int, int]:
        success = sum(1 for s in self.repo_statuses.values() if s == "success")
        failed = sum(1 for s in self.repo_statuses.values() if s == "failed")
        skipped = sum(1 for s in self.repo_statuses.values() if s == "skipped")
        return success, failed, skipped


class RepositoryManager:
    """Repository manager - unified management of all repository operations."""

    def __init__(
        self,
        github_client: GitHubClient,
        analyzer: ClaudeCodeAnalyzer,
        reporter: MarkdownReporter,
        config: Config,
    ):
        """Initialize repository manager.

        Args:
            github_client: GitHub client
            analyzer: Claude analyzer
            reporter: Report generator
            config: Configuration object
        """
        self.github_client = github_client
        self.analyzer = analyzer
        self.reporter = reporter
        self.config = config
        self.logger = logger

    def sync(self, repos_config: list) -> SyncResult:
        """Sync repository configuration to database.

        Args:
            repos_config: List of repository configurations

        Returns:
            SyncResult synchronization result
        """
        database = _get_database()
        configured_urls = set()
        created_count = 0
        updated_count = 0

        with database.atomic():
            for repo_config in repos_config:
                url, branch, enabled, repo_protocol = self._extract_repo_config(
                    repo_config
                )
                normalized_url = normalize_repo_url(
                    url, repo_protocol, self.config.github.protocol
                )
                name = parse_repo_name(url)
                configured_urls.add(normalized_url)

                repo, created = Repository.get_or_create(
                    url=normalized_url,
                    defaults={
                        "name": name,
                        "branch": branch,
                        "enabled": enabled,
                    },
                )

                if not created:
                    repo.name = name
                    repo.branch = branch
                    repo.enabled = enabled
                    repo.url = normalized_url
                    repo.save()
                    updated_count += 1
                    self.logger.debug(
                        f"Updated repository config: {repo.name} ({repo.url})"
                    )
                else:
                    created_count += 1
                    self.logger.info(f"Added new repository: {repo.name} ({repo.url})")

            deleted_count = (
                Repository.delete()
                .where(Repository.url.not_in(configured_urls))
                .execute()
            )

            if deleted_count > 0:
                self.logger.info(
                    f"Deleted {deleted_count} repositories not in configuration"
                )

        return SyncResult(
            created=created_count, updated=updated_count, deleted=deleted_count
        )

    def list_enabled(self) -> list[Repository]:
        """Get all enabled repositories.

        Returns:
            List of enabled repositories
        """
        database = _get_database()
        with database.connection_context():
            return list(Repository.select().where(Repository.enabled == True))

    def get_by_name(self, name: str) -> Repository | None:
        """Get repository by name.

        Args:
            name: Repository name

        Returns:
            Repository object or None
        """
        database = _get_database()
        try:
            with database.connection_context():
                return Repository.get(Repository.name == name)
        except Repository.DoesNotExist:
            return None

    def update_commit(self, repo_id: int, commit_hash: str) -> None:
        """Update repository's last commit hash.

        Args:
            repo_id: Repository ID
            commit_hash: Commit hash
        """
        database = _get_database()
        with database.atomic():
            repo = Repository.get_by_id(repo_id)
            repo.last_commit_hash = commit_hash
            repo.last_check_time = get_now(UTC)
            repo.save()

    def check(self, repo: Repository) -> RepositoryReport | None:
        """Check code changes for a single repository.

        Args:
            repo: Repository object

        Returns:
            RepositoryReport check report, or None if no changes
        """
        self.logger.info(f"Checking repository: {repo.url} (branch: {repo.branch})")

        is_first_time = not repo.last_commit_hash
        repo_path = self.github_client.clone_or_update(
            repo.url, repo.branch, is_first_time
        )

        current_commit = self.github_client.get_current_commit(repo_path)
        self.logger.debug(f"Current commit: {current_commit[:8]}")

        if repo.last_commit_hash == current_commit:
            self.logger.debug("No new commits, skipping")
            return None

        previous_commit = repo.last_commit_hash

        if not previous_commit:
            lookback_commits = self.config.analysis.first_run_lookback_commits
            total_commits = self.github_client.get_total_commit_count(repo_path)

            if total_commits <= 1:
                self.logger.warning(
                    "Repository has only one commit, cannot compare, skipping"
                )
                self.update_commit(repo.id, current_commit)
                return None

            effective_lookback = min(lookback_commits, total_commits)
            self.logger.info(
                f"First check, looking back {effective_lookback} commits (configured: {lookback_commits})"
            )

            if total_commits > effective_lookback:
                previous_commit = self.github_client.get_nth_commit_from_head(
                    repo_path, effective_lookback
                )
                if not previous_commit:
                    self.logger.warning(
                        "Failed to resolve base commit for first check, falling back to second-latest commit"
                    )
                    previous_commit = self.github_client.get_previous_commit(repo_path)
                if not previous_commit:
                    self.logger.warning(
                        "Failed to resolve base commit for first check, skipping"
                    )
                    self.update_commit(repo.id, current_commit)
                    return None
                self.logger.debug(f"Base commit: {previous_commit[:8]}")

                commit_messages = self.github_client.get_commit_messages(
                    repo_path, previous_commit, current_commit
                )
                commit_count = self.github_client.get_commit_count(
                    repo_path, previous_commit, current_commit
                )
                diff = self.github_client.get_commit_diff(
                    repo_path, previous_commit, current_commit
                )
            else:
                recent_hashes = self.github_client.get_recent_commit_hashes(
                    repo_path, effective_lookback
                )
                previous_commit = recent_hashes[-1] if recent_hashes else None
                if previous_commit:
                    self.logger.debug(f"Oldest selected commit: {previous_commit[:8]}")

                commit_messages = self.github_client.get_recent_commit_messages(
                    repo_path, effective_lookback
                )
                commit_count = len(recent_hashes)
                diff = self.github_client.get_recent_commit_patches(
                    repo_path, effective_lookback
                )
        else:
            commit_messages = self.github_client.get_commit_messages(
                repo_path, previous_commit, current_commit
            )
            commit_count = self.github_client.get_commit_count(
                repo_path, previous_commit, current_commit
            )

            diff = self.github_client.get_commit_diff(
                repo_path, previous_commit, current_commit
            )

        self.logger.info(f"Found {commit_count} new commits")

        if not diff.strip():
            self.logger.warning("Diff is empty, skipping analysis")
            self.update_commit(repo.id, current_commit)
            return None

        self.logger.info("Analyzing code changes...")
        analysis_markdown, truncated, original_length, analyzed_length = (
            self.analyzer.analyze_diff(repo.name, repo.branch, diff, commit_messages)
        )

        self.update_commit(repo.id, current_commit)

        self.logger.info(f"Repository {repo.name} check completed")

        repo_slug = parse_repo_name(repo.url)
        repo_web_url = f"https://github.com/{repo_slug}"

        return RepositoryReport(
            repo_name=repo.name,
            repo_slug=repo_slug,
            repo_web_url=repo_web_url,
            branch=repo.branch,
            commit_count=commit_count,
            current_commit=current_commit,
            previous_commit=previous_commit,
            commit_messages=commit_messages,
            analysis_markdown=analysis_markdown,
            truncated=truncated,
            original_diff_length=original_length,
            analyzed_diff_length=analyzed_length,
        )

    def check_all(
        self, repos: list[Repository] | None = None, concurrency: int = 1
    ) -> CheckAllResult:
        """Check all repositories (supports concurrency, skip on failure).

        Args:
            repos: List of repositories, None to get enabled repositories automatically
            concurrency: Concurrency level (1 for serial)

        Returns:
            CheckAllResult with reports, total commits, and status mapping
        """
        if repos is None:
            repos = self.list_enabled()

        reports = []
        total_commits = 0
        repo_statuses = {}

        def process(repo_obj: Repository) -> tuple[RepositoryReport | None, str]:
            """Process single repository, return (report, status)."""
            try:
                result = self.check(repo_obj)
                if result:
                    return result, "success"
                return None, "skipped"
            except Exception as e:
                self.logger.error(
                    f"Failed to check repository {repo_obj.name}: {e}", exc_info=True
                )
                return None, "failed"

        if concurrency > 1:
            self.logger.info(
                f"Using concurrent mode to check repositories (threads: {concurrency})"
            )
            lock = threading.Lock()

            def process_with_lock(
                repo_obj: Repository,
            ) -> tuple[RepositoryReport | None, str]:
                result, status = process(repo_obj)
                with lock:
                    repo_statuses[repo_obj.name] = status
                return result, status

            with ThreadPoolExecutor(
                max_workers=concurrency, thread_name_prefix="repo_checker"
            ) as executor:
                futures = {
                    executor.submit(process_with_lock, repo): repo for repo in repos
                }
                for future in as_completed(futures):
                    try:
                        result, status = future.result()
                        if result:
                            with lock:
                                reports.append(result)
                                total_commits += result.commit_count
                    except Exception as e:
                        repo = futures[future]
                        self.logger.error(
                            f"Exception while processing repository {repo.name}: {e}"
                        )
                        with lock:
                            repo_statuses[repo.name] = "failed"
        else:
            self.logger.info("Using serial mode to check repositories")
            for repo_obj in repos:
                result, status = process(repo_obj)
                repo_statuses[repo_obj.name] = status
                if result:
                    reports.append(result)
                    total_commits += result.commit_count

        return CheckAllResult(
            reports=reports, total_commits=total_commits, repo_statuses=repo_statuses
        )

    @staticmethod
    def _extract_repo_config(repo_config):
        """Extract repository parameters from configuration.

        Args:
            repo_config: dict or Pydantic model

        Returns:
            (url, branch, enabled, protocol) tuple
        """
        if hasattr(repo_config, "url"):
            protocol = getattr(repo_config, "protocol", None)
            protocol_value = protocol.value if protocol else None
            return (
                repo_config.url,
                repo_config.branch,
                repo_config.enabled,
                protocol_value,
            )
        protocol = repo_config.get("protocol")
        protocol_value = (
            protocol.value
            if protocol
            else None
            if isinstance(protocol, Protocol)
            else protocol
        )
        return (
            repo_config["url"],
            repo_config.get("branch", "main"),
            repo_config.get("enabled", True),
            protocol_value,
        )
