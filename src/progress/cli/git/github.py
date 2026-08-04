"""GitHub API client (gidgethub aiohttp adapter, spec 07).

Wraps :class:`gidgethub.aiohttp.GitHubAPI` to expose a small typed API for the
operations Progress actually needs: repository metadata, releases, README, and
pull-request titles.

Per spec 07:
- All GitHub API calls go through gidgethub (replaces PyGithub + ``to_thread``).
- ``aiohttp.ClientSession`` is owned by the caller (CLI lifespan or API
  lifespan) and passed into :func:`create_github_client`.
- Errors are unified into :class:`GitHubAPIException`.
- The token is **never** logged (security fix).
- Transient failures (5xx ``GitHubBroken``, ``RateLimitExceeded``, network
  ``aiohttp.ClientError``) are retried here via tenacity with exponential
  backoff (spec 07). 4xx errors and 404s are not retried.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, override

import aiohttp
import gidgethub
from gidgethub.aiohttp import GitHubAPI

from progress.cli.git.url import RepoRef, parse_repo_url
from progress.errors import GitHubAPIException, GitHubNotFoundException
from progress.utils.http import retry_async
from progress.utils.timezone import parse_created_at

logger = logging.getLogger(__name__)

REQUESTER = "progress"

_TRANSIENT_GITHUB_ERRORS: tuple[type[Exception], ...] = (
    gidgethub.GitHubBroken,
    gidgethub.RateLimitExceeded,
    aiohttp.ClientError,
)


class ProxiedGitHubAPI(GitHubAPI):
    """GitHubAPI variant that routes every request through a per-request proxy.

    gidgethub's ``GitHubAPI`` calls ``session.request(...)`` without exposing a
    proxy kwarg, and aiohttp 3.10 has no session-level proxy. Subclassing to
    inject ``proxy=`` into each request is the supported way to proxy only
    GitHub traffic without polluting the process-wide ``HTTP_PROXY`` env vars
    (which would also drag Feishu/MarkPost/AI traffic through the GitHub proxy).
    """

    def __init__(self, *args: Any, proxy: str | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._proxy = proxy

    @override
    async def _request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes = b"",
    ) -> tuple[int, Mapping[str, str], bytes]:
        async with self._session.request(method, url, headers=headers, data=body, proxy=self._proxy) as response:
            return response.status, response.headers, await response.read()


@dataclass(frozen=True)
class Release:
    """Subset of GitHub release payload we consume (spec repo §6.5)."""

    tag: str
    name: str | None
    body: str | None
    url: str
    published_at: str = ""
    prerelease: bool = False
    draft: bool = False


@dataclass(frozen=True)
class RepositoryInfo:
    """Subset of GitHub repository payload we consume (spec repo §7.4)."""

    owner: str
    name: str
    full_name: str
    default_branch: str
    description: str | None
    html_url: str
    created_at: str = ""
    fork: bool = False
    archived: bool = False


class GitHubClient:
    """Typed wrapper around :class:`gidgethub.aiohttp.GitHubAPI`.

    The wrapper exists to:
    1. Convert raw dict responses into typed dataclasses.
    2. Centralise error translation (``gidgethub.HTTPException`` →
       :class:`GitHubAPIException`).
    3. Keep callers free of gidgethub imports so the integration layer
       depends on a stable internal API.
    """

    def __init__(self, gh: GitHubAPI) -> None:
        self._gh = gh

    async def get_repository(self, ref: RepoRef) -> RepositoryInfo:
        data = await self._getitem(f"/repos/{ref.owner}/{ref.name}")
        return _parse_repository(data)

    async def get_readme(self, ref: RepoRef) -> str:
        data = await self._getitem(
            f"/repos/{ref.owner}/{ref.name}/readme",
            accept="application/vnd.github.raw",
        )
        if isinstance(data, (bytes, bytearray)):
            return data.decode("utf-8", errors="replace")
        if isinstance(data, str):
            return data
        return str(data)

    async def get_latest_release(self, ref: RepoRef) -> Release | None:
        try:
            data = await self._getitem(f"/repos/{ref.owner}/{ref.name}/releases/latest")
        except GitHubNotFoundException:
            return None
        return _parse_release(data)

    async def iter_releases(self, ref: RepoRef) -> AsyncIterator[Release]:
        """Yield all releases for the repo.

        Per spec repo §6.5, draft and prerelease releases are filtered out
        here so callers never see them.
        """
        async for item in self._getiter(f"/repos/{ref.owner}/{ref.name}/releases"):
            release = _parse_release(item)
            if release.draft or release.prerelease:
                continue
            yield release

    async def get_release_commit_sha(self, ref: RepoRef, tag: str) -> str | None:
        """Resolve the commit SHA a release tag points at (spec repo §6.5).

        Returns ``None`` on 404 or missing tag (caller should treat as
        "no commit hash available"; per spec §6.4 this does NOT block).
        """
        try:
            data = await self._getitem(f"/repos/{ref.owner}/{ref.name}/git/refs/tags/{tag}")
        except GitHubNotFoundException:
            return None
        if not isinstance(data, dict):
            return None
        obj = data.get("object") or {}
        sha = obj.get("sha")
        if not sha:
            return None
        if obj.get("type") == "tag":
            try:
                tag_obj = await self._getitem(f"/repos/{ref.owner}/{ref.name}/git/tags/{sha}")
            except GitHubNotFoundException:
                return None
            if isinstance(tag_obj, dict):
                return (tag_obj.get("object") or {}).get("sha") or sha
        return str(sha)

    async def get_pull_request_title(self, ref: RepoRef, number: int) -> str:
        data = await self._getitem(f"/repos/{ref.owner}/{ref.name}/pulls/{number}")
        title = data.get("title") if isinstance(data, dict) else None
        if not title:
            raise GitHubAPIException(f"PR {ref.slug}#{number} returned no title")
        return str(title)

    async def list_owner_repos(
        self, owner: str, *, owner_type: str, watermark: str | None = None
    ) -> AsyncIterator[RepositoryInfo]:
        if owner_type == "organization":
            url = f"/orgs/{owner}/repos?sort=created&direction=desc&per_page=100"
        elif owner_type == "user":
            url = f"/users/{owner}/repos?sort=created&direction=desc&per_page=100"
        else:
            raise GitHubAPIException(f"unknown owner type: {owner_type!r}")
        wm_dt: datetime | None = None
        if watermark is not None:
            wm_dt = parse_created_at(watermark)
        async for item in self._getiter(url):
            try:
                repo = _parse_repository(item)
            except GitHubNotFoundException:
                continue
            if wm_dt is not None and repo.created_at:
                created = parse_created_at(repo.created_at)
                if created is not None and created <= wm_dt:
                    return
            yield repo

    async def _getitem(self, url: str, *, accept: str | None = None) -> Any:
        kwargs: dict[str, Any] = {}
        if accept is not None:
            kwargs["accept"] = accept

        async def _call() -> Any:
            try:
                return await self._gh.getitem(url, **kwargs)
            except gidgethub.HTTPException as e:
                translated = _translate(url, e)
                if isinstance(e, _TRANSIENT_GITHUB_ERRORS):
                    raise
                raise translated from e

        try:
            return await retry_async(_call, retry_on=_TRANSIENT_GITHUB_ERRORS)
        except gidgethub.HTTPException as e:
            raise _translate(url, e) from e

    async def _getiter(self, url: str) -> AsyncIterator[Any]:
        async def _call() -> Any:
            return self._gh.getiter(url)

        try:
            iterator = await retry_async(_call, retry_on=_TRANSIENT_GITHUB_ERRORS)
        except gidgethub.HTTPException as e:
            raise _translate(url, e) from e
        if iterator is None:
            raise GitHubAPIException(
                f"GitHub API returned no iterable data for {url} (possible proxy/network corruption)"
            )
        try:
            async for item in iterator:
                yield item
        except gidgethub.HTTPException as e:
            raise _translate(url, e) from e
        except TypeError as e:
            raise GitHubAPIException(f"GitHub API returned non-iterable data for {url}: {e}") from e


async def create_github_client(
    session: aiohttp.ClientSession,
    *,
    oauth_token: str,
    proxy: str | None = None,
) -> GitHubClient:
    """Build a :class:`GitHubClient` bound to ``session``.

    Per spec 07, callers own the session; this helper only wraps gidgethub's
    constructor. The ``oauth_token`` is required — call sites must downgrade
    when it is empty (see spec 02 zero-config behaviour).

    ``proxy`` is threaded into each GitHub request via :class:`ProxiedGitHubAPI`
    so only GitHub traffic is proxied (env-var-based proxying would leak the
    GitHub proxy into every other HTTP client in the process).
    """
    if not oauth_token:
        raise GitHubAPIException("GitHub token is required; downgrade caller should skip GitHub work")
    gh = ProxiedGitHubAPI(session, REQUESTER, oauth_token=oauth_token, proxy=proxy)
    return GitHubClient(gh)


def _translate(url: str, exc: gidgethub.HTTPException) -> GitHubAPIException:
    status = getattr(exc, "status_code", 0)
    if status == 404:
        return GitHubNotFoundException(f"GitHub 404 for {url}")
    return GitHubAPIException(f"GitHub API error {status} for {url}: {exc}")


def _parse_repository(data: dict[str, Any]) -> RepositoryInfo:
    full_name = data.get("full_name") or ""
    if "/" in full_name:
        owner, name = full_name.split("/", 1)
    else:
        owner = ""
        name = data.get("name") or ""
    return RepositoryInfo(
        owner=owner,
        name=name,
        full_name=full_name,
        default_branch=data.get("default_branch") or "main",
        description=data.get("description"),
        html_url=data.get("html_url") or "",
        created_at=data.get("created_at") or "",
        fork=bool(data.get("fork")),
        archived=bool(data.get("archived")),
    )


def _parse_release(data: dict[str, Any]) -> Release:
    return Release(
        tag=data.get("tag_name") or "",
        name=data.get("name"),
        body=data.get("body"),
        url=data.get("html_url") or "",
        published_at=data.get("published_at") or "",
        prerelease=bool(data.get("prerelease")),
        draft=bool(data.get("draft")),
    )


__all__ = [
    "GitHubClient",
    "Release",
    "RepositoryInfo",
    "create_github_client",
    "parse_repo_url",
]
