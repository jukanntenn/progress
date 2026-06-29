"""RepositoryManager unit tests"""

from unittest.mock import Mock, patch

import pytest

from progress.contrib.repo.reporter import MarkdownReporter
from progress.contrib.repo.repository import RepositoryManager


class TestRepositoryManager:
    """Test RepositoryManager class"""

    @pytest.fixture
    def mock_config(self):
        """Create mock config"""
        config = Mock()
        config.workspace_dir = "/tmp/workspace"
        config.analysis.language = "en"
        config.analysis.max_diff_length = 100000
        github_config = Mock()
        github_config.gh_token = "test_token"
        github_config.proxy = None
        github_config.protocol = "https"
        github_config.git_timeout = 300
        config.github = github_config
        return config

    @pytest.fixture
    def mock_analyzer(self):
        """Create mock analyzer"""
        return Mock()

    @pytest.fixture
    def mock_reporter(self):
        """Create mock reporter"""
        reporter = Mock(spec=MarkdownReporter)
        return reporter

    @pytest.fixture
    def repo_manager(self, mock_analyzer, mock_reporter, mock_config):
        """Create RepositoryManager instance"""
        with patch("progress.contrib.repo.repository.GitClient"):
            with patch("progress.contrib.repo.repository.GitHubClient"):
                manager = RepositoryManager(mock_analyzer, mock_reporter, mock_config)
                return manager

    def test_analyze_all_releases_single_release(self, repo_manager):
        """Test analyzing a single release"""
        release_data = {
            "releases": [
                {
                    "tag_name": "v1.0.0",
                    "title": "Release 1.0.0",
                    "notes": "First release",
                    "published_at": "2024-01-01T00:00:00Z",
                    "commit_hash": "abc123",
                }
            ]
        }

        with patch(
            "progress.contrib.repo.repository.analyze_releases",
            return_value=("**Summary of v1.0.0**", "**Detailed analysis of v1.0.0**"),
        ) as mock_analyze:
            result = repo_manager._analyze_all_releases(
                "test/repo", "main", release_data
            )

            assert len(result) == 1
            assert result[0]["tag_name"] == "v1.0.0"
            assert result[0]["title"] == "Release 1.0.0"
            assert result[0]["notes"] == "First release"
            assert result[0]["ai_summary"] == "**Summary of v1.0.0**"
            assert result[0]["ai_detail"] == "**Detailed analysis of v1.0.0**"

            mock_analyze.assert_called_once()
            call_args = mock_analyze.call_args
            assert call_args[0][0] is repo_manager.analyzer
            assert call_args[0][1] == "test/repo"
            assert call_args[0][2] == "main"

    def test_analyze_all_releases_multiple_releases(self, repo_manager):
        """Test analyzing multiple releases individually"""
        release_data = {
            "releases": [
                {
                    "tag_name": "v1.2.0",
                    "title": "Release 1.2.0",
                    "notes": "New features",
                    "published_at": "2024-03-01T00:00:00Z",
                    "commit_hash": "def456",
                },
                {
                    "tag_name": "v1.1.0",
                    "title": "Release 1.1.0",
                    "notes": "Bug fixes",
                    "published_at": "2024-02-01T00:00:00Z",
                    "commit_hash": "ghi789",
                },
                {
                    "tag_name": "v1.0.0",
                    "title": "Release 1.0.0",
                    "notes": "First release",
                    "published_at": "2024-01-01T00:00:00Z",
                    "commit_hash": "abc123",
                },
            ]
        }

        with patch(
            "progress.contrib.repo.repository.analyze_releases",
            side_effect=[
                ("**Summary of v1.2.0**", "**Detail of v1.2.0**"),
                ("**Summary of v1.1.0**", "**Detail of v1.1.0**"),
                ("**Summary of v1.0.0**", "**Detail of v1.0.0**"),
            ],
        ) as mock_analyze:
            result = repo_manager._analyze_all_releases(
                "test/repo", "main", release_data
            )

            assert len(result) == 3
            assert mock_analyze.call_count == 3

            assert result[0]["tag_name"] == "v1.2.0"
            assert result[0]["ai_summary"] == "**Summary of v1.2.0**"
            assert result[0]["ai_detail"] == "**Detail of v1.2.0**"

            assert result[1]["tag_name"] == "v1.1.0"
            assert result[1]["ai_summary"] == "**Summary of v1.1.0**"
            assert result[1]["ai_detail"] == "**Detail of v1.1.0**"

            assert result[2]["tag_name"] == "v1.0.0"
            assert result[2]["ai_summary"] == "**Summary of v1.0.0**"
            assert result[2]["ai_detail"] == "**Detail of v1.0.0**"

    def test_analyze_all_releases_includes_diff_content(self, repo_manager):
        release_data = {
            "is_first_check": False,
            "releases": [
                {
                    "tag_name": "v2.0.0",
                    "title": "Release 2.0.0",
                    "notes": "Major update",
                    "published_at": "2024-02-01T00:00:00Z",
                    "commit_hash": "new123",
                }
            ],
        }

        mock_repo_obj = Mock()
        mock_repo_obj.repo_path = "/tmp/repo"
        mock_repo_obj.git.get_commit_diff.return_value = "diff text"

        with patch(
            "progress.contrib.repo.repository.analyze_releases",
            return_value=("Summary", "Detail"),
        ) as mock_analyze:
            repo_manager._analyze_all_releases(
                "test/repo",
                "main",
                release_data,
                mock_repo_obj,
                previous_release_commit="old456",
            )

            call_args = mock_analyze.call_args
            single_release_data = call_args[0][3]
            assert single_release_data["diff_content"] == "diff text"

    def test_analyze_all_releases_with_analysis_error(self, repo_manager):
        """Test graceful handling when AI analysis fails"""
        release_data = {
            "releases": [
                {
                    "tag_name": "v1.0.0",
                    "title": "Release 1.0.0",
                    "notes": "Important release notes",
                    "published_at": "2024-01-01T00:00:00Z",
                    "commit_hash": "abc123",
                }
            ]
        }

        with patch(
            "progress.contrib.repo.repository.analyze_releases",
            side_effect=Exception("AI service unavailable"),
        ):
            result = repo_manager._analyze_all_releases(
                "test/repo", "main", release_data
            )

            assert len(result) == 1
            assert result[0]["tag_name"] == "v1.0.0"
            assert result[0]["title"] == "Release 1.0.0"
            assert "AI analysis unavailable" in result[0]["ai_summary"]
            assert "v1.0.0" in result[0]["ai_summary"]
            assert "Release 1.0.0" in result[0]["ai_detail"]
            assert "Important release notes" in result[0]["ai_detail"]

    def test_release_analysis_failure_reports_error(self, repo_manager):
        """A swallowed release-analysis failure must still reach Bugsink."""
        release_data = {
            "releases": [
                {
                    "tag_name": "v1.0.0",
                    "title": "Release 1.0.0",
                    "notes": "notes",
                    "published_at": "2024-01-01T00:00:00Z",
                    "commit_hash": "abc123",
                }
            ]
        }

        with (
            patch(
                "progress.contrib.repo.repository.analyze_releases",
                side_effect=Exception("AI service unavailable"),
            ),
            patch("progress.contrib.repo.repository.report_error") as mock_report,
        ):
            repo_manager._analyze_all_releases("test/repo", "main", release_data)

        mock_report.assert_called_once()
        assert isinstance(mock_report.call_args.args[0], Exception)
        assert mock_report.call_args.kwargs["release_tag"] == "v1.0.0"
        assert mock_report.call_args.kwargs["stage"] == "release_analysis"
        assert mock_report.call_args.kwargs["repo"] == "test/repo"

    def test_analyze_all_releases_preserves_original_fields(self, repo_manager):
        """Test that all original release fields are preserved"""
        release_data = {
            "releases": [
                {
                    "tag_name": "v1.0.0",
                    "title": "Release 1.0.0",
                    "notes": "Release notes here",
                    "published_at": "2024-01-01T00:00:00Z",
                    "commit_hash": "abc123",
                    "author": "testuser",
                    "prerelease": False,
                }
            ]
        }

        with patch(
            "progress.contrib.repo.repository.analyze_releases",
            return_value=("Summary", "Detail"),
        ):
            result = repo_manager._analyze_all_releases(
                "test/repo", "main", release_data
            )

            assert len(result) == 1
            assert result[0]["tag_name"] == "v1.0.0"
            assert result[0]["title"] == "Release 1.0.0"
            assert result[0]["notes"] == "Release notes here"
            assert result[0]["published_at"] == "2024-01-01T00:00:00Z"
            assert result[0]["commit_hash"] == "abc123"
            assert result[0]["author"] == "testuser"
            assert result[0]["prerelease"] is False
            assert result[0]["ai_summary"] == "Summary"
            assert result[0]["ai_detail"] == "Detail"

    def test_analyze_all_releases_empty_list(self, repo_manager):
        """Test analyzing empty release list"""
        release_data = {"releases": []}

        with patch("progress.contrib.repo.repository.analyze_releases") as mock_analyze:
            result = repo_manager._analyze_all_releases(
                "test/repo", "main", release_data
            )

            assert result == []
            mock_analyze.assert_not_called()
