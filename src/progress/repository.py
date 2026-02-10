"""Repository manager - unified management of all repository operations."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .analyzer import ClaudeCodeAnalyzer
from .config import Config
from .consts import parse_repo_name, WORKSPACE_DIR_DEFAULT
from .db import UTC
from .enums import Protocol
from .github import GitClient, normalize_repo_url
from .github_client import GitHubClient
from .models import Repository
from .reporter import MarkdownReporter
from .repo import Repo
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
    analysis_summary: str
    analysis_detail: str
    truncated: bool
    original_diff_length: int
    analyzed_diff_length: int
    release_data: dict | None = None
    release_summary: str = ""
    release_detail: str = ""

    @property
    def content(self) -> str:
        if hasattr(self, "_content"):
            return self._content
        return f"{self.analysis_summary}\n\n{self.analysis_detail}"

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
        analyzer: ClaudeCodeAnalyzer,
        reporter: MarkdownReporter,
        config: Config,
    ):
        """Initialize repository manager.

        Args:
            analyzer: Claude analyzer
            reporter: Report generator
            config: Configuration object
        """
        self.analyzer = analyzer
        self.reporter = reporter
        self.config = config
        self.logger = logger

        workspace_dir = (
            config.workspace_dir
            if hasattr(config, "workspace_dir")
            else WORKSPACE_DIR_DEFAULT
        )

        self.git = GitClient(
            workspace_dir=workspace_dir, timeout=config.github.git_timeout
        )

        self.gh_token = config.github.gh_token
        self.proxy = config.github.proxy
        self.protocol = config.github.protocol

        self.github_client = GitHubClient(
            token=self.gh_token,
            proxy=self.proxy
        )

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
                url = repo_config.url
                branch = repo_config.branch
                enabled = repo_config.enabled
                repo_protocol = repo_config.protocol
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

    def check(self, repo: Repository) -> RepositoryReport | None:
        """Check code changes and releases for a single repository.

        Args:
            repo: Repository object

        Returns:
            RepositoryReport check report, or None if no changes
        """
        self.logger.info(f"Checking repository: {repo.url} (branch: {repo.branch})")

        repo_obj = Repo(
            repo,
            self.git,
            self.config,
            gh_token=self.gh_token,
            proxy=self.proxy,
            protocol=self.protocol,
            github_client=self.github_client,
        )

        # Clone or update repository
        repo_obj.clone_or_update()

        # Check releases (independent from commits)
        release_data = None
        release_summary = ""
        release_detail = ""
        try:
            release_data = repo_obj.check_releases()
            if release_data:
                self.logger.info("Found new releases, analyzing...")
                release_summary, release_detail = self.analyzer.analyze_releases(
                    str(repo.name), str(repo.branch), release_data
                )
                latest = release_data["latest_release"]
                commit_hash = latest.get("commit_hash")
                if commit_hash:
                    repo_obj.update_releases(latest["tag"], commit_hash)
        except Exception as e:
            self.logger.warning(f"Release analysis failed for {repo.name}: {e}")
            if release_data:
                from .i18n import gettext as _
                latest = release_data["latest_release"]
                tag = latest.get("tag", "unknown")
                notes = latest.get("notes", "")
                release_summary = _("**New release {tag} is available.**\n\n").format(tag=tag)
                if notes:
                    release_summary += _("**Release Notes:**\n\n{notes}\n\n").format(notes=notes[:500])
                release_summary += _("*AI analysis was not available. View release notes on GitHub for full details.*")
                release_detail = _("**Release Information:**\n\n")
                release_detail += f"- **Tag:** {tag}\n"
                release_detail += f"- **Name:** {latest.get('name', tag)}\n"
                release_detail += f"- **Published:** {latest.get('published_at', 'unknown')}\n"
                if notes:
                    release_detail += f"\n**Release Notes:**\n\n{notes}\n"
                if release_data.get("intermediate_releases"):
                    release_detail += f"\n**Intermediate Releases:** {len(release_data['intermediate_releases'])} additional release(s)\n"

        # Get diff data, returns None if no new commits
        diff_data = repo_obj.get_diff()
        if diff_data is None and not release_data:
            self.logger.debug("No new commits or releases, skipping")
            return None

        # Initialize with empty values
        diff = ""
        previous_commit = None
        commit_count = 0
        commit_messages = []
        analysis_summary = ""
        analysis_detail = ""
        truncated = False
        original_length = 0
        analyzed_length = 0
        current_commit = None

        if diff_data:
            diff, previous_commit, commit_count, commit_messages, _ = diff_data

            if diff.strip():
                self.logger.info(f"Found {commit_count} new commits")
                self.logger.info("Analyzing code changes...")
                analysis_summary, analysis_detail, truncated, original_length, analyzed_length = (
                    self.analyzer.analyze_diff(str(repo.name), str(repo.branch), diff, commit_messages)
                )
                current_commit = repo_obj.get_current_commit()
                repo_obj.update(current_commit)
            else:
                self.logger.warning("Diff is empty, skipping commit analysis")

        if not current_commit:
            current_commit = repo_obj.get_current_commit()

        self.logger.info(f"Repository {repo.name} check completed")

        return RepositoryReport(
            repo_name=str(repo.name),
            repo_slug=repo_obj.slug,
            repo_web_url=repo_obj.link,
            branch=str(repo.branch),
            commit_count=commit_count,
            current_commit=current_commit or "",
            previous_commit=previous_commit,
            commit_messages=commit_messages,
            analysis_summary=analysis_summary,
            analysis_detail=analysis_detail,
            truncated=truncated,
            original_diff_length=original_length,
            analyzed_diff_length=analyzed_length,
            release_data=release_data,
            release_summary=release_summary,
            release_detail=release_detail,
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
