"""GitHub API client using PyGithub"""

import logging
from typing import Optional
from github import Github, UnknownObjectException, RateLimitExceededException, BadCredentialsException
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

    def list_releases(
        self,
        owner: str,
        repo: str,
        exclude_drafts: bool = True,
        exclude_pre_releases: bool = True,
        limit: int = 100,
    ) -> list[dict]:
        """List GitHub releases for a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            exclude_drafts: Whether to exclude draft releases
            exclude_pre_releases: Whether to exclude pre-releases
            limit: Maximum number of releases to fetch

        Returns:
            List of release dicts with keys: tagName, name, publishedAt

        Raises:
            GitException: If API call fails (except not found)
        """
        try:
            repo_obj = self.github.get_repo(f"{owner}/{repo}")
            releases = repo_obj.get_releases()

            result = []
            for release in releases:
                if exclude_drafts and release.draft:
                    continue
                if exclude_pre_releases and release.prerelease:
                    continue
                result.append({
                    "tagName": release.tag_name,
                    "name": release.title,
                    "publishedAt": release.published_at,
                })
                if len(result) >= limit:
                    break

            logger.debug(f"Found {len(result)} releases for {owner}/{repo}")
            return result

        except UnknownObjectException:
            logger.debug(f"Repository {owner}/{repo} not found")
            return []
        except RateLimitExceededException as e:
            logger.warning(f"GitHub API rate limit reached: {e}")
            raise GitException(f"GitHub API rate limit exceeded: {e}") from e
        except BadCredentialsException as e:
            logger.warning(f"GitHub API authentication failed: {e}")
            raise GitException(f"Repository {owner}/{repo} access denied: {e}") from e
        except Exception as e:
            logger.error(f"Failed to list releases for {owner}/{repo}: {e}")
            raise GitException(f"Failed to list releases for {owner}/{repo}: {e}") from e
