"""E2E: repo integration incremental commit diff (spec 15 §2.5).

Second run pushes a new commit: diff analysis runs, commit_count=1, the commit
checkpoint advances past the first-run HEAD. Verifies the incremental diff path
on the cross-run state machine that only a full ``core.run`` exercises.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from progress.cli.core import run
from progress.db.models.report import Report
from progress.integrations.repo.config import RepoIntegrationConfig, RepoItemConfig
from progress.integrations.repo.models import Repository
from tests.e2e.conftest import db_view, seed_config

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_incremental_commit_diff(
    test_cfg: Any,
    workspace: Path,
    git_helper: Any,
    patch_clone_local: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = git_helper.make_repo(
        workspace,
        "owner_repo",
        initial_files={"README.md": "# hello\n"},
    )
    repo.add_commit("Add feature", files={"feature.py": "print('hi')\n"})
    patch_clone_local(monkeypatch, {"https://github.com/owner/repo.git": repo.bare_path})

    repo_cfg = RepoIntegrationConfig(
        repos=[RepoItemConfig(url="owner/repo", branch="main", enabled=True)],
        first_run_lookback_commits=3,
    )
    async with seed_config(test_cfg.state_home, "repo", repo_cfg):
        pass

    first = await run(test_cfg)
    assert first.exit_code == 0
    first_head = repo.head

    repo.add_commit("Add second feature", files={"feature2.py": "x = 1\n"})

    second = await run(test_cfg)
    assert second.exit_code == 0
    repo_result = second.results["repo"]
    assert repo_result.status == "success"
    assert len(repo_result.reports) == 1

    async with db_view(test_cfg.state_home):
        rows = await Report.all().order_by("created_at")
        assert len(rows) >= 2
        repo_rows = await Repository.all()
        assert len(repo_rows) == 1
        assert repo_rows[0].last_commit_hash == repo.head
        assert repo_rows[0].last_commit_hash != first_head
