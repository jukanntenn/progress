"""Repository wrapper class for high-level repository operations."""

import logging
import os
import shutil
from pathlib import Path
from typing import Dict, Optional

from ...config import Config
from ...consts import CMD_GH, GH_MAX_RETRIES
from ...db import UTC
from ...db.models import Repository
from ...enums import Protocol
from ...errors import GitException
from ...github import (
    GitClient,
    parse_protocol_from_url,
    resolve_repo_url,
    sanitize_repo_name,
)
from ...github_client import GitHubClient
from ...utils import get_now, retry, run_command, sanitize

logger = logging.getLogger(__name__)


class Repo:
    """Repository wrapper encapsulating model and git operations.

    This class represents a local repository and encapsulates all repository-related
    operations including cloning, updating, querying, and database updates.

    Design principles:
    - Completely replaces direct GitHubClient calls
    - Migrates necessary GitHubClient logic internally
    - Uses GitClient for low-level git operations
    """

    def __init__(
        self,
        model: Repository,
        git: GitClient,
        config: Config,
        gh_token: str | None = None,
        proxy: str | None = None,
        protocol: Protocol | str = Protocol.HTTPS,
        github_client: GitHubClient | None = None,
    ):
        """Initialize Repo instance.

        Args:
            model: Repository ORM model instance
            git: Git client for low-level git operations
            config: Global configuration object
            gh_token: GitHub token for cloning (optional)
            proxy: Proxy configuration for cloning (optional)
            protocol: Protocol to use for cloning (default: HTTPS)
            github_client: GitHub API client (optional, created if not provided)
        """
        self.model = model
        self.git = git
        self.config = config
        self.gh_token = gh_token
        self.proxy = proxy

        if isinstance(protocol, str):
            protocol = Protocol(protocol)
        self.protocol = protocol

        self.ssh_available = shutil.which("ssh") is not None
        if self.protocol == Protocol.SSH and not self.ssh_available:
            logger.warning(
                "SSH protocol configured but SSH client not available, "
                "falling back to HTTPS"
            )

        if github_client is None:
            self.github_client = GitHubClient(token=gh_token, proxy=proxy)
        else:
            self.github_client = github_client

    @property
    def slug(self) -> str:
        """Get repository slug (owner/repo)."""
        from ...consts import parse_repo_name

        return parse_repo_name(self.model.url)

    @property
    def link(self) -> str:
        """Get full GitHub web URL."""
        return f"https://github.com/{self.slug}"

    @property
    def is_new(self) -> bool:
        """Check if repository is being analyzed for the first time."""
        return not self.model.last_commit_hash

    @property
    def repo_path(self) -> Path:
        """Get local repository path."""
        repo_name = sanitize_repo_name(self.slug)
        return self.git.workspace_dir / repo_name

    def _get_effective_protocol(self, url: str) -> Protocol:
        """Get effective protocol considering URL format and SSH availability.

        Args:
            url: Repository URL

        Returns:
            Effective protocol to use
        """
        url_protocol = parse_protocol_from_url(url)

        if url_protocol:
            return url_protocol

        protocol = self.protocol

        if protocol == Protocol.SSH and not self.ssh_available:
            logger.warning(
                f"Repository {url} configured with SSH but SSH client unavailable, "
                "falling back to HTTPS"
            )
            return Protocol.HTTPS

        return protocol

    def clone_or_update(self) -> Path:
        """Clone repository for first time or pull updates.

        This method completely replaces GitHubClient.clone_or_update() by migrating
        the cloning logic into Repo, including protocol handling.

        Returns:
            Local repository path

        Raises:
            GitException: If clone/update fails
        """
        if self.is_new:
            effective_protocol = self._get_effective_protocol(self.model.url)
            full_url, short_url = resolve_repo_url(self.model.url, effective_protocol)
            logger.info(f"Using URL: {full_url} (protocol: {effective_protocol})")
            self._run_gh_clone_command(full_url, self.model.branch)
        else:
            self.git.fetch_and_reset(self.repo_path, self.model.branch)

        return self.repo_path

    def get_current_commit(self) -> str:
        """Get current HEAD commit hash.

        Returns:
            Current commit hash
        """
        return self.git.get_current_commit(self.repo_path)

    def get_diff(self) -> tuple[str, str, int, list[str], bool] | None:
        """Get diff data for AI analysis.

        Returns:
            (diff_content, previous_commit, commit_count, commit_messages, is_range_check)
            Returns None if no new commits

        Raises:
            GitException: If git operations fail
        """
        self.clone_or_update()
        current_commit = self.get_current_commit()

        if self.model.last_commit_hash == current_commit:
            return None

        previous_commit = self.model.last_commit_hash

        if not previous_commit:
            return self._get_first_check_diff(current_commit)
        else:
            return self._get_incremental_diff(current_commit, previous_commit)

    def _get_first_check_diff(
        self, current_commit: str
    ) -> tuple[str, str, int, list[str], bool]:
        """Get diff for first-time repository check.

        Args:
            current_commit: Current HEAD commit

        Returns:
            (diff, previous_commit, commit_count, commit_messages, is_range_check)
        """
        lookback_commits = self.config.analysis.first_run_lookback_commits
        total_commits = self.git.get_total_commit_count(self.repo_path)

        if total_commits <= 1:
            return None

        effective_lookback = min(lookback_commits, total_commits)

        if total_commits > effective_lookback:
            return self._get_range_diff(current_commit, effective_lookback)
        else:
            return self._get_recent_diff(current_commit, effective_lookback)

    def _get_range_diff(
        self, current_commit: str, lookback: int
    ) -> tuple[str, str, int, list[str], bool]:
        """Get diff using old..new range when history is sufficient.

        Args:
            current_commit: Current HEAD commit
            lookback: Number of commits to look back

        Returns:
            (diff, previous_commit, commit_count, commit_messages, is_range_check=True)
        """
        previous_commit = self.git.get_nth_commit_from_head(self.repo_path, lookback)

        if not previous_commit:
            previous_commit = self.git.get_previous_commit(self.repo_path)

        if not previous_commit:
            return None

        commit_messages = self.git.get_commit_messages(
            self.repo_path, previous_commit, current_commit
        )
        commit_count = self.git.get_commit_count(
            self.repo_path, previous_commit, current_commit
        )
        diff = self.git.get_commit_diff(self.repo_path, previous_commit, current_commit)

        return diff, previous_commit, commit_count, commit_messages, True

    def _get_recent_diff(
        self, current_commit: str, max_count: int
    ) -> tuple[str, str, int, list[str], bool]:
        """Get diff using recent commits when history is insufficient.

        Args:
            current_commit: Current HEAD commit
            max_count: Maximum number of commits to analyze

        Returns:
            (diff, previous_commit, commit_count, commit_messages, is_range_check=False)
        """
        recent_hashes = self.git.get_recent_commit_hashes(self.repo_path, max_count)
        previous_commit = recent_hashes[-1] if recent_hashes else None

        if not previous_commit:
            return None

        commit_messages = self.git.get_recent_commit_messages(self.repo_path, max_count)
        commit_count = len(recent_hashes)
        diff = self.git.get_recent_commit_patches(self.repo_path, max_count)

        return diff, previous_commit, commit_count, commit_messages, False

    def _get_incremental_diff(
        self, current_commit: str, previous_commit: str
    ) -> tuple[str, str, int, list[str], bool]:
        """Get diff for incremental check (existing repository).

        Args:
            current_commit: Current HEAD commit
            previous_commit: Last analyzed commit

        Returns:
            (diff, previous_commit, commit_count, commit_messages, is_range_check=True)
        """
        commit_messages = self.git.get_commit_messages(
            self.repo_path, previous_commit, current_commit
        )
        commit_count = self.git.get_commit_count(
            self.repo_path, previous_commit, current_commit
        )
        diff = self.git.get_commit_diff(self.repo_path, previous_commit, current_commit)

        return diff, previous_commit, commit_count, commit_messages, True

    def update(self, current_commit: str) -> None:
        """Update repository model state after analysis.

        Args:
            current_commit: Current HEAD commit hash
        """
        from ...db import database

        with database.atomic():
            self.model.last_commit_hash = current_commit
            self.model.last_check_time = get_now(UTC)
            self.model.save()

    def update_releases(self, release_tag: str, commit_hash: str) -> None:
        """Update repository release tracking state after analysis.

        Args:
            release_tag: Release tag name (e.g., "v5.0.0")
            commit_hash: Commit hash the release tag points to
        """
        from ...db import database

        with database.atomic():
            self.model.last_release_tag = release_tag
            self.model.last_release_commit_hash = commit_hash
            self.model.last_release_check_time = get_now(UTC)
            self.model.save()

    def check_releases(self) -> Optional[dict]:
        """Check for new GitHub releases.

        Returns:
            Dict with list of release data, or None if no new releases:
            - releases: list of dicts with tag_name, title, notes, published_at, commit_hash
        """
        try:
            owner, repo_name = self.slug.split("/")
            releases = self.github_client.list_releases(owner, repo_name)
        except GitException as e:
            logger.warning(f"Failed to check releases for {self.slug}: {e}")
            return None

        if not releases:
            logger.debug(f"No releases found for {self.slug}")
            return None

        new_releases = []
        last_check_time = self.model.last_release_check_time

        from datetime import datetime

        for r in releases:
            published_at_str = r.get("publishedAt")
            if published_at_str:
                try:
                    published_at = datetime.fromisoformat(
                        published_at_str.replace("Z", "+00:00")
                    )
                    if last_check_time is None or published_at > last_check_time:
                        try:
                            commit_hash = self.github_client.get_release_commit(
                                owner, repo_name, r["tagName"]
                            )
                        except GitException as e:
                            logger.warning(
                                f"Failed to get commit hash for {r['tagName']}: {e}"
                            )
                            commit_hash = None

                        try:
                            notes = self.github_client.get_release_body(
                                owner, repo_name, r["tagName"]
                            )
                        except GitException as e:
                            logger.warning(
                                f"Failed to get release notes for {r['tagName']}: {e}"
                            )
                            notes = ""

                        new_releases.append(
                            {
                                "tag_name": r["tagName"],
                                "title": r["name"],
                                "notes": notes,
                                "published_at": r["publishedAt"],
                                "commit_hash": commit_hash,
                            }
                        )
                except (ValueError, TypeError):
                    logger.debug(f"Could not parse publishedAt: {published_at_str}")
                    continue

        if not new_releases:
            return None

        return {"releases": new_releases}

    def get_commit_messages(
        self, old_commit: Optional[str], new_commit: str
    ) -> list[str]:
        """Get commit messages between two commits.

        Args:
            old_commit: Old commit hash (None for single commit)
            new_commit: New commit hash

        Returns:
            List of commit messages
        """
        return self.git.get_commit_messages(self.repo_path, old_commit, new_commit)

    @retry(
        times=GH_MAX_RETRIES,
        initial_delay=3,
        backoff="exponential",
        exceptions=(GitException,),
    )
    def _run_gh_clone_command(self, url: str, branch: str) -> None:
        """Clone repository using gh repo clone.

        This method is migrated from GitHubClient._run_gh_clone_command().

        Args:
            url: Repository URL
            branch: Branch name

        Raises:
            GitException: If clone fails
        """
        repo_path = self.repo_path

        if repo_path.exists():
            logger.debug(f"Removing existing repository path: {repo_path}")
            shutil.rmtree(repo_path)

        cmd = [
            CMD_GH,
            "repo",
            "clone",
            url,
            str(repo_path),
            "--",
            "--branch",
            branch,
            "--single-branch",
            "--tags",
        ]

        self._run_command(cmd)

    def _prepare_env(self, cmd: list[str]) -> Optional[Dict[str, str]]:
        """Prepare environment variables for gh command.

        Args:
            cmd: Command list to check

        Returns:
            Environment dict with GH_TOKEN and proxy for gh commands, None otherwise
        """
        if cmd[0] != CMD_GH:
            return None

        env = os.environ.copy()
        if self.gh_token:
            env["GH_TOKEN"] = self.gh_token
            logger.debug(f"Using GH_TOKEN: {sanitize(self.gh_token)}")
        if self.proxy:
            env["HTTP_PROXY"] = self.proxy
            env["HTTPS_PROXY"] = self.proxy
            logger.debug(f"Using proxy: {sanitize(self.proxy)}")

        return env

    def _run_command(self, cmd: list[str]) -> str:
        """Run command and return output.

        This method is migrated from GitHubClient._run_command().

        Args:
            cmd: Command list

        Returns:
            Command output

        Raises:
            GitException: If command fails
        """
        env = self._prepare_env(cmd)
        return run_command(
            cmd,
            timeout=self.config.github.gh_timeout,
            env=env,
        )
