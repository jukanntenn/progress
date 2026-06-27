"""Repository manager - unified management of all repository operations."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from progress.ai import Analyzer
from progress.config import Config
from progress.consts import WORKSPACE_DIR_DEFAULT
from progress.db.models import Repository
from progress.enums import Protocol
from progress.github import GitClient, normalize_repo_url
from progress.github_client import GitHubClient
from progress.i18n import gettext as _

from .analysis import analyze_diff, analyze_releases
from .repo import Repo
from .reporter import MarkdownReporter

logger = logging.getLogger(__name__)


def _get_database():
    """Get database instance (lazy import)."""
    from ... import db

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


def replace_repositories(
    repos_config: list, default_protocol: "Protocol | str"
) -> SyncResult:
    """Persist the desired repos to the table, upserting and pruning the rest.

    This performs no GitHub verification — it simply makes the ``repositories``
    table match the desired set. Used by the config UI and ``config import``; the
    tracking check verifies repos lazily and skips ones that no longer exist.
    """
    from ...consts import parse_repo_name

    database = _get_database()
    configured_urls = set()
    created_count = 0
    updated_count = 0

    with database.atomic():
        for repo_config in repos_config:
            normalized_url = normalize_repo_url(
                repo_config.url, repo_config.protocol, default_protocol
            )
            name = parse_repo_name(repo_config.url)
            configured_urls.add(normalized_url)

            repo, created = Repository.get_or_create(
                url=normalized_url,
                defaults={
                    "name": name,
                    "branch": repo_config.branch,
                    "enabled": repo_config.enabled,
                },
            )
            if not created:
                repo.name = name
                repo.branch = repo_config.branch
                repo.enabled = repo_config.enabled
                repo.url = normalized_url
                repo.save()
                updated_count += 1
            else:
                created_count += 1

        deleted_count = (
            Repository.delete().where(Repository.url.not_in(configured_urls)).execute()
        )

    return SyncResult(
        created=created_count, updated=updated_count, deleted=deleted_count
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
    releases: list | None = None

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
        analyzer: Analyzer,
        reporter: MarkdownReporter,
        config: Config,
    ):
        self.analyzer = analyzer
        self.reporter = reporter
        self.config = config
        self.language = config.analysis.language
        self.max_diff_length = config.analysis.max_diff_length
        self.logger = logger

        workspace_dir = config.workspace_dir or WORKSPACE_DIR_DEFAULT

        self.git = GitClient(
            workspace_dir=workspace_dir, timeout=config.github.git_timeout
        )

        self.gh_token = config.github.gh_token
        self.proxy = config.github.proxy
        self.protocol = config.github.protocol

        self.github_client = GitHubClient(token=self.gh_token, proxy=self.proxy)

    def list_enabled(self) -> list[Repository]:
        """Get all enabled repositories.

        Returns:
            List of enabled repositories
        """
        database = _get_database()
        with database.connection_context():
            return list(Repository.select().where(Repository.enabled))

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

    def _analyze_all_releases(
        self,
        repo_name: str,
        branch: str,
        release_data: dict,
        repo_obj=None,
        previous_release_commit: str | None = None,
    ) -> list:
        """Analyze all releases individually.

        Args:
            repo_name: Repository name
            branch: Branch name
            release_data: Dict with releases list and is_first_check flag
            repo_obj: Repo instance for diff computation
            previous_release_commit: Previous release commit hash for diff

        Returns:
            List of release dicts with added ai_summary and ai_detail fields
        """
        from datetime import datetime

        releases = release_data["releases"]
        is_first_check = release_data.get("is_first_check", False)

        def parse_published_at(value: str | None) -> datetime:
            if not value:
                return datetime.min
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return datetime.min

        releases.sort(
            key=lambda r: parse_published_at(r.get("published_at")),
            reverse=True,
        )

        analyzed_releases = []

        for i, release in enumerate(releases):
            diff_content = None
            if not is_first_check and repo_obj and previous_release_commit:
                diff_content = self._get_release_diff(
                    repo_obj,
                    previous_release_commit,
                    release.get("commit_hash"),
                )
            single_release_data = {
                "is_first_check": is_first_check,
                "latest_release": {
                    "tag": release["tag_name"],
                    "name": release["title"],
                    "notes": release["notes"],
                    "published_at": release["published_at"],
                    "commit_hash": release.get("commit_hash"),
                },
                "intermediate_releases": releases[i + 1 :]
                if i < len(releases) - 1
                else [],
                "diff_content": diff_content,
            }

            try:
                summary, detail = analyze_releases(
                    self.analyzer,
                    repo_name,
                    branch,
                    single_release_data,
                    self.language,
                )
            except Exception as e:
                self.logger.warning(
                    f"Failed to analyze release {release['tag_name']}: {e}"
                )
                summary = _("**AI analysis unavailable for {tag_name}**").format(
                    tag_name=release["tag_name"]
                )
                detail = _(
                    "**Release Information:**\n\n"
                    "- **Tag:** {tag_name}\n"
                    "- **Name:** {name}\n"
                    "- **Published:** {published}\n\n"
                    "{notes}"
                ).format(
                    tag_name=release["tag_name"],
                    name=release.get("title", release["tag_name"]),
                    published=release.get("published_at", "unknown"),
                    notes=release.get("notes", ""),
                )

            analyzed_releases.append(
                {
                    **release,
                    "ai_summary": summary,
                    "ai_detail": detail,
                }
            )

        return analyzed_releases

    def _get_release_diff(
        self,
        repo_obj,
        previous_commit: str | None,
        current_commit: str | None,
    ) -> str | None:
        if not previous_commit or not current_commit:
            return None
        try:
            return repo_obj.git.get_commit_diff(
                repo_obj.repo_path, previous_commit, current_commit
            )
        except Exception as e:
            self.logger.warning(f"Failed to get release diff: {e}")
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
        releases_list = None
        try:
            release_data = repo_obj.check_releases()
        except Exception as e:
            self.logger.warning(
                f"Failed to check releases for {repo.name}: {e}",
                exc_info=True,
            )
            release_data = None
        if release_data:
            try:
                is_first_check = release_data.get("is_first_check", False)
                releases = release_data["releases"]
                self.logger.info(f"Found {len(releases)} release(s), analyzing...")
                previous_release_commit = None
                if not is_first_check and repo.last_release_commit_hash:
                    previous_release_commit = repo.last_release_commit_hash
                releases_list = self._analyze_all_releases(
                    str(repo.name),
                    str(repo.branch),
                    release_data,
                    repo_obj,
                    previous_release_commit,
                )

                latest = releases_list[0] if releases_list else None
                commit_hash = latest.get("commit_hash") if latest else None
                if commit_hash:
                    repo_obj.update_releases(latest["tag_name"], commit_hash)
            except Exception as e:
                self.logger.error(f"Failed to analyze releases: {e}")
                self.logger.info("Continuing with commit analysis...")

        # Get diff data, returns None if no new commits
        diff_data = repo_obj.get_diff()
        if diff_data is None and not releases_list:
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
                (
                    analysis_summary,
                    analysis_detail,
                    truncated,
                    original_length,
                    analyzed_length,
                ) = analyze_diff(
                    self.analyzer,
                    str(repo.name),
                    str(repo.branch),
                    diff,
                    commit_messages,
                    self.max_diff_length,
                    self.language,
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
            releases=releases_list,
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
