"""Git module - low-level Git and GitHub operations.

This module provides low-level Git and GitHub API operations without
business logic. For high-level repository management with analysis and
tracking, see progress.contrib.repo.
"""

from .client import GitClient, parse_protocol_from_url
from .github_client import GitHubClient
from .url import (
    normalize_repo_url,
    resolve_repo_url,
    sanitize_repo_name,
)

__all__ = [
    "GitClient",
    "GitHubClient",
    "parse_protocol_from_url",
    "normalize_repo_url",
    "resolve_repo_url",
    "sanitize_repo_name",
]
