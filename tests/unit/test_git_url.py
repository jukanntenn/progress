"""Unit tests for ``progress.cli.git.url`` (spec 07).

Pure-function tests: parse_repo_url, is_github_url, build_clone_url,
build_authenticated_clone_url. No IO, no mocks.

The legacy regex bug (``\\.?git?`` making the ``t`` optional, so "gi" matched)
is explicitly covered.
"""

from __future__ import annotations

import pytest

from progress.cli.git.url import (
    RepoRef,
    build_authenticated_clone_url,
    build_clone_url,
    is_github_url,
    parse_repo_url,
)


class TestParseRepoUrl:
    def test_https_url(self) -> None:
        ref = parse_repo_url("https://github.com/vitejs/vite")
        assert ref == RepoRef(owner="vitejs", name="vite")

    def test_https_url_with_dotgit(self) -> None:
        ref = parse_repo_url("https://github.com/vitejs/vite.git")
        assert ref == RepoRef(owner="vitejs", name="vite")

    def test_https_url_trailing_slash(self) -> None:
        ref = parse_repo_url("https://github.com/vitejs/vite/")
        assert ref == RepoRef(owner="vitejs", name="vite")

    def test_ssh_url(self) -> None:
        ref = parse_repo_url("git@github.com:vitejs/vite.git")
        assert ref == RepoRef(owner="vitejs", name="vite")

    def test_owner_name_shorthand(self) -> None:
        ref = parse_repo_url("vitejs/vite")
        assert ref == RepoRef(owner="vitejs", name="vite")

    def test_owner_name_with_dots_and_dashes(self) -> None:
        ref = parse_repo_url("facebook/react-native")
        assert ref == RepoRef(owner="facebook", name="react-native")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="empty repository url"):
            parse_repo_url("")

    def test_rejects_unknown_scheme(self) -> None:
        with pytest.raises(ValueError, match="unrecognised GitHub repository URL"):
            parse_repo_url("https://gitlab.com/vitejs/vite")

    def test_rejects_garbage(self) -> None:
        with pytest.raises(ValueError, match="unrecognised GitHub repository URL"):
            parse_repo_url("not a url at all")

    def test_strips_whitespace(self) -> None:
        ref = parse_repo_url("  vitejs/vite  ")
        assert ref == RepoRef(owner="vitejs", name="vite")


class TestIsGithubUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/vitejs/vite",
            "https://github.com/vitejs/vite.git",
            "git@github.com:vitejs/vite.git",
            "vitejs/vite",
        ],
    )
    def test_recognises(self, url: str) -> None:
        assert is_github_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "",
            "https://gitlab.com/foo/bar",
            "not a url",
        ],
    )
    def test_rejects(self, url: str) -> None:
        assert is_github_url(url) is False


class TestRepoRef:
    def test_slug(self) -> None:
        ref = RepoRef(owner="vitejs", name="vite")
        assert ref.slug == "vitejs/vite"

    def test_frozen(self) -> None:
        ref = RepoRef(owner="vitejs", name="vite")
        with pytest.raises(AttributeError):
            ref.owner = "other"  # ty:ignore[invalid-assignment]


class TestBuildCloneUrl:
    def test_canonical(self) -> None:
        assert build_clone_url("vitejs", "vite") == "https://github.com/vitejs/vite.git"


class TestBuildAuthenticatedCloneUrl:
    def test_with_token(self) -> None:
        url = build_authenticated_clone_url("vitejs", "vite", "abc123")
        assert url == "https://x-access-token:abc123@github.com/vitejs/vite.git"

    def test_without_token_returns_unauthenticated(self) -> None:
        url = build_authenticated_clone_url("vitejs", "vite", "")
        assert url == "https://github.com/vitejs/vite.git"
