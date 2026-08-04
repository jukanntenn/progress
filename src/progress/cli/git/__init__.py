"""Git / GitHub clients used by the CLI tracking pipeline (spec 07).

Sub-modules:
- :mod:`progress.cli.git.url`    — URL parsing (regex bug fix per spec 07).
- :mod:`progress.cli.git.local`  — local git via ``asyncio.create_subprocess_exec``.
- :mod:`progress.cli.git.github` — gidgethub aiohttp wrapper.

This package is in ``cli/`` (not shared) because git operations are only
triggered by the CLI tracking run; the API never shells out to git.
"""

from progress.cli.git.github import (
    GitHubClient,
    Release,
    RepositoryInfo,
    create_github_client,
)
from progress.cli.git.local import (
    GIT_BINARY,
    GIT_TIMEOUT,
    CommitMessage,
    cleanup_git_locks,
    clone,
    ensure_object,
    fetch,
    get_commit_count,
    get_commit_diff_range,
    get_commit_hash_at,
    get_commit_messages,
    get_default_branch,
    get_diff,
    get_diff_name_status,
    get_file_creation_time,
    get_file_diff,
    get_first_n_commits,
    get_head_commit,
    get_log,
    get_parent_commit,
    get_recent_n_commit_hashes,
    get_total_commit_count,
    is_shallow_repository,
    reset_hard,
    unshallow,
)
from progress.cli.git.url import (
    RepoRef,
    build_authenticated_clone_url,
    build_clone_url,
    is_github_url,
    parse_repo_url,
)

__all__ = [
    "GIT_BINARY",
    "GIT_TIMEOUT",
    "CommitMessage",
    "GitHubClient",
    "Release",
    "RepoRef",
    "RepositoryInfo",
    "build_authenticated_clone_url",
    "build_clone_url",
    "cleanup_git_locks",
    "clone",
    "create_github_client",
    "ensure_object",
    "fetch",
    "get_commit_count",
    "get_commit_diff_range",
    "get_commit_hash_at",
    "get_commit_messages",
    "get_default_branch",
    "get_diff",
    "get_diff_name_status",
    "get_file_creation_time",
    "get_file_diff",
    "get_first_n_commits",
    "get_head_commit",
    "get_log",
    "get_parent_commit",
    "get_recent_n_commit_hashes",
    "get_total_commit_count",
    "is_github_url",
    "is_shallow_repository",
    "parse_repo_url",
    "reset_hard",
    "unshallow",
]
