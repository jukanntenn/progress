"""Repository release checking unit tests (simplified)"""

from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

from progress.repo import Repo
from progress.models import Repository
from progress.github import GitClient
from progress.github_client import GitHubClient
from progress.config import Config
from progress.errors import GitException


@pytest.fixture
def mock_config():
    """Create a mock config object."""
    config = Mock(spec=Config)
    config.github = Mock()
    config.github.gh_timeout = 300
    config.github.git_timeout = 300
    config.workspace_dir = "/tmp/test"
    config.github.gh_token = None
    config.github.proxy = None
    return config


@pytest.fixture
def mock_git_client():
    """Create a mock GitClient."""
    from pathlib import Path
    git = Mock(spec=GitClient)
    git.workspace_dir = Path("/tmp/test")
    git.get_commit_diff = Mock(return_value="diff content")
    return git


@pytest.fixture
def mock_github_client():
    """Create a mock GitHubClient."""
    github_client = Mock(spec=GitHubClient)
    return github_client


@pytest.fixture
def mock_repository():
    """Create a mock repository."""
    repo = Mock(spec=Repository)
    repo.name = "test/repo"
    repo.url = "https://github.com/test/repo.git"
    repo.branch = "main"
    repo.last_release_tag = None
    repo.last_release_commit_hash = None
    repo.last_release_check_time = None
    repo.save = Mock()
    return repo


class TestCheckReleasesBasic:
    """Test basic Repo.check_releases() scenarios."""

    def test_first_check_with_releases(self, mock_repository, mock_git_client, mock_config, mock_github_client):
        """Test first-time check when releases exist."""
        mock_github_client.list_releases.return_value = [
            {
                "tagName": "v1.0.0",
                "name": "Version 1.0.0",
                "publishedAt": "2024-01-01T00:00:00Z"
            }
        ]
        mock_github_client.get_release_commit.return_value = "abc123def456"
        mock_github_client.get_release_body.return_value = "First release"

        repo = Repo(mock_repository, mock_git_client, mock_config, github_client=mock_github_client)
        result = repo.check_releases()

        assert result is not None
        assert "releases" in result
        assert len(result["releases"]) == 1
        assert result["releases"][0]["tag_name"] == "v1.0.0"
        assert result["releases"][0]["title"] == "Version 1.0.0"
        assert result["releases"][0]["notes"] == "First release"
        assert result["releases"][0]["commit_hash"] == "abc123def456"

        mock_github_client.list_releases.assert_called_once_with("test", "repo")
        mock_github_client.get_release_commit.assert_called_once_with("test", "repo", "v1.0.0")
        mock_github_client.get_release_body.assert_called_once_with("test", "repo", "v1.0.0")

    def test_first_check_no_releases(self, mock_repository, mock_git_client, mock_config, mock_github_client):
        """Test first-time check when repository has no releases."""
        mock_github_client.list_releases.return_value = []

        repo = Repo(mock_repository, mock_git_client, mock_config, github_client=mock_github_client)
        result = repo.check_releases()

        assert result is None

    def test_gh_cli_failure_returns_none(self, mock_repository, mock_git_client, mock_config, mock_github_client):
        """Test that GitHub CLI failure returns None gracefully."""
        mock_github_client.list_releases.side_effect = GitException("API error")

        repo = Repo(mock_repository, mock_git_client, mock_config, github_client=mock_github_client)
        result = repo.check_releases()

        assert result is None

    def test_incremental_check_filters_by_date(self, mock_repository, mock_git_client, mock_config, mock_github_client):
        """Test that incremental check filters releases by date correctly."""
        repo = Repo(mock_repository, mock_git_client, mock_config, github_client=mock_github_client)
        repo.model.last_release_tag = "v1.0.0"
        repo.model.last_release_commit_hash = "oldhash"
        repo.model.last_release_check_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=ZoneInfo("UTC"))

        # Mix of old and new releases
        mock_github_client.list_releases.return_value = [
            {
                "tagName": "v1.0.0",
                "publishedAt": "2023-12-01T00:00:00Z"  # Old
            },
            {
                "tagName": "v1.1.0",
                "publishedAt": "2024-01-15T00:00:00Z",  # New
                "name": "v1.1.0"
            },
            {
                "tagName": "v2.0.0",
                "publishedAt": "2024-02-01T00:00:00Z",  # New
                "name": "v2.0.0"
            }
        ]
        mock_github_client.get_release_commit.return_value = "abc123"
        mock_github_client.get_release_body.return_value = "Release notes"

        result = repo.check_releases()

        assert result is not None
        assert "releases" in result
        assert len(result["releases"]) == 2
        tag_names = [r["tag_name"] for r in result["releases"]]
        assert "v1.1.0" in tag_names
        assert "v2.0.0" in tag_names


