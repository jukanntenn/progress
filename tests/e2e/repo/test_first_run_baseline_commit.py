"""E2E: repo integration first-run baseline (spec 15 §2.5).

Single repo first check: clone (real git, local file:// remote), lookback, a
``repo_update`` report is produced, and the commit checkpoint advances to HEAD.
Verifies the clone real-path + Report persistence + checkpoint contract that
only a full ``core.run`` exercises.
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
async def test_first_run_baseline_commit(
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

    outcome = await run(test_cfg)
    assert outcome.exit_code == 0

    repo_result = outcome.results.get("repo")
    assert repo_result is not None
    assert repo_result.status == "success"
    assert len(repo_result.reports) == 1

    async with db_view(test_cfg.state_home):
        rows = await Report.all()
        report_types = {row.report_type for row in rows}
        assert "repo_update" in report_types
        repo_rows = await Repository.all()
        assert len(repo_rows) == 1
        assert repo_rows[0].last_commit_hash == repo.head
