"""Unit tests for ``progress.cli.git.github.list_owner_repos`` (T10 pagination)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from progress.cli.git.github import GitHubClient

if TYPE_CHECKING:
    import pytest


class FakeGitHubClient:
    """Minimal stand-in for ``GitHubClient`` exposing ``_getiter``."""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        self._items = items

    async def _getiter(self, url: str):
        for item in self._items:
            yield item


def _make_repo_item(
    full_name: str,
    created_at: str,
) -> dict[str, Any]:
    return {
        "id": 1,
        "name": full_name.rsplit("/", maxsplit=1)[-1],
        "full_name": full_name,
        "owner": {"login": full_name.split("/", maxsplit=1)[0]},
        "default_branch": "main",
        "description": "",
        "html_url": f"https://github.com/{full_name}",
        "created_at": created_at,
        "fork": False,
    }


class TestListOwnerReposWatermark:
    """T10 — sort+per_page URL + watermark early termination."""

    async def test_url_contains_sort_per_page(self, monkeypatch: pytest.MonkeyPatch) -> None:

        captured_urls: list[str] = []

        async def _capturing_getiter(self, url: str):
            captured_urls.append(url)
            return
            yield  # pragma: no cover

        monkeypatch.setattr(GitHubClient, "_getiter", _capturing_getiter)

        gh = GitHubClient.__new__(GitHubClient)
        async for _ in gh.list_owner_repos("vitejs", owner_type="organization"):
            pass

        assert captured_urls == ["/orgs/vitejs/repos?sort=created&direction=desc&per_page=100"]

    async def test_watermark_terminates_early(self, monkeypatch: pytest.MonkeyPatch) -> None:

        items = [
            _make_repo_item("vitejs/newest", "2024-03-01T00:00:00Z"),
            _make_repo_item("vitejs/old", "2023-01-01T00:00:00Z"),
        ]

        async def _fake_getiter(self, url):
            for item in items:
                yield item

        monkeypatch.setattr(GitHubClient, "_getiter", _fake_getiter)

        gh = GitHubClient.__new__(GitHubClient)
        wm = datetime(2024, 1, 1, tzinfo=UTC)
        repos = [
            repo async for repo in gh.list_owner_repos("vitejs", owner_type="organization", watermark=wm.isoformat())
        ]

        assert len(repos) == 1
        assert repos[0].full_name == "vitejs/newest"

    async def test_no_watermark_yields_all(self, monkeypatch: pytest.MonkeyPatch) -> None:

        items = [
            _make_repo_item("vitejs/a", "2024-02-01T00:00:00Z"),
            _make_repo_item("vitejs/b", "2024-01-01T00:00:00Z"),
        ]

        async def _fake_getiter(self, url):
            for item in items:
                yield item

        monkeypatch.setattr(GitHubClient, "_getiter", _fake_getiter)

        gh = GitHubClient.__new__(GitHubClient)
        repos = [repo async for repo in gh.list_owner_repos("vitejs", owner_type="organization")]

        assert len(repos) == 2
