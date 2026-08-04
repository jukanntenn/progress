"""E2E: repo integration release tracking via GitHub API (spec 15 §2.5).

Configure release tracking (needs a GitHub token so the gidgethub client is
built). aioresponses mocks the GitHub Releases API; first run reports only the
single newest release and advances the release checkpoint. Verifies the release
path (gidgethub + aioresponses) and the "first run only 1" business rule.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pydantic import SecretStr
import pytest

from progress.cli.core import run
from progress.config.root import CoreConfig, GitHubConfig
from progress.integrations.repo.config import RepoIntegrationConfig, RepoItemConfig
from progress.integrations.repo.models import Repository
from tests.e2e.conftest import db_view, seed_config

if TYPE_CHECKING:
    from pathlib import Path

_RELEASES_PAYLOAD = [
    {
        "id": 2,
        "tag_name": "v2.0.0",
        "name": "Second Release",
        "body": "Second release notes",
        "published_at": "2024-06-01T00:00:00Z",
        "prerelease": False,
        "draft": False,
        "html_url": "https://github.com/owner/repo/releases/tag/v2.0.0",
    },
    {
        "id": 1,
        "tag_name": "v1.0.0",
        "name": "First Release",
        "body": "First release notes",
        "published_at": "2024-01-01T00:00:00Z",
        "prerelease": False,
        "draft": False,
        "html_url": "https://github.com/owner/repo/releases/tag/v1.0.0",
    },
]

_REF_PAYLOAD = {
    "ref": "refs/tags/v2.0.0",
    "object": {"sha": "abc123commit", "type": "commit", "url": ""},
}


@pytest.mark.asyncio
async def test_release_tracking_with_github_api(
    tmp_state_home: str,
    workspace: Path,
    git_helper: Any,
    patch_clone_local: Any,
    monkeypatch: pytest.MonkeyPatch,
    gh_mock: Any,
) -> None:
    repo = git_helper.make_repo(
        workspace,
        "owner_repo",
        initial_files={"README.md": "# hello\n"},
    )
    patch_clone_local(monkeypatch, {"https://github.com/owner/repo.git": repo.bare_path})

    releases_url = re.compile(r"^https://api\.github\.com/repos/owner/repo/releases")
    gh_mock.get(releases_url, payload=_RELEASES_PAYLOAD, repeat=True)
    gh_mock.get(
        re.compile(r"^https://api\.github\.com/repos/owner/repo/git/refs/tags/v2\.0\.0$"),
        payload=_REF_PAYLOAD,
        repeat=True,
    )

    repo_cfg = RepoIntegrationConfig(
        repos=[RepoItemConfig(url="owner/repo", branch="main", enabled=True)],
        owners=[],
        first_run_lookback_commits=1,
    )
    cfg = CoreConfig(
        state_home=tmp_state_home,
        github=GitHubConfig(gh_token=SecretStr("fake-token")),
    )
    async with seed_config(tmp_state_home, "repo", repo_cfg):
        pass

    outcome = await run(cfg)
    assert outcome.exit_code == 0

    repo_result = outcome.results["repo"]
    assert repo_result.status == "success"

    async with db_view(tmp_state_home):
        rows = await Repository.all()
        assert len(rows) == 1
        row = rows[0]
        assert row.last_release_tag == "v2.0.0"
        assert row.last_release_check_time is not None
