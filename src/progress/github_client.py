"""GitHub API client using PyGithub"""

import logging
from typing import Optional
from github import Github
from .errors import GitException

logger = logging.getLogger(__name__)


class GitHubClient:
    """GitHub API client using PyGithub."""

    def __init__(self, token: Optional[str] = None, proxy: Optional[str] = None):
        """Initialize GitHub client.

        Args:
            token: GitHub personal access token (optional)
            proxy: Proxy URL for API requests (optional)
        """
        self.github = Github(token)
        if proxy:
            self.github.set_proxy(proxy)
        logger.debug(f"GitHubClient initialized (token: {token[:8] + '...' if token else 'None'})")
