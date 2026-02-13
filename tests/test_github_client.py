"""GitHub API client unit tests"""

import pytest
from unittest.mock import Mock, patch
from progress.github_client import GitHubClient
from progress.errors import GitException


def test_github_client_initialization():
    """Test: GitHubClient initializes with token and proxy"""
    mock_github = Mock()
    with patch("progress.github_client.Github", return_value=mock_github) as mock_ctor:
        client = GitHubClient(token="test_token", proxy="http://proxy")
        mock_ctor.assert_called_once_with("test_token")
        mock_github.set_proxy.assert_called_once_with("http://proxy")


def test_github_client_initialization_without_proxy():
    """Test: GitHubClient initializes without proxy"""
    mock_github = Mock()
    with patch("progress.github_client.Github", return_value=mock_github) as mock_ctor:
        client = GitHubClient(token="test_token")
        mock_ctor.assert_called_once_with("test_token")
        mock_github.set_proxy.assert_not_called()


class TestListReleases:
    """Test list_releases method."""

    def test_success_with_releases(self):
        """Test successful release list retrieval."""
        mock_repo = Mock()
        mock_release1 = Mock()
        mock_release1.tag_name = "v1.0.0"
        mock_release1.title = "Version 1.0.0"
        mock_release1.published_at = "2024-01-01T00:00:00Z"
        mock_release1.draft = False
        mock_release1.prerelease = False

        mock_release2 = Mock()
        mock_release2.tag_name = "v2.0.0"
        mock_release2.title = "Version 2.0.0"
        mock_release2.published_at = "2024-02-01T00:00:00Z"
        mock_release2.draft = False
        mock_release2.prerelease = False

        mock_repo.get_releases.return_value = [mock_release2, mock_release1]

        mock_github = Mock()
        mock_github.get_repo.return_value = mock_repo

        client = GitHubClient(token="test")
        client.github = mock_github

        releases = client.list_releases("owner", "repo", limit=10)

        assert len(releases) == 2
        assert releases[0]["tagName"] == "v2.0.0"
        assert releases[1]["tagName"] == "v1.0.0"

    def test_success_no_releases(self):
        """Test repository with no releases."""
        mock_repo = Mock()
        mock_repo.get_releases.return_value = []

        mock_github = Mock()
        mock_github.get_repo.return_value = mock_repo

        client = GitHubClient(token="test")
        client.github = mock_github

        releases = client.list_releases("owner", "repo")

        assert releases == []

    def test_repository_not_found(self):
        """Test repository not found error."""
        from github import UnknownObjectException

        mock_github = Mock()
        mock_github.get_repo.side_effect = UnknownObjectException(
            404, {"message": "Not Found"}
        )

        client = GitHubClient(token="test")
        client.github = mock_github

        releases = client.list_releases("owner", "repo")

        assert releases == []

    def test_rate_limit_error(self):
        """Test rate limit error."""
        from github import RateLimitExceededException

        mock_github = Mock()
        mock_github.get_repo.side_effect = RateLimitExceededException(
            403, {"message": "API rate limit exceeded"}
        )

        client = GitHubClient(token="test")
        client.github = mock_github

        with pytest.raises(GitException) as exc_info:
            client.list_releases("owner", "repo")

        assert "rate limit" in str(exc_info.value).lower()

    def test_bad_credentials(self):
        """Test bad credentials error."""
        from github import BadCredentialsException

        mock_github = Mock()
        mock_github.get_repo.side_effect = BadCredentialsException(
            401, {"message": "Bad credentials"}
        )

        client = GitHubClient(token="test")
        client.github = mock_github

        with pytest.raises(GitException) as exc_info:
            client.list_releases("owner", "repo")

        assert (
            "access denied" in str(exc_info.value).lower()
            or "credentials" in str(exc_info.value).lower()
        )


class TestListRepos:
    """Test list_repos method."""

    def test_success(self):
        """Test successful repository list retrieval."""
        mock_repo1 = Mock()
        mock_repo1.full_name = "owner/repo1"
        mock_repo1.description = "First repository"
        mock_repo1.created_at = "2024-01-01T00:00:00Z"
        mock_repo1.updated_at = "2024-02-01T00:00:00Z"
        mock_repo1.source = True

        mock_repo2 = Mock()
        mock_repo2.full_name = "owner/repo2"
        mock_repo2.description = "Second repository"
        mock_repo2.created_at = "2024-01-02T00:00:00Z"
        mock_repo2.updated_at = "2024-02-02T00:00:00Z"
        mock_repo2.source = True

        mock_user = Mock()
        mock_user.get_repos.return_value = [mock_repo1, mock_repo2]

        mock_github = Mock()
        mock_github.get_user.return_value = mock_user

        client = GitHubClient(token="test")
        client.github = mock_github

        repos = client.list_repos("owner", limit=100, source=True)

        assert len(repos) == 2
        assert repos[0]["nameWithOwner"] == "owner/repo1"
        assert repos[0]["description"] == "First repository"
        assert repos[1]["nameWithOwner"] == "owner/repo2"

    def test_organization_not_found(self):
        """Test organization not found returns empty list."""
        from github import UnknownObjectException

        mock_github = Mock()
        mock_github.get_user.side_effect = UnknownObjectException(
            404, {"message": "Not Found"}
        )

        client = GitHubClient(token="test")
        client.github = mock_github

        repos = client.list_repos("nonexistent")

        assert repos == []

    def test_rate_limit_error(self):
        """Test rate limit error."""
        from github import RateLimitExceededException

        mock_github = Mock()
        mock_github.get_user.side_effect = RateLimitExceededException(
            403, {"message": "API rate limit exceeded"}
        )

        client = GitHubClient(token="test")
        client.github = mock_github

        with pytest.raises(GitException) as exc_info:
            client.list_repos("owner")

        assert "rate limit" in str(exc_info.value).lower()


