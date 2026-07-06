"""Repo class unit tests"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from progress.config import Config
from progress.contrib.repo.repo import Repo
from progress.db.models import Repository
from progress.git import GitClient


class TestRepo:
    """Test Repo class"""

    def test_properties(self):
        """Test slug, link, is_new, repo_path properties"""
        model = Mock(spec=Repository)
        model.url = "https://github.com/owner/repo.git"
        model.last_commit_hash = None

        git = Mock(spec=GitClient)
        git.workspace_dir = Path("/tmp/workspace")
        config = Mock(spec=Config)

        repo = Repo(model, git, config)

        assert repo.slug == "owner/repo"
        assert repo.link == "https://github.com/owner/repo"
        assert repo.is_new is True
        assert repo.repo_path == Path("/tmp/workspace/owner_repo")

    def test_properties_existing_repo(self):
        """Test properties for existing repository"""
        model = Mock(spec=Repository)
        model.url = "git@github.com:owner/repo.git"
        model.last_commit_hash = "abc123"

        git = Mock(spec=GitClient)
        git.workspace_dir = Path("/tmp/workspace")
        config = Mock(spec=Config)

        repo = Repo(model, git, config)

        assert repo.slug == "owner/repo"
        assert repo.is_new is False

    async def test_clone_or_update_first_time(self):
        """Test clone_or_update for new repository"""
        model = Mock(spec=Repository)
        model.url = "https://github.com/owner/repo.git"
        model.branch = "main"
        model.last_commit_hash = None

        git = Mock(spec=GitClient)
        git.workspace_dir = Path("/tmp/workspace")

        config = Mock(spec=Config)
        github_config = Mock()
        github_config.gh_timeout = 300
        config.github = github_config

        repo = Repo(model, git, config, gh_token="test_token")

        with patch.object(repo, "_run_gh_clone_command", new_callable=AsyncMock):
            result = await repo.clone_or_update()

            repo._run_gh_clone_command.assert_called_once_with(
                "https://github.com/owner/repo.git", "main"
            )
            assert result == Path("/tmp/workspace/owner_repo")

    async def test_clone_or_update_existing(self):
        """Test clone_or_update for existing repository"""
        model = Mock(spec=Repository)
        model.url = "https://github.com/owner/repo.git"
        model.branch = "main"
        model.last_commit_hash = "abc123"

        git = Mock(spec=GitClient)
        git.workspace_dir = Path("/tmp/workspace")
        git.fetch_and_reset = AsyncMock()

        config = Mock(spec=Config)

        repo = Repo(model, git, config)
        result = await repo.clone_or_update()

        git.fetch_and_reset.assert_called_once_with(
            Path("/tmp/workspace/owner_repo"), "main"
        )
        assert result == Path("/tmp/workspace/owner_repo")

    async def test_get_current_commit(self):
        """Test get_current_commit"""
        model = Mock(spec=Repository)
        model.url = "https://github.com/owner/repo.git"
        model.last_commit_hash = "abc123"

        git = Mock(spec=GitClient)
        git.workspace_dir = Path("/tmp/workspace")
        git.get_current_commit = AsyncMock(return_value="def456")

        config = Mock(spec=Config)

        repo = Repo(model, git, config)
        result = await repo.get_current_commit()

        git.get_current_commit.assert_called_once_with(
            Path("/tmp/workspace/owner_repo")
        )
        assert result == "def456"

    async def test_get_diff_no_new_commits(self):
        """Test get_diff returns None when no new commits"""
        model = Mock(spec=Repository)
        model.url = "https://github.com/owner/repo.git"
        model.branch = "main"
        model.last_commit_hash = "abc123"

        git = Mock(spec=GitClient)
        git.workspace_dir = Path("/tmp/workspace")
        git.get_current_commit = AsyncMock(return_value="abc123")
        git.fetch_and_reset = AsyncMock()

        config = Mock(spec=Config)

        repo = Repo(model, git, config)
        result = await repo.get_diff()

        assert result is None

    async def test_get_diff_first_check_insufficient_history(self):
        """Test get_diff uses recent mode when repository has only one commit"""
        model = Mock(spec=Repository)
        model.url = "https://github.com/owner/repo.git"
        model.branch = "main"
        model.last_commit_hash = None

        git = Mock(spec=GitClient)
        git.workspace_dir = Path("/tmp/workspace")
        git.get_current_commit = AsyncMock(return_value="abc123")
        git.get_total_commit_count = AsyncMock(return_value=1)
        git.get_recent_commit_hashes = AsyncMock(return_value=["abc123"])
        git.get_recent_commit_messages = AsyncMock(return_value=["msg"])
        git.get_recent_commit_patches = AsyncMock(return_value="diff content")
        git.fetch_and_reset = AsyncMock()

        config = Mock(spec=Config)
        analysis_config = Mock()
        analysis_config.first_run_lookback_commits = 3
        config.analysis = analysis_config

        repo = Repo(model, git, config)

        with patch.object(repo, "clone_or_update", new_callable=AsyncMock):
            result = await repo.get_diff()

        assert result is not None
        diff, previous_commit, commit_count, commit_messages, is_range_check = result
        assert diff == "diff content"
        assert previous_commit == "abc123"
        assert commit_count == 1
        assert commit_messages == ["msg"]
        assert is_range_check is False

    async def test_get_diff_first_check_range_mode(self):
        """Test get_diff uses old..new range when total commits > lookback"""
        model = Mock(spec=Repository)
        model.url = "https://github.com/owner/repo.git"
        model.branch = "main"
        model.last_commit_hash = None

        git = Mock(spec=GitClient)
        git.workspace_dir = Path("/tmp/workspace")
        git.get_current_commit = AsyncMock(return_value="abc123")
        git.get_total_commit_count = AsyncMock(return_value=10)
        git.get_nth_commit_from_head = AsyncMock(return_value="def456")
        git.get_commit_messages = AsyncMock(return_value=["msg1", "msg2"])
        git.get_commit_count = AsyncMock(return_value=2)
        git.get_commit_diff = AsyncMock(return_value="diff content")
        git.fetch_and_reset = AsyncMock()

        config = Mock(spec=Config)
        analysis_config = Mock()
        analysis_config.first_run_lookback_commits = 3
        config.analysis = analysis_config

        repo = Repo(model, git, config)

        with patch.object(repo, "clone_or_update", new_callable=AsyncMock):
            result = await repo.get_diff()

        assert result is not None
        diff, previous_commit, commit_count, commit_messages, is_range_check = result
        assert diff == "diff content"
        assert previous_commit == "def456"
        assert commit_count == 2
        assert commit_messages == ["msg1", "msg2"]
        assert is_range_check is True

    async def test_get_diff_first_check_recent_mode(self):
        """Test get_diff uses recent commits when total commits <= lookback"""
        model = Mock(spec=Repository)
        model.url = "https://github.com/owner/repo.git"
        model.branch = "main"
        model.last_commit_hash = None

        git = Mock(spec=GitClient)
        git.workspace_dir = Path("/tmp/workspace")
        git.get_current_commit = AsyncMock(return_value="abc123")
        git.get_total_commit_count = AsyncMock(return_value=2)
        git.get_recent_commit_hashes = AsyncMock(return_value=["abc123", "def456"])
        git.get_recent_commit_messages = AsyncMock(return_value=["msg1", "msg2"])
        git.get_recent_commit_patches = AsyncMock(return_value="diff content")
        git.fetch_and_reset = AsyncMock()

        config = Mock(spec=Config)
        analysis_config = Mock()
        analysis_config.first_run_lookback_commits = 3
        config.analysis = analysis_config

        repo = Repo(model, git, config)

        with patch.object(repo, "clone_or_update", new_callable=AsyncMock):
            result = await repo.get_diff()

        assert result is not None
        diff, previous_commit, commit_count, commit_messages, is_range_check = result
        assert diff == "diff content"
        assert previous_commit == "def456"
        assert commit_count == 2
        assert commit_messages == ["msg1", "msg2"]
        assert is_range_check is False

    async def test_get_diff_incremental(self):
        """Test get_diff for incremental check"""
        model = Mock(spec=Repository)
        model.url = "https://github.com/owner/repo.git"
        model.branch = "main"
        model.last_commit_hash = "abc123"

        git = Mock(spec=GitClient)
        git.workspace_dir = Path("/tmp/workspace")
        git.get_current_commit = AsyncMock(return_value="def456")
        git.get_commit_messages = AsyncMock(return_value=["msg1"])
        git.get_commit_count = AsyncMock(return_value=1)
        git.get_commit_diff = AsyncMock(return_value="diff content")
        git.fetch_and_reset = AsyncMock()

        config = Mock(spec=Config)

        repo = Repo(model, git, config)
        result = await repo.get_diff()

        assert result is not None
        diff, previous_commit, commit_count, commit_messages, is_range_check = result
        assert diff == "diff content"
        assert previous_commit == "abc123"
        assert commit_count == 1
        assert commit_messages == ["msg1"]
        assert is_range_check is True

    async def test_update(self):
        """Test update saves model changes"""
        model = Mock(spec=Repository)
        model.url = "https://github.com/owner/repo.git"
        model.last_commit_hash = "abc123"
        model.save = AsyncMock()

        git = Mock(spec=GitClient)
        git.workspace_dir = Path("/tmp/workspace")

        config = Mock(spec=Config)

        repo = Repo(model, git, config)

        with patch("progress.contrib.repo.repo.database_connection") as mock_conn:
            mock_conn.return_value.__aenter__ = AsyncMock()
            mock_conn.return_value.__aexit__ = AsyncMock(return_value=None)

            await repo.update("def456")

            assert model.last_commit_hash == "def456"
            model.save.assert_awaited_once()

    async def test_get_commit_messages(self):
        """Test get_commit_messages"""
        model = Mock(spec=Repository)
        model.url = "https://github.com/owner/repo.git"
        model.last_commit_hash = "abc123"

        git = Mock(spec=GitClient)
        git.workspace_dir = Path("/tmp/workspace")
        git.get_commit_messages = AsyncMock(return_value=["msg1", "msg2"])

        config = Mock(spec=Config)

        repo = Repo(model, git, config)
        result = await repo.get_commit_messages("abc123", "def456")

        git.get_commit_messages.assert_called_once_with(
            Path("/tmp/workspace/owner_repo"), "abc123", "def456"
        )
        assert result == ["msg1", "msg2"]

    async def test_clone_includes_tags_flag(self):
        """Test that clone command includes --tags flag"""
        model = Mock(spec=Repository)
        model.url = "https://github.com/owner/repo.git"
        model.branch = "main"
        model.last_commit_hash = None

        git = Mock(spec=GitClient)
        git.workspace_dir = Path("/tmp/workspace")

        config = Mock(spec=Config)
        github_config = Mock()
        github_config.gh_timeout = 300
        config.github = github_config

        repo = Repo(model, git, config, gh_token="test_token")

        with patch.object(repo, "_run_command", new_callable=AsyncMock) as mock_run:
            await repo._run_gh_clone_command("https://github.com/owner/repo.git", "main")

            call_args = mock_run.call_args[0][0]
            assert "--" in call_args
            assert "--tags" in call_args
