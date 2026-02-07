"""GitHub CLI interactions"""

import logging
import os
import re
import shutil
import subprocess
import threading
import base64
from pathlib import Path
from typing import List, Optional, Tuple
import json

from .consts import (
    CMD_GH,
    CMD_GIT,
    GH_MAX_RETRIES,
    GIT_MAX_RETRIES,
    GIT_SUFFIX,
    GITHUB_HTTPS_PREFIX,
    GITHUB_SSH_PREFIX,
    TIMEOUT_GH_COMMAND,
    TIMEOUT_GIT_COMMAND,
    WORKSPACE_DIR_DEFAULT,
)
from .enums import Protocol
from .errors import GitException
from .utils import retry, run_command, sanitize

logger = logging.getLogger(__name__)


def _get_env_with_token(gh_token: Optional[str]) -> dict | None:
    """Create environment dict with GH_TOKEN if provided.

    Args:
        gh_token: GitHub token (optional)

    Returns:
        Environment dict with token set, or None
    """
    if not gh_token:
        return None

    env = os.environ.copy()
    env["GH_TOKEN"] = gh_token
    logger.debug(f"Using GH_TOKEN: {gh_token[:8]}...")
    return env


def parse_protocol_from_url(url: str) -> Protocol | None:
    """Parse protocol from repository URL.

    Args:
        url: Repository URL (https://..., git@..., or owner/repo)

    Returns:
        Protocol if detected, None for short format
    """
    if url.startswith("https://"):
        return Protocol.HTTPS
    if url.startswith("git@"):
        return Protocol.SSH
    return None


def normalize_repo_url(
    url: str,
    repo_protocol: Protocol | str | None = None,
    default_protocol: Protocol | str = Protocol.HTTPS,
) -> str:
    """Normalize repository URL to standard format.

    Args:
        url: Repository URL in various formats
        repo_protocol: Repository-level protocol (optional)
        default_protocol: Default protocol (from github config)

    Returns:
        Normalized URL (https://github.com/owner/repo.git or git@github.com:owner/repo.git)
    """
    if isinstance(repo_protocol, str):
        repo_protocol = Protocol(repo_protocol)
    if isinstance(default_protocol, str):
        default_protocol = Protocol(default_protocol)

    url_protocol = parse_protocol_from_url(url)

    if url_protocol:
        return url

    owner, repo_name = _parse_owner_repo(url)

    final_protocol = repo_protocol or default_protocol

    if final_protocol == Protocol.SSH:
        return f"{GITHUB_SSH_PREFIX}{owner}/{repo_name}{GIT_SUFFIX}"
    return f"{GITHUB_HTTPS_PREFIX}{owner}/{repo_name}{GIT_SUFFIX}"


def _parse_owner_repo(url: str) -> tuple[str, str]:
    """Parse owner and repo name from URL.

    Args:
        url: Repository URL in any format

    Returns:
        (owner, repo_name) tuple

    Raises:
        ValueError: If URL format is invalid
    """
    if url.startswith("https://"):
        match = re.match(r"https://github\.com/([^/]+)/([^/.]+)", url)
        if match:
            owner, repo = match.groups()
            return owner, repo
        raise ValueError(f"Invalid HTTPS URL: {url}")

    if url.startswith("git@"):
        match = re.match(r"git@github\.com:([^/]+)/([^/.]+)", url)
        if match:
            owner, repo = match.groups()
            return owner, repo
        raise ValueError(f"Invalid SSH URL: {url}")

    if "/" in url:
        parts = url.split("/")
        if len(parts) == 2:
            return parts[0], parts[1].rstrip(GIT_SUFFIX)

    raise ValueError(f"Invalid repository URL format: {url}")


def sanitize_repo_name(name: str) -> str:
    """Sanitize repository name to be safe for filesystem.

    Args:
        name: Original repository name (e.g., owner/repo or owner/repo.git)

    Returns:
        Safe directory name (e.g., owner_repo)

    Rules:
        - Only allow a-z A-Z 0-9 - _ characters
        - Replace other characters with underscore
        - Compress consecutive underscores into single
        - Strip leading/trailing underscores
    """
    if name.endswith(GIT_SUFFIX):
        name = name[:-4]

    name = name.replace("/", "_")

    sanitized = "".join(
        char if char.isalnum() or char in "-_" else "_" for char in name
    )

    result = re.sub(r"_+", "_", sanitized).strip("_")

    return result or "repo"


