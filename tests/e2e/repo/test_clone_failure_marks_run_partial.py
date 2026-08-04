"""E2E: repo integration clone failure → run partial (spec 15 §2.5).

A clone URL with no mock mapping raises FileNotFoundError inside the faked
``clone_or_fetch``; ``core.run`` aggregates it into ``outcome.errors`` and the
process exits 1, with the repo result status partial/failed. Verifies the error
aggregation contract (spec 06 partial/failed) at the ``core.run`` layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from progress.cli.core import run
from progress.integrations.repo.config import RepoIntegrationConfig, RepoItemConfig
from tests.e2e.conftest import seed_config

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_clone_failure_marks_run_partial(
    test_cfg: Any,
    workspace: Path,
    git_helper: Any,
    patch_clone_local: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git_helper.make_repo(workspace, "owner_repo")
    patch_clone_local(monkeypatch, {})

    repo_cfg = RepoIntegrationConfig(
        repos=[RepoItemConfig(url="owner/repo", branch="main", enabled=True)],
        first_run_lookback_commits=3,
    )
    async with seed_config(test_cfg.state_home, "repo", repo_cfg):
        pass

    outcome = await run(test_cfg)
    assert outcome.exit_code == 1
    assert outcome.errors
    repo_result = outcome.results.get("repo")
    assert repo_result is not None
    assert repo_result.status in {"partial", "failed"}
