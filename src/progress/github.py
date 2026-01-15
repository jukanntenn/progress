"""GitHub CLI interactions"""

import logging
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import List, Optional, Tuple

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
from .utils import retry, sanitize

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
            return match.groups()
        raise ValueError(f"Invalid HTTPS URL: {url}")

    if url.startswith("git@"):
        match = re.match(r"git@github\.com:([^/]+)/([^/.]+)", url)
        if match:
            return match.groups()
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
        logger.debug(f"Executing command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {e.stderr}")
            raise GitException(f"Git command failed: {e.stderr}") from e
        except subprocess.TimeoutExpired:
            logger.error("Command timeout")
            raise GitException("Git command timeout") from None


class GitHubClient:
    """GitHub client for GitHub interactions and proxy configuration."""

    _git_lock = threading.Lock()

    def __init__(
        self,
        workspace_dir: str = WORKSPACE_DIR_DEFAULT,
        gh_token: Optional[str] = None,
        protocol: str | Protocol = "https",
        proxy: Optional[str] = None,
        git_timeout: int = TIMEOUT_GIT_COMMAND,
        gh_timeout: int = TIMEOUT_GH_COMMAND,
    ):
        """Initialize GitHub client.

        Args:
            workspace_dir: Working directory path
            gh_token: GitHub personal access token
            protocol: Default protocol (https or ssh)
            proxy: Proxy URL
            git_timeout: Git command timeout in seconds
            gh_timeout: GitHub CLI command timeout in seconds
        """
        if isinstance(protocol, str):
            protocol = Protocol(protocol)

        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        self.git = GitClient(workspace_dir, timeout=git_timeout)

        self.gh_token = gh_token
        self.protocol = protocol
        self.proxy = proxy
        self.git_timeout = git_timeout
        self.gh_timeout = gh_timeout

        logger.debug(f"GitHub workspace directory: {self.workspace_dir}")
        logger.debug(f"Protocol: {self.protocol}")
        logger.debug(
            f"Proxy: {sanitize(self.proxy) if self.proxy else 'Not configured'}"
        )

        self.ssh_available = shutil.which("ssh") is not None
        if self.protocol == Protocol.SSH and not self.ssh_available:
            logger.warning(
                "SSH protocol configured but SSH client not available, falling back to HTTPS"
            )
        logger.debug(f"SSH available: {self.ssh_available}")

    @staticmethod
    def _resolve_repo_url(repo_url: str, protocol: str | Protocol) -> Tuple[str, str]:
        """Resolve repository URL, return (full_url, owner/repo).

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

    def clone_or_update(
        self, repo_url: str, branch: str, is_first_time: bool = False
    ) -> Path:
        """Clone or update repository.

        Args:
            repo_url: Repository URL in various formats:
                - Short: owner/repo
                - HTTPS: https://github.com/owner/repo.git
                - SSH: git@github.com:owner/repo.git
            branch: Branch name
            is_first_time: True if first time cloning (last_commit_hash is empty)

        Returns:
            Repository path
        """
        url_protocol = parse_protocol_from_url(repo_url)
        protocol = url_protocol or self.protocol

        if protocol == Protocol.SSH and not self.ssh_available:
            logger.warning(
                f"Repository {repo_url} configured with SSH but SSH client unavailable, "
                "falling back to HTTPS"
            )
            protocol = Protocol.HTTPS

        full_url, short_url = self._resolve_repo_url(repo_url, protocol)
        logger.info(f"Using URL: {full_url} (protocol: {protocol})")

        repo_name = sanitize_repo_name(short_url)
        repo_path = self.workspace_dir / repo_name

        if is_first_time:
            logger.info(f"Cloning repository: {short_url} (branch: {branch})")
            self._run_gh_clone_command(full_url, repo_path, branch)
        else:
            logger.info(f"Syncing repository: {short_url} (branch: {branch})")
            self.git.fetch_and_reset(repo_path, branch)

        return repo_path

    @retry(
        times=GH_MAX_RETRIES,
        initial_delay=1,
        backoff="exponential",
        exceptions=(GitException,),
    )
    def _run_gh_clone_command(self, url: str, repo_path: Path, branch: str) -> None:
        """Clone repository using gh repo clone.

        Args:
            url: Full repository URL (supports SSH and HTTPS)
            repo_path: Local path
            branch: Branch name
        """
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
        ]

        self._run_command(cmd)

    def _run_command(self, cmd: List[str]) -> str:
        """Run command and return output.

        Args:
            cmd: Command list

        Returns:
            Command output
        """
        logger.debug(f"Executing command: {' '.join(cmd)}")

        env = None
        if cmd[0] == CMD_GH:
            env = os.environ.copy()
            if self.gh_token:
                env["GH_TOKEN"] = self.gh_token
                logger.debug(f"Using GH_TOKEN: {sanitize(self.gh_token)}")
            if self.proxy:
                env["HTTP_PROXY"] = self.proxy
                env["HTTPS_PROXY"] = self.proxy
                logger.debug(f"Using proxy: {sanitize(self.proxy)}")

        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.gh_timeout,
                env=env,
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {e.stderr}")
            raise GitException(f"Command failed: {e.stderr}") from e
        except subprocess.TimeoutExpired:
            logger.error("Command timeout")
            raise GitException("Command timeout") from None

    def get_current_commit(self, repo_path: Path) -> str:
        """Get current commit hash (proxy to GitClient)."""
        return self.git.get_current_commit(repo_path)

    def get_previous_commit(self, repo_path: Path) -> Optional[str]:
        """Get second latest commit hash (proxy to GitClient)."""
        return self.git.get_previous_commit(repo_path)

    def get_commit_diff(
        self, repo_path: Path, old_commit: Optional[str], new_commit: str
    ) -> str:
        """Get commit diff (proxy to GitClient)."""
        return self.git.get_commit_diff(repo_path, old_commit, new_commit)

    def get_commit_messages(
        self, repo_path: Path, old_commit: Optional[str], new_commit: str
    ) -> List[str]:
        """Get commit messages (proxy to GitClient)."""
        return self.git.get_commit_messages(repo_path, old_commit, new_commit)

    def get_commit_count(
        self, repo_path: Path, old_commit: Optional[str], new_commit: str
    ) -> int:
        """Get commit count (proxy to GitClient)."""
        return self.git.get_commit_count(repo_path, old_commit, new_commit)

    def get_nth_commit_from_head(self, repo_path: Path, n: int) -> Optional[str]:
        """Get nth commit from HEAD (proxy to GitClient)."""
        return self.git.get_nth_commit_from_head(repo_path, n)

    def get_total_commit_count(self, repo_path: Path) -> int:
        """Get total commit count (proxy to GitClient)."""
        return self.git.get_total_commit_count(repo_path)

    def get_recent_commit_hashes(self, repo_path: Path, max_count: int) -> list[str]:
        """Get recent commit hashes (proxy to GitClient)."""
        return self.git.get_recent_commit_hashes(repo_path, max_count)

    def get_recent_commit_messages(self, repo_path: Path, max_count: int) -> List[str]:
        """Get recent commit messages (proxy to GitClient)."""
        return self.git.get_recent_commit_messages(repo_path, max_count)

    def get_recent_commit_patches(self, repo_path: Path, max_count: int) -> str:
        """Get recent commit patches (proxy to GitClient)."""
        return self.git.get_recent_commit_patches(repo_path, max_count)