def resolve_repo_url(repo_url: str, protocol: str | Protocol) -> Tuple[str, str]:
    """Resolve repository URL, return (full_url, owner/repo).

    This is extracted from GitHubClient._resolve_repo_url() for migration.

    Args:
        repo_url: Repository URL in various formats:
            - Short: owner/repo
            - HTTPS: https://github.com/owner/repo.git
            - SSH: git@github.com:owner/repo.git
        protocol: Default protocol (https or ssh), only for short format

    Returns:
        (full_url, owner/repo)

    Raises:
        ValueError: If URL format is invalid
    """
    if isinstance(protocol, Protocol):
        protocol = protocol.value
    if repo_url.startswith("https://"):
        match = re.match(r"https://github\.com/([^/]+)/([^/.]+)", repo_url)
        if match:
            owner, repo = match.groups()
            short_url = f"{owner}/{repo}"
            logger.debug(f"Detected HTTPS URL: {repo_url} -> {short_url}")
            return repo_url, short_url
        raise ValueError(f"Invalid HTTPS URL: {repo_url}")

    if repo_url.startswith("git@"):
        match = re.match(r"git@github\.com:([^/]+)/([^/.]+)", repo_url)
        if match:
            owner, repo = match.groups()
            short_url = f"{owner}/{repo}"
            logger.debug(f"Detected SSH URL: {repo_url} -> {short_url}")
            return repo_url, short_url
        raise ValueError(f"Invalid SSH URL: {repo_url}")

    if "/" in repo_url:
        parts = repo_url.split("/")
        if len(parts) == 2:
            owner, repo_name = parts
            short_url = f"{owner}/{repo_name}"

            if protocol == "ssh":
                full_url = f"{GITHUB_SSH_PREFIX}{owner}/{repo_name}.git"
            else:
                full_url = f"{GITHUB_HTTPS_PREFIX}{owner}/{repo_name}.git"

            logger.debug(
                f"Short URL conversion: {repo_url} -> {full_url} (protocol: {protocol})"
            )
            return full_url, short_url

    raise ValueError(f"Invalid repository URL format: {repo_url}")


