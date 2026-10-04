"""Unit tests for ``progress.cli.git.github.iter_releases`` filtering."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from progress.cli.git import RepoRef
from progress.cli.git.github import GitHubClient

if TYPE_CHECKING:
    import pytest


def _make_release_item(
    tag: str,
    *,
    prerelease: bool = False,
    draft: bool = False,
    published_at: str = "2024-01-15T00:00:00Z",
) -> dict[str, Any]:
    return {
        "id": 1,
        "tag_name": tag,
        "name": tag,
        "body": "",
        "published_at": published_at,
        "prerelease": prerelease,
        "draft": draft,
        "html_url": f"https://github.com/vitejs/vite/releases/tag/{tag}",
    }


class TestIterReleasesFiltering:
    """Published releases pass through (incl. prereleases); drafts are dropped."""

    def _client_over(self, monkeypatch: pytest.MonkeyPatch, items: list[dict[str, Any]]) -> GitHubClient:
        async def _fake_getiter(self, url: str):
            for item in items:
                yield item

        monkeypatch.setattr(GitHubClient, "_getiter", _fake_getiter)
        return GitHubClient.__new__(GitHubClient)

    async def test_prereleases_are_included(self, monkeypatch: pytest.MonkeyPatch) -> None:

        gh = self._client_over(
            monkeypatch,
            [
                _make_release_item("v1.0.0"),
                _make_release_item("v0.9.0-rc.1", prerelease=True),
            ],
        )
        ref = RepoRef(owner="vitejs", name="vite")
        tags = [r.tag async for r in gh.iter_releases(ref)]

        assert tags == ["v1.0.0", "v0.9.0-rc.1"]

    async def test_drafts_are_excluded(self, monkeypatch: pytest.MonkeyPatch) -> None:

        gh = self._client_over(
            monkeypatch,
            [
                _make_release_item("v1.0.0"),
                _make_release_item("v1.1.0-draft", draft=True),
                _make_release_item("v0.9.0-rc.1", prerelease=True, draft=False),
            ],
        )
        ref = RepoRef(owner="vitejs", name="vite")
        tags = [r.tag async for r in gh.iter_releases(ref)]

        assert tags == ["v1.0.0", "v0.9.0-rc.1"]

    async def test_all_prereleases_still_yielded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A repo with only prereleases must not look release-less (deepseek-harness case)."""

        gh = self._client_over(
            monkeypatch,
            [
                _make_release_item("dsh-v0.1.1-rc.2", prerelease=True),
                _make_release_item("dsh-v0.1.1-rc.1", prerelease=True),
            ],
        )
        ref = RepoRef(owner="deepseek-ai", name="deepseek-harness")
        releases = [r async for r in gh.iter_releases(ref)]

        assert [r.tag for r in releases] == ["dsh-v0.1.1-rc.2", "dsh-v0.1.1-rc.1"]
        assert all(r.prerelease for r in releases)
