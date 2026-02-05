"""GitHub release monitoring unit tests"""

from unittest.mock import patch, MagicMock
import pytest
import json

from progress.github import gh_release_list, gh_release_get_commit
from progress.errors import GitException


class TestGhReleaseList:
    """Test gh_release_list function."""

    def test_success_with_releases(self):
        """Test successful release list retrieval."""
        mock_releases = [
            {
                "tagName": "v1.0.0",
                "name": "Version 1.0.0",
                "publishedAt": "2024-01-01T00:00:00Z"
            },
            {
                "tagName": "v2.0.0",
                "name": "Version 2.0.0",
                "publishedAt": "2024-02-01T00:00:00Z"
            }
        ]

        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.return_value = json.dumps(mock_releases)
            releases = gh_release_list("owner/repo")

            assert len(releases) == 2
            assert releases[0]["tagName"] == "v1.0.0"
            assert releases[1]["tagName"] == "v2.0.0"
            mock_cmd.assert_called_once()

    def test_success_no_releases_empty_response(self):
        """Test repository with no releases - empty JSON response."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.return_value = '[]'
            releases = gh_release_list("owner/repo")

            assert releases == []

    def test_success_no_releases_empty_string(self):
        """Test repository with no releases - empty string response."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.return_value = ''
            releases = gh_release_list("owner/repo")

            assert releases == []

    def test_no_releases_found_message(self):
        """Test handling of 'no releases found' error message."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.side_effect = RuntimeError("no releases found")
            releases = gh_release_list("owner/repo")

            assert releases == []

    def test_not_found_message(self):
        """Test handling of 'not found' error message."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.side_effect = RuntimeError("repository not found")
            releases = gh_release_list("owner/repo")

            assert releases == []

    def test_rate_limit_error(self):
        """Test rate limit error detection and handling."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.side_effect = RuntimeError("API rate limit exceeded")

            with pytest.raises(GitException) as exc_info:
                gh_release_list("owner/repo")

            assert "rate limit" in str(exc_info.value).lower()

    def test_repository_not_found(self):
        """Test repository not found error."""
        # Use an error message that won't match the "no releases" check
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.side_effect = RuntimeError("could not find repository")

            with pytest.raises(GitException) as exc_info:
                gh_release_list("nonexistent/repo")

            assert "not found" in str(exc_info.value).lower() or "failed to list" in str(exc_info.value).lower()

    def test_access_denied(self):
        """Test access denied error."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.side_effect = RuntimeError("Access denied")

            with pytest.raises(GitException) as exc_info:
                gh_release_list("private/repo")

            assert "access denied" in str(exc_info.value).lower()

    def test_forbidden(self):
        """Test forbidden error."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.side_effect = RuntimeError("403 Forbidden")

            with pytest.raises(GitException) as exc_info:
                gh_release_list("private/repo")

            assert "forbidden" in str(exc_info.value).lower() or "access denied" in str(exc_info.value).lower()

    def test_generic_error(self):
        """Test generic error is properly wrapped."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.side_effect = RuntimeError("Some unknown error")

            with pytest.raises(GitException) as exc_info:
                gh_release_list("owner/repo")

            assert "Failed to list releases" in str(exc_info.value)

    def test_exclude_drafts_parameter(self):
        """Test exclude_drafts parameter is passed correctly."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.return_value = '[]'
            gh_release_list("owner/repo", exclude_drafts=True)

            called_cmd = mock_cmd.call_args[0][0]
            assert "--exclude-drafts" in called_cmd

    def test_exclude_pre_releases_parameter(self):
        """Test exclude_pre_releases parameter is passed correctly."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.return_value = '[]'
            gh_release_list("owner/repo", exclude_pre_releases=True)

            called_cmd = mock_cmd.call_args[0][0]
            assert "--exclude-pre-releases" in called_cmd

    def test_limit_parameter(self):
        """Test limit parameter is passed correctly."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.return_value = '[]'
            gh_release_list("owner/repo", limit=50)

            called_cmd = mock_cmd.call_args[0][0]
            assert "--limit" in called_cmd
            assert "50" in called_cmd

    def test_default_parameters(self):
        """Test default parameters are used when not specified."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.return_value = '[]'
            gh_release_list("owner/repo")

            called_cmd = mock_cmd.call_args[0][0]
            assert "--exclude-drafts" in called_cmd
            assert "--exclude-pre-releases" in called_cmd
            assert "--limit" in called_cmd
            assert "100" in called_cmd


class TestGhReleaseGetCommit:
    """Test gh_release_get_commit function."""

    def test_success(self):
        """Test successful commit hash retrieval."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.return_value = "abc123def456789"
            commit = gh_release_get_commit("owner/repo", "v1.0.0")

            assert commit == "abc123def456789"

    def test_success_with_whitespace(self):
        """Test commit hash is stripped of whitespace."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.return_value = "  abc123def456789  \n"
            commit = gh_release_get_commit("owner/repo", "v1.0.0")

            assert commit == "abc123def456789"

    def test_rate_limit_error(self):
        """Test rate limit error detection."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.side_effect = RuntimeError("API rate limit exceeded")

            with pytest.raises(GitException) as exc_info:
                gh_release_get_commit("owner/repo", "v1.0.0")

            assert "rate limit" in str(exc_info.value).lower()

    def test_release_not_found(self):
        """Test release not found error."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.side_effect = RuntimeError("Release not found")

            with pytest.raises(GitException) as exc_info:
                gh_release_get_commit("owner/repo", "v999.0.0")

            assert "not found" in str(exc_info.value).lower()

    def test_access_denied(self):
        """Test access denied error."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.side_effect = RuntimeError("Access denied")

            with pytest.raises(GitException) as exc_info:
                gh_release_get_commit("private/repo", "v1.0.0")

            assert "access denied" in str(exc_info.value).lower()

    def test_empty_response(self):
        """Test empty response handling."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.return_value = ""

            with pytest.raises(GitException) as exc_info:
                gh_release_get_commit("owner/repo", "v1.0.0")

            assert "No commit hash found" in str(exc_info.value)

    def test_command_construction(self):
        """Test command is constructed correctly."""
        with patch('progress.github.run_command') as mock_cmd:
            mock_cmd.return_value = "abc123"
            gh_release_get_commit("owner/repo", "v2.0.0")

            called_cmd = mock_cmd.call_args[0][0]
            assert "gh" in called_cmd
            assert "release" in called_cmd
            assert "view" in called_cmd
            assert "v2.0.0" in called_cmd
            assert "--repo" in called_cmd
            assert "owner/repo" in called_cmd