class GitClient:
    """Git client for pure Git operations."""

    def __init__(
        self,
        workspace_dir: str = WORKSPACE_DIR_DEFAULT,
        timeout: int = TIMEOUT_GIT_COMMAND,
    ):
        """Initialize Git client.

        Args:
            workspace_dir: Working directory path
            timeout: Command timeout in seconds
        """
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        logger.debug(f"Git workspace directory: {self.workspace_dir}")

    def get_current_commit(self, repo_path: Path) -> str:
        """Get current commit hash."""
        result = self._run_git_command(["rev-parse", "HEAD"], repo_path)
        return result.strip()

    def get_previous_commit(self, repo_path: Path) -> Optional[str]:
        """Get second latest commit hash (HEAD^1).

        Returns:
            Second latest commit hash, or None if it doesn't exist
        """
        try:
            result = self._run_git_command(["rev-parse", "HEAD^1"], repo_path)
            return result.strip() if result.strip() else None
        except RuntimeError:
            return None

    def get_commit_diff(
        self, repo_path: Path, old_commit: Optional[str], new_commit: str
    ) -> str:
        """Get diff between two commits.

        Args:
            repo_path: Repository path
            old_commit: Old commit hash (None means get diff of latest two commits)
            new_commit: New commit hash

        Returns:
            Diff content
        """
        commit_range = f"{old_commit}..{new_commit}" if old_commit else "HEAD^1..HEAD"
        return self._run_git_command(["diff", commit_range], repo_path)

    def get_changed_files(
        self, repo_path: Path, old_commit: Optional[str], new_commit: str
    ) -> list[str]:
        commit_range = f"{old_commit}..{new_commit}" if old_commit else "HEAD^1..HEAD"
        result = self._run_git_command(["diff", "--name-only", commit_range], repo_path)
        return [line.strip() for line in result.splitlines() if line.strip()]

    def get_changed_file_statuses(
        self, repo_path: Path, old_commit: Optional[str], new_commit: str
    ) -> list[tuple[str, str]]:
        commit_range = f"{old_commit}..{new_commit}" if old_commit else "HEAD^1..HEAD"
        result = self._run_git_command(["diff", "--name-status", commit_range], repo_path)
        items: list[tuple[str, str]] = []
        for line in result.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            items.append((parts[0].strip(), parts[1].strip()))
        return items

    def get_file_diff(
        self,
        repo_path: Path,
        old_commit: Optional[str],
        new_commit: str,
        file_path: str,
    ) -> str:
        commit_range = f"{old_commit}..{new_commit}" if old_commit else "HEAD^1..HEAD"
        return self._run_git_command(["diff", commit_range, "--", file_path], repo_path)

    def get_file_creation_date(self, repo_path: Path, file_path: str) -> Optional[str]:
        try:
            result = self._run_git_command(
                [
                    "log",
                    "--diff-filter=A",
                    "--format=%ai",
                    "-1",
                    "--",
                    file_path,
                ],
                repo_path,
            )
            return result.strip() if result.strip() else None
        except RuntimeError:
            return None

    def get_commit_messages(
        self, repo_path: Path, old_commit: Optional[str], new_commit: str
    ) -> List[str]:
        """Get list of commit messages (full messages including body)."""
        if old_commit:
            result = self._run_git_command(
                ["log", f"{old_commit}..{new_commit}", "--pretty=format:%B%n%x00"],
                repo_path,
            )
        else:
            result = self._run_git_command(
                ["log", "--pretty=format:%B%n%x00", "-1"], repo_path
            )

        if not result.strip():
            return []

        messages = [msg.strip() for msg in result.split("\x00") if msg.strip()]
        return messages

    def get_commit_count(
        self, repo_path: Path, old_commit: Optional[str], new_commit: str
    ) -> int:
        """Get commit count."""
        if not old_commit:
            return 1

        result = self._run_git_command(
            [
                "rev-list",
                "--count",
                f"{old_commit}..{new_commit}",
            ],
            repo_path,
        )
        return int(result.strip())

    def get_nth_commit_from_head(self, repo_path: Path, n: int) -> Optional[str]:
        """Get nth commit hash from HEAD (0-indexed).

        Args:
            repo_path: Repository path
            n: Nth commit (0=HEAD, 1=HEAD^1, 2=HEAD^2...)

        Returns:
            Commit hash, or None if it doesn't exist
        """
        try:
            result = self._run_git_command(["rev-parse", f"HEAD~{n}"], repo_path)
            return result.strip() if result.strip() else None
        except RuntimeError:
            return None

    def get_total_commit_count(self, repo_path: Path) -> int:
        """Get total commit count of current branch."""
        try:
            result = self._run_git_command(["rev-list", "--count", "HEAD"], repo_path)
            return int(result.strip())
        except RuntimeError:
            return 0

    def get_recent_commit_hashes(self, repo_path: Path, max_count: int) -> list[str]:
        """Get recent commit hashes (newest first)."""
        result = self._run_git_command(
            ["log", f"-{max_count}", "--format=%H"], repo_path
        )
        return [line.strip() for line in result.splitlines() if line.strip()]

    def get_recent_commit_messages(self, repo_path: Path, max_count: int) -> List[str]:
        """Get recent commit messages (full messages including body)."""
        result = self._run_git_command(
            ["log", f"-{max_count}", "--pretty=format:%B%n%x00"], repo_path
        )

        if not result.strip():
            return []

        messages = [msg.strip() for msg in result.split("\x00") if msg.strip()]
        return messages

    def get_recent_commit_patches(self, repo_path: Path, max_count: int) -> str:
        """Get concatenated patches for recent commits (newest first)."""
        return self._run_git_command(
            ["log", f"-{max_count}", "-p", "--no-color", "--pretty=format:"],
            repo_path,
        )

    def fetch_and_reset(self, repo_path: Path, branch: str) -> None:
        """Fetch remote updates and force reset to remote branch.

        Args:
            repo_path: Repository path
            branch: Branch name
        """
        self._cleanup_git_locks(repo_path)

        self._run_git_command(
            ["fetch", "origin"],
            repo_path,
        )

        self._run_git_command(
            ["reset", "--hard", f"origin/{branch}"],
            repo_path,
        )

    def _cleanup_git_locks(self, repo_path: Path):
        """Clean up git lock files.

        Args:
            repo_path: Repository path
        """
        git_dir = repo_path / ".git"
        if not git_dir.exists():
            return

        lock_files = list(git_dir.rglob("*.lock"))
        if lock_files:
            logger.debug(f"Cleaning up {len(lock_files)} git lock files")
            for lock_file in lock_files:
                try:
                    lock_file.unlink()
                    logger.debug(f"Deleted lock file: {lock_file}")
                except Exception as e:
                    logger.debug(f"Failed to delete lock file {lock_file}: {e}")

    def _handle_git_retry(
        self, args: tuple, kwargs: dict, error: Exception, attempt: int
    ):
        repo_path = kwargs.get("repo_path") or args[1]
        error_msg = str(error)
        is_lock_error = "lock" in error_msg.lower() and "File exists" in error_msg

        if is_lock_error:
            logger.warning("Git lock file conflict detected, cleaning up...")
            self._cleanup_git_locks(repo_path)

    @retry(
        times=GIT_MAX_RETRIES,
        initial_delay=2,
        backoff="exponential",
        exceptions=(GitException,),
        on_retry=lambda args, kwargs, error, attempt: args[0]._handle_git_retry(
            args, kwargs, error, attempt
        ),
    )
    def _run_git_command(self, args: List[str], repo_path: Path) -> str:
        """Run Git command and return output.

        Args:
            args: Git command arguments (without 'git' and '-C')
            repo_path: Repository path

        Returns:
            Command output
        """
        cmd = [CMD_GIT, "-C", str(repo_path)] + args
        return run_command(cmd, timeout=self.timeout)


