"""GitHub CLI interactions"""

import logging
import re
import git
from pathlib import Path
from typing import List, Optional, Tuple

from .consts import (
    CMD_GIT,
    GIT_MAX_RETRIES,
    GIT_SUFFIX,
    GITHUB_HTTPS_PREFIX,
    GITHUB_SSH_PREFIX,
    TIMEOUT_GIT_COMMAND,
    WORKSPACE_DIR_DEFAULT,
)
from .enums import Protocol
from .errors import GitException
from .utils import retry, run_command, strip_git_suffix

logger = logging.getLogger(__name__)


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
            return parts[0], strip_git_suffix(parts[1])

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
        repo = git.Repo(str(repo_path))
        return repo.head.commit.hexsha

    def get_previous_commit(self, repo_path: Path) -> Optional[str]:
        """Get second latest commit hash (HEAD^1).

        Returns:
            Second latest commit hash, or None if it doesn't exist
        """
        repo = git.Repo(str(repo_path))
        try:
            return repo.head.commit.parents[0].hexsha
        except (IndexError, AttributeError):
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
        repo = git.Repo(str(repo_path))
        if old_commit is None:
            old = repo.head.commit.parents[0] if repo.head.commit.parents else None
            new = repo.head.commit
        else:
            old = repo.commit(old_commit)
            new = repo.commit(new_commit)

        if old is None:
            diff = new.diff(create_patch=True, paths=None)
        else:
            diff = old.diff(new, create_patch=True, paths=None)

        return "\n".join(
            d.diff.decode("utf-8", errors="replace") if isinstance(d.diff, bytes) else str(d.diff)
            for d in diff
        )

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
        repo = git.Repo(str(repo_path))
        if old_commit:
            old = repo.commit(old_commit)
            new = repo.commit(new_commit)
            commits = list(repo.iter_commits(f"{old.hexsha}..{new.hexsha}"))
        else:
            commits = [repo.head.commit]
        messages = [c.message for c in commits]
        return messages

    def get_commit_count(
        self, repo_path: Path, old_commit: Optional[str], new_commit: str
    ) -> int:
        """Get commit count."""
        if not old_commit:
            return 1
        repo = git.Repo(str(repo_path))
        old = repo.commit(old_commit)
        new = repo.commit(new_commit)
        return sum(1 for _ in repo.iter_commits(f"{old.hexsha}..{new.hexsha}"))

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

        repo = git.Repo(str(repo_path))
        repo.remotes.origin.fetch()
        repo.head.reset(f"origin/{branch}", index=True, working_tree=True)

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