class TestGetReleaseCommit:
    """Test get_release_commit method."""

    def test_success(self):
        """Test successful release commit retrieval."""
        mock_release = Mock()
        mock_release.tag_name = "v1.0.0"
        mock_release.title = "Version 1.0.0"
        mock_release.published_at = "2024-01-01T00:00:00Z"
        mock_release.draft = False
        mock_release.prerelease = False
        mock_release.html_url = "https://github.com/owner/repo/releases/tag/v1.0.0"

        mock_tag = Mock()
        mock_tag.name = "v1.0.0"
        mock_tag.commit.sha = "abc123def456"

        mock_repo = Mock()
        mock_repo.get_releases.return_value = [mock_release]
        mock_repo.get_tags.return_value = [mock_tag]

        mock_github = Mock()
        mock_github.get_repo.return_value = mock_repo

        client = GitHubClient(token="test")
        client.github = mock_github

        commit = client.get_release_commit("owner", "repo", "v1.0.0")

        assert commit == "abc123def456"

    def test_release_not_found(self):
        """Test release not found raises GitException."""
        mock_repo = Mock()
        mock_repo.get_releases.return_value = []

        mock_github = Mock()
        mock_github.get_repo.return_value = mock_repo

        client = GitHubClient(token="test")
        client.github = mock_github

        with pytest.raises(GitException) as exc_info:
            client.get_release_commit("owner", "repo", "v1.0.0")

        assert "not found" in str(exc_info.value).lower()

    def test_rate_limit_error(self):
        """Test rate limit error."""
        from github import RateLimitExceededException

        mock_github = Mock()
        mock_github.get_repo.side_effect = RateLimitExceededException(
            403, {"message": "API rate limit exceeded"}
        )

        client = GitHubClient(token="test")
        client.github = mock_github

        with pytest.raises(GitException) as exc_info:
            client.get_release_commit("owner", "repo", "v1.0.0")

        assert "rate limit" in str(exc_info.value).lower()


class TestGetReleaseBody:
    """Test get_release_body method."""

    def test_success(self):
        """Test successful release body retrieval."""
        mock_release = Mock()
        mock_release.tag_name = "v1.0.0"
        mock_release.title = "Version 1.0.0"
        mock_release.body = "Release notes here"
        mock_release.published_at = "2024-01-01T00:00:00Z"
        mock_release.draft = False
        mock_release.prerelease = False

        mock_repo = Mock()
        mock_repo.get_releases.return_value = [mock_release]

        mock_github = Mock()
        mock_github.get_repo.return_value = mock_repo

        client = GitHubClient(token="test")
        client.github = mock_github

        body = client.get_release_body("owner", "repo", "v1.0.0")

        assert body == "Release notes here"

    def test_success_with_empty_body(self):
        """Test release with empty body returns empty string."""
        mock_release = Mock()
        mock_release.tag_name = "v1.0.0"
        mock_release.title = "Version 1.0.0"
        mock_release.body = None
        mock_release.published_at = "2024-01-01T00:00:00Z"
        mock_release.draft = False
        mock_release.prerelease = False

        mock_repo = Mock()
        mock_repo.get_releases.return_value = [mock_release]

        mock_github = Mock()
        mock_github.get_repo.return_value = mock_repo

        client = GitHubClient(token="test")
        client.github = mock_github

        body = client.get_release_body("owner", "repo", "v1.0.0")

        assert body == ""

    def test_release_not_found(self):
        """Test release not found raises GitException."""
        mock_repo = Mock()
        mock_repo.get_releases.return_value = []

        mock_github = Mock()
        mock_github.get_repo.return_value = mock_repo

        client = GitHubClient(token="test")
        client.github = mock_github

        with pytest.raises(GitException) as exc_info:
            client.get_release_body("owner", "repo", "v1.0.0")

        assert "not found" in str(exc_info.value).lower()


class TestGetReadme:
    """Test get_readme method."""

    def test_success(self):
        """Test successful README retrieval."""
        mock_content = Mock()
        mock_content.decoded_content.decode.return_value = (
            "# README\n\nThis is a readme"
        )

        mock_repo = Mock()
        mock_repo.get_readme.return_value = mock_content

        mock_github = Mock()
        mock_github.get_repo.return_value = mock_repo

        client = GitHubClient(token="test")
        client.github = mock_github

        readme = client.get_readme("owner", "repo")

        assert readme == "# README\n\nThis is a readme"

    def test_readme_not_found(self):
        """Test README not found returns None."""
        from github import UnknownObjectException

        mock_repo = Mock()
        mock_repo.get_readme.side_effect = UnknownObjectException(
            404, {"message": "Not Found"}
        )

        mock_github = Mock()
        mock_github.get_repo.return_value = mock_repo

        client = GitHubClient(token="test")
        client.github = mock_github

        readme = client.get_readme("owner", "repo")

        assert readme is None

    def test_api_error(self):
        """Test API error raises GitException."""
        from github import GithubException

        mock_repo = Mock()
        mock_repo.get_readme.side_effect = GithubException(
            500, {"message": "Internal Server Error"}
        )

        mock_github = Mock()
        mock_github.get_repo.return_value = mock_repo

        client = GitHubClient(token="test")
        client.github = mock_github

        with pytest.raises(GitException):
            client.get_readme("owner", "repo")