def gh_release_list(
    repo_slug: str,
    exclude_drafts: bool = True,
    exclude_pre_releases: bool = True,
    limit: int = 100,
    gh_token: Optional[str] = None,
) -> List[dict]:
    """List GitHub releases for a repository.

    Security: All parameters are safely passed as list arguments to subprocess,
    preventing command injection. Release data from GitHub is treated as
    read-only and not executed or interpolated into commands.

    Args:
        repo_slug: Repository slug in format "owner/repo"
        exclude_drafts: Whether to exclude draft releases
        exclude_pre_releases: Whether to exclude pre-releases
        limit: Maximum number of releases to fetch
        gh_token: GitHub token for authentication (optional)

    Returns:
        List of release dicts with keys: tagName, name, body, publishedAt, targetCommitish

    Raises:
        GitException: If gh command fails
    """
    cmd = [
        CMD_GH,
        "release",
        "list",
        "--repo",
        repo_slug,
        "--limit",
        str(limit),
        "--json",
        "tagName,name,publishedAt",
    ]

    if exclude_drafts:
        cmd.append("--exclude-drafts")
    if exclude_pre_releases:
        cmd.append("--exclude-pre-releases")

    env = _get_env_with_token(gh_token)

    try:
        output = run_command(cmd, timeout=TIMEOUT_GH_COMMAND, env=env)
        releases = json.loads(output) if output.strip() else []
        logger.debug(f"Found {len(releases)} releases for {repo_slug}")
        return releases
    except RuntimeError as e:
        error_str = str(e).lower()
        if "no releases found" in error_str:
            logger.debug(f"No releases found for {repo_slug}")
            return []
        if "rate limit" in error_str or "api rate limit" in error_str:
            logger.warning(f"GitHub API rate limit reached while checking {repo_slug}")
            raise GitException(f"GitHub API rate limit exceeded: {e}")
        if "repository not found" in error_str:
            logger.debug(f"Repository {repo_slug} not found")
            return []
        if "access denied" in error_str or "forbidden" in error_str:
            logger.warning(f"Repository {repo_slug} access denied")
            raise GitException(f"Repository {repo_slug} access denied: {e}")
        raise GitException(f"Failed to list releases for {repo_slug}: {e}")


