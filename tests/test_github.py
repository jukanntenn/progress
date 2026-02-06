"""GitHub module unit tests"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from progress.github import sanitize_repo_name, GitClient, resolve_repo_url
from progress.github import gh_api_get_readme, gh_repo_list
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


def test_gh_repo_list_parses_json(monkeypatch):
    def fake_run_command(cmd, timeout=None, env=None, **kwargs):
        assert cmd[:3] == ["gh", "repo", "list"]
        return """[{"nameWithOwner":"o/r","description":"d","createdAt":"2024-01-01T00:00:00Z","updatedAt":"2024-01-02T00:00:00Z"}]"""

    monkeypatch.setattr("progress.github.run_command", fake_run_command)
    repos = gh_repo_list("o")
    assert repos[0]["nameWithOwner"] == "o/r"


def test_gh_repo_list_invalid_owner_returns_empty(monkeypatch):
    def fake_run_command(*args, **kwargs):
        raise CommandException("Could not resolve to a User")

    monkeypatch.setattr("progress.github.run_command", fake_run_command)
    assert gh_repo_list("does-not-exist") == []


def test_gh_repo_list_other_errors_raise(monkeypatch):
    def fake_run_command(*args, **kwargs):
        raise CommandException("Some unexpected error")

    monkeypatch.setattr("progress.github.run_command", fake_run_command)
    with pytest.raises(GitException):
        gh_repo_list("o")


def test_gh_api_get_readme_decodes_base64(monkeypatch):
    def fake_run_command(cmd, timeout=None, env=None, **kwargs):
        assert cmd[:2] == ["gh", "api"]
        return '{"content":"SGVsbG8=","encoding":"base64"}'

    monkeypatch.setattr("progress.github.run_command", fake_run_command)
    assert gh_api_get_readme("o", "r") == "Hello"


def test_gh_api_get_readme_404_returns_none(monkeypatch):
    def fake_run_command(*args, **kwargs):
        raise CommandException("404 Not Found")

    monkeypatch.setattr("progress.github.run_command", fake_run_command)
    assert gh_api_get_readme("o", "r") is None


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
