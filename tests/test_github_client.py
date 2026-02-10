"""GitHub API client unit tests"""

import pytest
from unittest.mock import Mock, patch
from progress.github_client import GitHubClient
from progress.errors import GitException


def test_github_client_initialization():
    """Test: GitHubClient initializes with token and proxy"""
    mock_github = Mock()
    with patch('progress.github_client.Github', return_value=mock_github) as mock_ctor:
        client = GitHubClient(token="test_token", proxy="http://proxy")
        mock_ctor.assert_called_once_with("test_token")
        mock_github.set_proxy.assert_called_once_with("http://proxy")


def test_github_client_initialization_without_proxy():
    """Test: GitHubClient initializes without proxy"""
    mock_github = Mock()
    with patch('progress.github_client.Github', return_value=mock_github) as mock_ctor:
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

        assert "access denied" in str(exc_info.value).lower() or "credentials" in str(exc_info.value).lower()