def gh_release_get_commit(repo_slug: str, tag_name: str, gh_token: Optional[str] = None) -> str:
    """Get the commit hash that a release tag points to.

    Args:
        repo_slug: Repository slug in format "owner/repo"
        tag_name: Release tag name (e.g., "v5.0.0")
        gh_token: GitHub token for authentication (optional)

    Returns:
        Commit hash string

    Raises:
        GitException: If gh command fails or release not found
    """
    cmd = [
        CMD_GH,
        "release",
        "view",
        tag_name,
        "--repo",
        repo_slug,
        "--json",
        "targetCommitish",
        "--jq",
        ".targetCommitish",
    ]

    env = _get_env_with_token(gh_token)

    try:
        output = run_command(cmd, timeout=TIMEOUT_GH_COMMAND, env=env)
        commit_hash = output.strip()
        if not commit_hash:
            raise GitException(f"No commit hash found for release {tag_name}")
        logger.debug(f"Release {tag_name} points to commit {commit_hash}")
        return commit_hash
    except RuntimeError as e:
        error_str = str(e).lower()
        if "rate limit" in error_str or "api rate limit" in error_str:
            logger.warning(f"GitHub API rate limit reached while getting {tag_name}")
            raise GitException(f"GitHub API rate limit exceeded: {e}")
        if "not found" in error_str or "access denied" in error_str or "forbidden" in error_str:
            logger.warning(f"Release {tag_name} not found or access denied")
            raise GitException(f"Release {tag_name} not found or access denied: {e}")
        raise GitException(f"Failed to get commit hash for release {tag_name}: {e}")


def gh_release_get_body(repo_slug: str, tag_name: str, gh_token: Optional[str] = None) -> str:
    """Get the release notes/body for a release.

    Args:
        repo_slug: Repository slug in format "owner/repo"
        tag_name: Release tag name (e.g., "v5.0.0")
        gh_token: GitHub token for authentication (optional)

    Returns:
        Release notes/body string

    Raises:
        GitException: If gh command fails or release not found
    """
    cmd = [
        CMD_GH,
        "release",
        "view",
        tag_name,
        "--repo",
        repo_slug,
        "--json",
        "body",
        "--jq",
        ".body",
    ]

    env = _get_env_with_token(gh_token)

    try:
        output = run_command(cmd, timeout=TIMEOUT_GH_COMMAND, env=env)
        body = output.strip()
        logger.debug(f"Fetched release notes for {tag_name}")
        return body
    except RuntimeError as e:
        error_str = str(e).lower()
        if "rate limit" in error_str or "api rate limit" in error_str:
            logger.warning(f"GitHub API rate limit reached while getting {tag_name}")
            raise GitException(f"GitHub API rate limit exceeded: {e}")
        if "not found" in error_str or "access denied" in error_str or "forbidden" in error_str:
            logger.warning(f"Release {tag_name} not found or access denied")
            raise GitException(f"Release {tag_name} not found or access denied: {e}")
        raise GitException(f"Failed to get release notes for {tag_name}: {e}")


def gh_repo_list(
    owner: str,
    limit: int = 100,
    source: bool = True,
    gh_token: Optional[str] = None,
) -> List[dict]:
    cmd = [
        CMD_GH,
        "repo",
        "list",
        owner,
        "--limit",
        str(limit),
        "--json",
        "nameWithOwner,description,createdAt,updatedAt",
    ]
    if source:
        cmd.append("--source")

    env = _get_env_with_token(gh_token)

    try:
        output = run_command(cmd, timeout=TIMEOUT_GH_COMMAND, env=env)
        return json.loads(output) if output.strip() else []
    except Exception as e:
        from .errors import CommandException

        error_str = str(e).lower()
        if isinstance(e, CommandException):
            if "could not resolve" in error_str or "not found" in error_str:
                logger.warning(f"Owner {owner} not found")
                return []
            if "rate limit" in error_str or "api rate limit" in error_str:
                logger.warning(f"GitHub API rate limit reached while listing repos for {owner}")
                raise GitException(f"GitHub API rate limit exceeded: {e}") from e
            raise GitException(f"Failed to list repositories for {owner}: {e}") from e
        raise


def gh_api_get_readme(
    owner: str,
    repo: str,
    gh_token: Optional[str] = None,
) -> str | None:
    cmd = [CMD_GH, "api", f"repos/{owner}/{repo}/readme"]

    env = _get_env_with_token(gh_token)

    try:
        output = run_command(cmd, timeout=TIMEOUT_GH_COMMAND, env=env)
        data = json.loads(output) if output.strip() else {}
        content_b64 = data.get("content")
        if not content_b64:
            return None
        try:
            return base64.b64decode(content_b64).decode("utf-8", errors="replace")
        except Exception as decode_error:
            raise GitException(f"Failed to decode README content: {decode_error}") from decode_error
    except Exception as e:
        from .errors import CommandException

        error_str = str(e).lower()
        if isinstance(e, CommandException):
            if "404" in error_str or "not found" in error_str:
                return None
            raise GitException(f"Failed to fetch README for {owner}/{repo}: {e}") from e
        raise
