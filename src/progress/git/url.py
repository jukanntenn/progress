"""URL utility functions for repository operations."""

import logging
import re

from ..consts import GIT_SUFFIX, GITHUB_HTTPS_PREFIX, GITHUB_SSH_PREFIX
from ..enums import Protocol
from ..utils import strip_git_suffix

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


def resolve_repo_url(repo_url: str, protocol: str | Protocol) -> tuple[str, str]:
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
