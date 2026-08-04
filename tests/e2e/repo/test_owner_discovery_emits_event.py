"""E2E: repo integration owner discovery emits DiscoveredRepoEvent (spec 15 §2.5).

Configure an owner; aioresponses mocks ``/orgs/{owner}/repos`` (first run → only
the single newest repo) and the candidate's README. Verifies that a
DiscoveredRepoEvent is emitted into ``outcome.events``, and crucially that the
discovered repo is **NOT** inserted into the Repository table (spec repo §7.3).
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import SecretStr
import pytest

from progress.cli.core import run
from progress.cli.notifications.events import DiscoveredRepoEvent
from progress.config.root import CoreConfig, GitHubConfig
from progress.integrations.repo.config import OwnerItemConfig, RepoIntegrationConfig
from progress.integrations.repo.models import GitHubOwner, Repository
from tests.e2e.conftest import db_view, seed_config

_OWNER_REPOS_PAYLOAD = [
    {
        "id": 1,
        "name": "older-repo",
        "full_name": "vitejs/older-repo",
        "owner": {"login": "vitejs"},
        "default_branch": "main",
        "description": "Older repo",
        "html_url": "https://github.com/vitejs/older-repo",
        "created_at": "2023-01-01T00:00:00Z",
        "fork": False,
        "archived": False,
    },
    {
        "id": 2,
        "name": "newer-repo",
        "full_name": "vitejs/newer-repo",
        "owner": {"login": "vitejs"},
        "default_branch": "main",
        "description": "Newer repo",
        "html_url": "https://github.com/vitejs/newer-repo",
        "created_at": "2024-06-01T00:00:00Z",
        "fork": False,
        "archived": False,
    },
]


@pytest.mark.asyncio
async def test_owner_discovery_emits_event(
    tmp_state_home: str,
    monkeypatch: pytest.MonkeyPatch,
    gh_mock: Any,
) -> None:
    gh_mock.get(
        re.compile(r"^https://api\.github\.com/orgs/vitejs/repos"),
        payload=_OWNER_REPOS_PAYLOAD,
        repeat=True,
    )
    gh_mock.get(
        re.compile(r"^https://api\.github\.com/repos/vitejs/newer-repo/readme$"),
        payload='"# Newer repo\n\nA great project."',
        repeat=True,
    )

    repo_cfg = RepoIntegrationConfig(
        repos=[],
        owners=[OwnerItemConfig(type="organization", name="vitejs", enabled=True)],
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
    discovered = [e for e in repo_result.events if isinstance(e, DiscoveredRepoEvent)]
    assert len(discovered) == 1
    assert discovered[0].name == "vitejs/newer-repo"

    async with db_view(tmp_state_home):
        repo_rows = await Repository.all()
        assert len(repo_rows) == 0
        owners = await GitHubOwner.all()
        assert len(owners) == 1
        assert owners[0].last_tracked_repo is not None
