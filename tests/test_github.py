"""GitHub module unit tests"""

import pytest

from progress.github import sanitize_repo_name, GitClient, GitHubClient
from progress.enums import Protocol


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


def test_github_client_initialization():
    """Test: GitHubClient initialization"""
    client = GitHubClient(
        workspace_dir="/tmp/test_workspace",
        gh_token="test_token",
        protocol="https",
        proxy="http://proxy:8080",
    )
    assert client.workspace_dir.name == "test_workspace"
    assert client.gh_token == "test_token"
    assert client.protocol == Protocol.HTTPS
    assert client.proxy == "http://proxy:8080"
    assert client.git is not None  # Verify GitClient instance is created


def test_github_client_has_git_client_methods():
    """Test: GitHubClient proxies GitClient methods"""
    client = GitHubClient()

    # Verify GitHubClient has GitClient methods
    assert hasattr(client, "get_current_commit")
    assert hasattr(client, "get_previous_commit")
    assert hasattr(client, "get_commit_diff")
    assert hasattr(client, "get_commit_messages")
    assert hasattr(client, "get_commit_count")
    assert hasattr(client, "get_nth_commit_from_head")


def test_github_client_without_proxy():
    """Test: GitHubClient without proxy configuration"""
    client = GitHubClient(gh_token="test_token", protocol="https")
    assert client.proxy is None
    assert client.gh_token == "test_token"


def test_github_client_default_protocol():
    """Test: GitHubClient default protocol is https"""
    client = GitHubClient()
    assert client.protocol == Protocol.HTTPS


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
    full_url, short_url = GitHubClient._resolve_repo_url(repo_url, protocol)
    assert full_url == expected_full_url
    assert short_url == expected_short_url


def test_resolve_repo_url_invalid_format():
    """Test: Invalid repository URL format raises exception"""
    with pytest.raises(ValueError, match="Invalid repository URL format"):
        GitHubClient._resolve_repo_url("invalid-url-format", "https")