class TestUpdateReleases:
    """Test Repo.update_releases() method."""

    def test_updates_repository_fields(self, mock_repository, mock_git_client, mock_config):
        """Test that update_releases sets the correct fields."""
        from progress import db

        repo = Repo(mock_repository, mock_git_client, mock_config)

        # Mock the database and atomic transaction
        with patch('progress.repo.get_now') as mock_get_now:
            with patch.object(db, 'database') as mock_database:
                mock_get_now.return_value = datetime(2024, 2, 1, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
                mock_database.atomic.return_value.__enter__ = Mock()
                mock_database.atomic.return_value.__exit__ = Mock(return_value=False)

                repo.update_releases("v2.0.0", "abc123")

                assert repo.model.last_release_tag == "v2.0.0"
                assert repo.model.last_release_commit_hash == "abc123"
                assert repo.model.last_release_check_time is not None


class TestReleaseAnalysisFallback:
    """Test fallback behavior when AI analysis fails."""

    def test_analysis_failure_generates_fallback_summary(self, mock_repository, mock_git_client, mock_config, mock_github_client):
        """Test that when AI analysis fails, a fallback summary is generated."""
        from progress.repository import RepositoryManager
        from progress.analyzer import ClaudeCodeAnalyzer
        from progress.reporter import MarkdownReporter
        from progress.errors import AnalysisException

        repo = Repo(mock_repository, mock_git_client, mock_config, github_client=mock_github_client)
        release_data = {
            "releases": [
                {
                    "tag_name": "v1.0.0",
                    "title": "Version 1.0.0",
                    "notes": "Initial release with features",
                    "published_at": "2024-01-01T00:00:00Z",
                    "commit_hash": "abc123"
                }
            ]
        }

        # Create analyzer mock that raises AnalysisException
        analyzer = Mock(spec=ClaudeCodeAnalyzer)
        analyzer.analyze_releases.side_effect = AnalysisException("Claude Code failed")

        reporter = Mock(spec=MarkdownReporter)
        manager = RepositoryManager(analyzer, reporter, mock_config)

        # Mock Repo class creation to avoid actual git operations
        with patch('progress.repository.Repo', return_value=repo):
            # Mock repo.check_releases to return test data
            with patch.object(repo, 'check_releases', return_value=release_data):
                with patch.object(repo, 'update_releases'):
                    with patch.object(repo, 'clone_or_update'):
                        with patch.object(repo, 'get_diff', return_value=None):
                            with patch.object(repo, 'get_current_commit', return_value="current123"):
                                result = manager.check(mock_repository)

        # Verify that despite analysis failure, we get fallback content
        assert result is not None
        assert result.releases is not None
        assert len(result.releases) == 1
        assert "AI analysis unavailable" in result.releases[0]["ai_summary"]
        assert "v1.0.0" in result.releases[0]["ai_summary"]
        assert result.releases[0]["ai_detail"] != ""
        assert "Tag:" in result.releases[0]["ai_detail"] or "tag" in result.releases[0]["ai_detail"].lower()

    def test_analysis_failure_with_no_notes(self, mock_repository, mock_git_client, mock_config, mock_github_client):
        """Test fallback when release has no notes."""
        from progress.repository import RepositoryManager
        from progress.analyzer import ClaudeCodeAnalyzer
        from progress.reporter import MarkdownReporter
        from progress.errors import AnalysisException

        repo = Repo(mock_repository, mock_git_client, mock_config, github_client=mock_github_client)
        release_data = {
            "releases": [
                {
                    "tag_name": "v2.0.0",
                    "title": "Version 2.0.0",
                    "notes": "",
                    "published_at": "2024-02-01T00:00:00Z",
                    "commit_hash": "def456"
                }
            ]
        }

        analyzer = Mock(spec=ClaudeCodeAnalyzer)
        analyzer.analyze_releases.side_effect = AnalysisException("AI unavailable")

        reporter = Mock(spec=MarkdownReporter)
        manager = RepositoryManager(analyzer, reporter, mock_config)

        with patch('progress.repository.Repo', return_value=repo):
            with patch.object(repo, 'check_releases', return_value=release_data):
                with patch.object(repo, 'update_releases'):
                    with patch.object(repo, 'clone_or_update'):
                        with patch.object(repo, 'get_diff', return_value=None):
                            with patch.object(repo, 'get_current_commit', return_value="current123"):
                                result = manager.check(mock_repository)

        assert result is not None
        assert result.releases is not None
        assert len(result.releases) == 1
        assert "AI analysis unavailable" in result.releases[0]["ai_summary"]
        assert "v2.0.0" in result.releases[0]["ai_summary"]
