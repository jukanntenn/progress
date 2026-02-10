"""GitHub module unit tests"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from progress.github import sanitize_repo_name, GitClient, resolve_repo_url
from progress.enums import Protocol
from progress.repository import RepositoryManager
from progress.errors import CommandException, GitException


# ========== Test Cases ==========


@pytest.mark.parametrize(
    "input_name,expected",
    [
        # Basic format
        ("owner/repo", "owner_repo"),
        # With .git suffix
        ("owner/repo.git", "owner_repo"),
        # Contains dots (dots replaced with underscores)
        ("owner/vue.js", "owner_vue_js"),
        ("owner/next.js", "owner_next_js"),
        ("owner/dot.repo", "owner_dot_repo"),
        # Contains special characters (replaced with underscores, consecutive compressed)
        ("owner/repo;rm -rf /", "owner_repo_rm_-rf"),
        ("owner/repo@test", "owner_repo_test"),
        ("owner/repo:tag", "owner_repo_tag"),
        # Path traversal attack protection
        ("owner/../etc/passwd", "owner_etc_passwd"),
        ("../../etc/passwd", "etc_passwd"),
        # Multiple consecutive slashes
        ("owner///repo", "owner_repo"),
        # Remove leading/trailing underscores
        ("_owner_repo_", "owner_repo"),
        ("__owner__repo__", "owner_repo"),
        # Compress consecutive underscores
        ("owner__repo", "owner_repo"),
        ("owner___repo", "owner_repo"),
        ("owner__repo__test", "owner_repo_test"),
        # Returns default value when only special characters
        ("...", "repo"),
        ("___", "repo"),
        ("///", "repo"),
        # Contains hyphens (hyphens preserved)
        ("owner/my-repo", "owner_my-repo"),
        ("owner/test-repo-name", "owner_test-repo-name"),
        # Mixed case (preserved as-is)
        ("Owner/Repo", "Owner_Repo"),
        ("OWNER/REPO", "OWNER_REPO"),
    ],
)
def test_sanitize_repo_name(input_name, expected):
    """Test: Repository name sanitization"""
    assert sanitize_repo_name(input_name) == expected


def test_git_client_initialization():
    """Test: GitClient initialization"""
    client = GitClient("/tmp/test_workspace")
    assert client.workspace_dir.name == "test_workspace"


def test_git_client_get_current_commit_with_gitpython(monkeypatch):
    from types import SimpleNamespace
    mock_repo = SimpleNamespace(
        head=SimpleNamespace(
            commit=SimpleNamespace(hexsha="abc123def456")
        )
    )
    def fake_repo_open(path):
        return mock_repo
    monkeypatch.setattr("git.Repo", fake_repo_open)
    client = GitClient("/tmp/test_workspace")
    commit = client.get_current_commit(Path("/tmp/test_workspace/test_repo"))
    assert commit == "abc123def456"


def test_git_client_get_previous_commit_with_gitpython(monkeypatch):
    from types import SimpleNamespace
    mock_commit = SimpleNamespace(hexsha="def456")
    mock_repo = SimpleNamespace(
        head=SimpleNamespace(
            commit=SimpleNamespace(
                hexsha="abc123",
                parents=[mock_commit]
            )
        )
    )
    monkeypatch.setattr("git.Repo", lambda p: mock_repo)
    client = GitClient("/tmp/test_workspace")
    assert client.get_previous_commit(Path("/tmp/test_workspace/test_repo")) == "def456"


def test_git_client_get_previous_commit_no_parent_with_gitpython(monkeypatch):
    from types import SimpleNamespace
    mock_repo = SimpleNamespace(
        head=SimpleNamespace(
            commit=SimpleNamespace(
                hexsha="abc123",
                parents=[]
            )
        )
    )
    monkeypatch.setattr("git.Repo", lambda p: mock_repo)
    client = GitClient("/tmp/test_workspace")
    assert client.get_previous_commit(Path("/tmp/test_workspace/test_repo")) is None


def test_git_client_get_commit_messages_with_gitpython(monkeypatch):
    from types import SimpleNamespace
    mock_commit1 = SimpleNamespace(message="First commit\n\nDetails here")
    mock_commit2 = SimpleNamespace(message="Second commit")

    def mock_commit_fn(sha):
        if sha == "old123":
            return SimpleNamespace(hexsha="old123")
        return SimpleNamespace(hexsha="abc123")

    mock_repo = SimpleNamespace(
        head=SimpleNamespace(commit=SimpleNamespace(hexsha="abc123")),
        commit=mock_commit_fn,
        iter_commits=lambda rev_range: [mock_commit2, mock_commit1]
    )
    monkeypatch.setattr("git.Repo", lambda p: mock_repo)
    client = GitClient("/tmp/test_workspace")
    messages = client.get_commit_messages(Path("/tmp/test_workspace"), "old123", "abc123")
    assert len(messages) == 2
    assert messages[0] == "Second commit"
    assert messages[1] == "First commit\n\nDetails here"


def test_git_client_get_commit_count_with_gitpython(monkeypatch):
    from types import SimpleNamespace

    def mock_commit_fn(sha):
        if sha == "old123":
            return SimpleNamespace(hexsha="old123")
        return SimpleNamespace(hexsha="abc123")

    mock_repo = SimpleNamespace(
        head=SimpleNamespace(commit=SimpleNamespace(hexsha="abc123")),
        commit=mock_commit_fn,
        iter_commits=lambda rev_range: range(5)
    )
    monkeypatch.setattr("git.Repo", lambda p: mock_repo)
    client = GitClient("/tmp/test_workspace")
    count = client.get_commit_count(Path("/tmp/test_workspace"), "old123", "abc123")
    assert count == 5


def test_git_client_get_commit_count_no_old_commit_with_gitpython(monkeypatch):
    from types import SimpleNamespace
    mock_repo = SimpleNamespace(
        head=SimpleNamespace(commit=SimpleNamespace(hexsha="abc123"))
    )
    monkeypatch.setattr("git.Repo", lambda p: mock_repo)
    client = GitClient("/tmp/test_workspace")
    count = client.get_commit_count(Path("/tmp/test_workspace"), None, "abc123")
    assert count == 1


def test_git_client_get_commit_diff_with_gitpython(monkeypatch):
    from types import SimpleNamespace
    expected_diff = "@@ file1.py @@\n+new line\n-old line"
    mock_diff = SimpleNamespace(diff=expected_diff)
    mock_repo = SimpleNamespace(
        commit=SimpleNamespace(hexsha="abc123"),
        head=SimpleNamespace(
            commit=SimpleNamespace(
                hexsha="abc123",
                parents=[SimpleNamespace(diff=lambda *a, **k: [mock_diff])]
            )
        )
    )

    def fake_repo_diff(old, new, **kwargs):
        return [mock_diff]

    mock_repo.diff = fake_repo_diff
    monkeypatch.setattr("git.Repo", lambda p: mock_repo)
    client = GitClient("/tmp/test_workspace")
    diff = client.get_commit_diff(Path("/tmp/test_workspace"), None, "abc123")
    assert diff == expected_diff


def test_git_client_fetch_and_reset_with_gitpython(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock

    mock_remote = Mock()
    mock_head = SimpleNamespace(reset=Mock())
    mock_repo = SimpleNamespace(
        remotes=SimpleNamespace(origin=mock_remote),
        head=mock_head
    )
    monkeypatch.setattr("git.Repo", lambda p: mock_repo)

    client = GitClient(str(tmp_path))
    monkeypatch.setattr(client, "_cleanup_git_locks", Mock())

    client.fetch_and_reset(tmp_path / "test_repo", "main")
    mock_remote.fetch.assert_called_once()
    mock_head.reset.assert_called_once()


@pytest.mark.parametrize(
    "repo_url,protocol,expected_full_url,expected_short_url",
    [
        # Short format + HTTPS
        ("vitejs/vite", "https", "https://github.com/vitejs/vite.git", "vitejs/vite"),
        # Short format + SSH
        ("vitejs/vite", "ssh", "git@github.com:vitejs/vite.git", "vitejs/vite"),
        # HTTPS format
        (
            "https://github.com/vuejs/core.git",
            "https",
            "https://github.com/vuejs/core.git",
            "vuejs/core",
        ),
        # SSH format
        (
            "git@github.com:facebook/react.git",
            "ssh",
            "git@github.com:facebook/react.git",
            "facebook/react",
        ),
    ],
)
def test_resolve_repo_url(repo_url, protocol, expected_full_url, expected_short_url):
    """Test: Repository URL resolution"""
    full_url, short_url = resolve_repo_url(repo_url, protocol)
    assert full_url == expected_full_url
    assert short_url == expected_short_url


def test_resolve_repo_url_invalid_format():
    """Test: Invalid repository URL format raises exception"""
    with pytest.raises(ValueError, match="Invalid repository URL format"):
        resolve_repo_url("invalid-url-format", "https")


def test_git_client_recent_commit_helpers(monkeypatch):
    """Test: GitClient recent commit helper parsing"""
    client = GitClient("/tmp/test_workspace")

    def fake_run_git_command(args, repo_path):
        if args[:3] == ["rev-list", "--count", "HEAD"]:
            return "4\n"
        if args[:2] == ["log", "-3"] and "--format=%H" in args:
            return "h1\nh2\nh3\n"
        if args[:2] == ["log", "-2"] and "--pretty=format:%B%n%x00" in args:
            return "m1\n\x00m2\n\x00"
        if args[:2] == ["log", "-2"] and "-p" in args:
            return "diff --git a/a b/a\n"
        raise AssertionError(f"Unexpected args: {args}")

    monkeypatch.setattr(client, "_run_git_command", fake_run_git_command)
    repo_path = Path("/tmp/repo")

    assert client.get_total_commit_count(repo_path) == 4
    assert client.get_recent_commit_hashes(repo_path, 3) == ["h1", "h2", "h3"]
    assert client.get_recent_commit_messages(repo_path, 2) == ["m1", "m2"]
    assert client.get_recent_commit_patches(repo_path, 2) == "diff --git a/a b/a\n"


def test_repository_manager_first_check_total_commits_le_1(monkeypatch):
    """Test: First check skips when repo has <= 1 commit"""

    class FakeGitClient:
        workspace_dir = Path("/tmp")

        def get_current_commit(self, repo_path):
            return "c" * 40

        def get_total_commit_count(self, repo_path):
            return 1

    class FakeAnalyzer:
        def analyze_diff(self, repo_name, branch, diff, commit_messages):
            raise AssertionError("Should not analyze when total commits <= 1")

    repo = SimpleNamespace(
        id=1,
        name="test",
        url="owner/repo",
        branch="main",
        last_commit_hash=None,
    )
    cfg = SimpleNamespace(
        analysis=SimpleNamespace(first_run_lookback_commits=3),
        github=SimpleNamespace(
            gh_timeout=300, gh_token=None, proxy=None, protocol="https", git_timeout=300
        ),
    )
    manager = RepositoryManager(FakeAnalyzer(), None, cfg)

    # Replace manager.git with FakeGitClient
    manager.git = FakeGitClient()

    # Mock Repo.clone_or_update to avoid actually running gh command
    with monkeypatch.context() as m:
        def fake_clone_or_update(self):
            pass

        m.setattr("progress.repo.Repo.clone_or_update", fake_clone_or_update)
        assert manager.check(repo) is None


def test_repository_manager_first_check_uses_range_when_history_sufficient(monkeypatch):
    """Test: First check uses old..new range when total commits > lookback"""

    class FakeGitClient:
        workspace_dir = Path("/tmp")

        def get_current_commit(self, repo_path):
            return "n" * 40

        def get_total_commit_count(self, repo_path):
            return 10

        def get_nth_commit_from_head(self, repo_path, n):
            assert n == 3
            return "b" * 40

        def get_commit_messages(self, repo_path, old_commit, new_commit):
            assert old_commit == "b" * 40
            assert new_commit == "n" * 40
            return ["m"]

        def get_commit_count(self, repo_path, old_commit, new_commit):
            return 3

        def get_commit_diff(self, repo_path, old_commit, new_commit):
            return "diff"

    class FakeAnalyzer:
        def analyze_diff(self, repo_name, branch, diff, commit_messages):
            assert diff == "diff"
            assert commit_messages == ["m"]
            return ("report", "detail", False, 4, 4)

    repo = SimpleNamespace(
        id=1,
        name="test",
        url="owner/repo",
        branch="main",
        last_commit_hash=None,
    )
    cfg = SimpleNamespace(
        analysis=SimpleNamespace(first_run_lookback_commits=3),
        github=SimpleNamespace(
            gh_timeout=300, gh_token=None, proxy=None, protocol="https", git_timeout=300
        ),
    )
    manager = RepositoryManager(FakeAnalyzer(), None, cfg)

    # Replace manager.git with FakeGitClient
    manager.git = FakeGitClient()

    # Mock Repo.clone_or_update to avoid actually running gh command
    with monkeypatch.context() as m:
        def fake_clone_or_update(self):
            pass

        def fake_update(self, current_commit):
            pass

        m.setattr("progress.repo.Repo.clone_or_update", fake_clone_or_update)
        m.setattr("progress.repo.Repo.update", fake_update)
        report = manager.check(repo)
        assert report is not None
        assert report.previous_commit == "b" * 40
        assert report.current_commit == "n" * 40
        assert report.commit_count == 3


def test_repository_manager_first_check_uses_recent_commits_when_history_insufficient(
    monkeypatch,
):
    """Test: First check analyzes all existing commits when total <= lookback"""

    class FakeGitClient:
        workspace_dir = Path("/tmp")

        def get_current_commit(self, repo_path):
            return "n" * 40

        def get_total_commit_count(self, repo_path):
            return 2

        def get_recent_commit_hashes(self, repo_path, max_count):
            assert max_count == 2
            return ["n" * 40, "o" * 40]

        def get_recent_commit_messages(self, repo_path, max_count):
            assert max_count == 2
            return ["m1", "m2"]

        def get_recent_commit_patches(self, repo_path, max_count):
            assert max_count == 2
            return "patches"

    class FakeAnalyzer:
        def analyze_diff(self, repo_name, branch, diff, commit_messages):
            assert diff == "patches"
            assert commit_messages == ["m1", "m2"]
            return ("report", "detail", False, 7, 7)

    repo = SimpleNamespace(
        id=1,
        name="test",
        url="owner/repo",
        branch="main",
        last_commit_hash=None,
    )
    cfg = SimpleNamespace(
        analysis=SimpleNamespace(first_run_lookback_commits=3),
        github=SimpleNamespace(
            gh_timeout=300, gh_token=None, proxy=None, protocol="https", git_timeout=300
        ),
    )
    manager = RepositoryManager(FakeAnalyzer(), None, cfg)

    # Replace manager.git with FakeGitClient
    manager.git = FakeGitClient()

    # Mock Repo.clone_or_update to avoid actually running gh command
    with monkeypatch.context() as m:
        def fake_clone_or_update(self):
            pass

        def fake_update(self, current_commit):
            pass

        m.setattr("progress.repo.Repo.clone_or_update", fake_clone_or_update)
        m.setattr("progress.repo.Repo.update", fake_update)
        report = manager.check(repo)
        assert report is not None
        assert report.previous_commit == "o" * 40
        assert report.current_commit == "n" * 40
        assert report.commit_count == 2


class TestParseRepoName:
    """Test parse_repo_name function."""

    @pytest.mark.parametrize(
        "input_url,expected",
        [
            # Short format (owner/repo)
            ("OpenListTeam/OpenList", "OpenListTeam/OpenList"),
            ("vitejs/vite", "vitejs/vite"),
            # Short format with .git suffix
            ("OpenListTeam/OpenList.git", "OpenListTeam/OpenList"),
            ("vitejs/vite.git", "vitejs/vite"),
            # HTTPS format
            ("https://github.com/OpenListTeam/OpenList.git", "OpenListTeam/OpenList"),
            ("https://github.com/vitejs/vite", "vitejs/vite"),
            # SSH format
            ("git@github.com:OpenListTeam/OpenList.git", "OpenListTeam/OpenList"),
            ("git@github.com:vitejs/vite", "vitejs/vite"),
            # Repo names ending with characters from .git set
            # Regression test for rstrip bug where 't' in "OpenList" was removed
            ("owner/test", "owner/test"),
            ("owner/git", "owner/git"),
            # Edge cases with multiple dots in name (not suffix)
            ("owner/vue.js", "owner/vue.js"),
        ],
    )
    def test_parse_repo_name(self, input_url, expected):
        """Test parse_repo_name extracts owner/repo correctly."""
        from progress.consts import parse_repo_name

        result = parse_repo_name(input_url)
        assert result == expected, f"Failed for {input_url}: got {result}, expected {expected}"

    def test_parse_repo_name_openlist_regression(self):
        """Regression test for OpenList -> OpenLis bug."""
        from progress.consts import parse_repo_name

        # Test the specific case that was failing
        result = parse_repo_name("OpenListTeam/OpenList")
        assert result == "OpenListTeam/OpenList", f"Got {result!r}"

        # Test with .git suffix
        result = parse_repo_name("OpenListTeam/OpenList.git")
        assert result == "OpenListTeam/OpenList", f"Got {result!r}"

        # Test full HTTPS URL
        result = parse_repo_name("https://github.com/OpenListTeam/OpenList.git")
        assert result == "OpenListTeam/OpenList", f"Got {result!r}"
