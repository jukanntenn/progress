"""GitHub API client using PyGithub.

PyGithub is a synchronous, ``requests``-based client with no async
alternative. Every API call runs off the event loop via
``asyncio.to_thread``; the ``_*_sync`` helpers contain the original PyGithub
logic unchanged.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from github import (
    BadCredentialsException,
    Github,
    RateLimitExceededException,
    UnknownObjectException,
)

from ..errors import GitException

logger = logging.getLogger(__name__)


class GitHubClient:
    """GitHub API client using PyGithub."""

    def __init__(self, token: str | None = None, proxy: str | None = None):
        if proxy:
            self._configure_proxy(proxy)
        self.github = Github(token)
        logger.debug(
            f"GitHubClient initialized (token: {token[:8] + '...' if token else 'None'})"
        )

    @staticmethod
    def _configure_proxy(proxy: str) -> None:
        os.environ["HTTP_PROXY"] = proxy
        os.environ["HTTPS_PROXY"] = proxy
        os.environ["http_proxy"] = proxy
        os.environ["https_proxy"] = proxy
        if proxy.startswith(("socks4://", "socks4a://", "socks5://", "socks5h://")):
            os.environ["ALL_PROXY"] = proxy
            os.environ["all_proxy"] = proxy

    def _list_releases_sync(
        self,
        owner: str,
        repo: str,
        exclude_drafts: bool = True,
        exclude_pre_releases: bool = True,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        try:
            repo_obj = self.github.get_repo(f"{owner}/{repo}")
            releases = repo_obj.get_releases()

            result = []
            for release in releases:
                if exclude_drafts and release.draft:
                    continue
                if exclude_pre_releases and release.prerelease:
                    continue
                published_at = release.published_at
                if isinstance(published_at, datetime):
                    if published_at.tzinfo is None:
                        published_at = published_at.replace(tzinfo=timezone.utc)
                    published_at = published_at.isoformat().replace("+00:00", "Z")
                result.append(
                    {
                        "tagName": release.tag_name,
                        "name": release.title,
                        "publishedAt": published_at,
                    }
                )
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
            raise GitException(
                f"Failed to list releases for {owner}/{repo}: {e}"
            ) from e

    async def list_releases(
        self,
        owner: str,
        repo: str,
        exclude_drafts: bool = True,
        exclude_pre_releases: bool = True,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._list_releases_sync,
            owner,
            repo,
            exclude_drafts,
            exclude_pre_releases,
            limit,
        )

    def _list_repos_sync(
        self,
        owner: str,
        limit: int = 100,
        source: bool = True,
    ) -> list[dict[str, Any]]:
        try:
            user = self.github.get_user(owner)
            repos = user.get_repos()

            result = []
            for repo in repos:
                if source:
                    fork_attr = getattr(repo, "fork", None)
                    is_fork = fork_attr if isinstance(fork_attr, bool) else False
                    if is_fork:
                        continue

                    source_attr = getattr(repo, "source", None)
                    if isinstance(source_attr, bool) and not source_attr:
                        continue
                created_at = getattr(repo, "created_at", None)
                updated_at = getattr(repo, "updated_at", None)

                if isinstance(created_at, datetime):
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                    created_at = created_at.isoformat().replace("+00:00", "Z")
                if isinstance(updated_at, datetime):
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=timezone.utc)
                    updated_at = updated_at.isoformat().replace("+00:00", "Z")
                result.append(
                    {
                        "nameWithOwner": repo.full_name,
                        "description": repo.description,
                        "createdAt": created_at,
                        "updatedAt": updated_at,
                    }
                )
                if len(result) >= limit:
                    break

            logger.debug(f"Found {len(result)} repositories for {owner}")
            return result

        except UnknownObjectException:
            logger.debug(f"Owner {owner} not found")
            return []
        except RateLimitExceededException as e:
            logger.warning(f"GitHub API rate limit reached: {e}")
            raise GitException(f"GitHub API rate limit exceeded: {e}") from e
        except BadCredentialsException as e:
            logger.warning(f"GitHub API authentication failed: {e}")
            raise GitException(f"Owner {owner} access denied: {e}") from e
        except Exception as e:
            logger.error(f"Failed to list repositories for {owner}: {e}")
            raise GitException(f"Failed to list repositories for {owner}: {e}") from e

    async def list_repos(
        self,
        owner: str,
        limit: int = 100,
        source: bool = True,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_repos_sync, owner, limit, source)

    def _get_release_commit_sync(self, owner: str, repo: str, tag_name: str) -> str:
        try:
            repo_obj = self.github.get_repo(f"{owner}/{repo}")
            releases = repo_obj.get_releases()

            for release in releases:
                if release.tag_name == tag_name:
                    tags = repo_obj.get_tags()
                    for tag in tags:
                        if tag.name == tag_name:
                            logger.debug(
                                f"Found commit {tag.commit.sha} for {owner}/{repo}:{tag_name}"
                            )
                            return tag.commit.sha

            logger.debug(f"Release {tag_name} not found for {owner}/{repo}")
            raise GitException(f"Release {tag_name} not found for {owner}/{repo}")

        except GitException:
            raise
        except UnknownObjectException as e:
            logger.error(f"Repository or release not found: {e}")
            raise GitException(
                f"Repository {owner}/{repo} or release {tag_name} not found: {e}"
            ) from e
        except RateLimitExceededException as e:
            logger.warning(f"GitHub API rate limit reached: {e}")
            raise GitException(f"GitHub API rate limit exceeded: {e}") from e
        except BadCredentialsException as e:
            logger.warning(f"GitHub API authentication failed: {e}")
            raise GitException(f"Repository {owner}/{repo} access denied: {e}") from e
        except Exception as e:
            logger.error(
                f"Failed to get release commit for {owner}/{repo}:{tag_name}: {e}"
            )
            raise GitException(
                f"Failed to get release commit for {owner}/{repo}:{tag_name}: {e}"
            ) from e

    async def get_release_commit(self, owner: str, repo: str, tag_name: str) -> str:
        return await asyncio.to_thread(self._get_release_commit_sync, owner, repo, tag_name)

    def _get_release_body_sync(self, owner: str, repo: str, tag_name: str) -> str:
        try:
            repo_obj = self.github.get_repo(f"{owner}/{repo}")
            releases = repo_obj.get_releases()

            for release in releases:
                if release.tag_name == tag_name:
                    body = release.body or ""
                    logger.debug(f"Found release body for {owner}/{repo}:{tag_name}")
                    return body

            logger.debug(f"Release {tag_name} not found for {owner}/{repo}")
            raise GitException(f"Release {tag_name} not found for {owner}/{repo}")

        except GitException:
            raise
        except UnknownObjectException as e:
            logger.error(f"Repository or release not found: {e}")
            raise GitException(
                f"Repository {owner}/{repo} or release {tag_name} not found: {e}"
            ) from e
        except RateLimitExceededException as e:
            logger.warning(f"GitHub API rate limit reached: {e}")
            raise GitException(f"GitHub API rate limit exceeded: {e}") from e
        except BadCredentialsException as e:
            logger.warning(f"GitHub API authentication failed: {e}")
            raise GitException(f"Repository {owner}/{repo} access denied: {e}") from e
        except Exception as e:
            logger.error(
                f"Failed to get release body for {owner}/{repo}:{tag_name}: {e}"
            )
            raise GitException(
                f"Failed to get release body for {owner}/{repo}:{tag_name}: {e}"
            ) from e

    async def get_release_body(self, owner: str, repo: str, tag_name: str) -> str:
        return await asyncio.to_thread(self._get_release_body_sync, owner, repo, tag_name)

    def _get_readme_sync(self, owner: str, repo: str) -> str | None:
        try:
            repo_obj = self.github.get_repo(f"{owner}/{repo}")
            readme_content = repo_obj.get_readme()
            content = readme_content.decoded_content.decode()
            logger.debug(f"Found README for {owner}/{repo}")
            return content

        except UnknownObjectException:
            logger.debug(f"README not found for {owner}/{repo}")
            return None
        except RateLimitExceededException as e:
            logger.warning(f"GitHub API rate limit reached: {e}")
            raise GitException(f"GitHub API rate limit exceeded: {e}") from e
        except BadCredentialsException as e:
            logger.warning(f"GitHub API authentication failed: {e}")
            raise GitException(f"Repository {owner}/{repo} access denied: {e}") from e
        except Exception as e:
            logger.error(f"Failed to get README for {owner}/{repo}: {e}")
            raise GitException(f"Failed to get README for {owner}/{repo}: {e}") from e

    async def get_readme(self, owner: str, repo: str) -> str | None:
        return await asyncio.to_thread(self._get_readme_sync, owner, repo)


__all__ = ["GitHubClient"]
