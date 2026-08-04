"""E2E golden path 2: second run with repo increment (spec 15 §2.2.1).

Same cfg as golden path 1, but the second run pushes a new commit to repo only;
changelog and proposal are no-op. Verifies that repo's report and the no-op
states mix correctly in the persisted reports, the commit checkpoint advances
only for repo, and notifications dispatch only repo's contribution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from progress.cli.ai.agent import AnalysisResult, TitleSummary
from progress.cli.core import run
from progress.cli.notifications.events import ChangelogEvent, ProposalEvent
from progress.integrations.changelog.config import ChangelogIntegrationConfig, ChangelogItemConfig
from progress.integrations.proposal.config import ProposalIntegrationConfig
from progress.integrations.repo.config import RepoIntegrationConfig, RepoItemConfig
from progress.integrations.repo.models import Repository
from tests.e2e.conftest import _patch_kind_repo_url, _patch_proposal_clone

from .conftest import db_view, override_agent, seed_config

if TYPE_CHECKING:
    from pathlib import Path

_CHANGELOG_MD = """\
# Changelog

## [1.0.0] - 2024-04-01
Initial release.
"""

_EIP_DRAFT = """\
---
eip: 1
title: First EIP
status: Draft
type: Standards Track
category: Core
---

# First EIP

Body.
"""


async def _seed_and_run_first(
    test_cfg: Any,
    workspace: Path,
    httpserver: Any,
    git_helper: Any,
    patch_clone_local: Any,
    monkeypatch: pytest.MonkeyPatch,
    repo: Any,
    eips: Any,
) -> Any:

    patch_clone_local(monkeypatch, {"https://github.com/owner/repo.git": repo.bare_path})
    httpserver.expect_request("/vite.md").respond_with_data(_CHANGELOG_MD)
    _patch_kind_repo_url(monkeypatch, "eip", eips.bare_path)
    _patch_proposal_clone(monkeypatch, eips.bare_path, "master")

    async with (
        seed_config(test_cfg.state_home, "repo", RepoIntegrationConfig(repos=[RepoItemConfig(url="owner/repo")])),
        seed_config(
            test_cfg.state_home,
            "changelog",
            ChangelogIntegrationConfig(
                trackers=[ChangelogItemConfig(name="Vite", url=httpserver.url_for("/vite.md"))],
            ),
        ),
        seed_config(test_cfg.state_home, "proposal", ProposalIntegrationConfig(trackers=["eip"])),
    ):
        pass

    with (
        override_agent(AnalysisResult, response_text='{"summary": "s", "detail": "d"}'),
        override_agent(TitleSummary, response_text='{"title": "T", "summary": "u"}'),
    ):
        first = await run(test_cfg)
    assert first.exit_code == 0
    return first


@pytest.mark.asyncio
async def test_all_integrations_second_run_with_increments(
    test_cfg: Any,
    workspace: Path,
    httpserver: Any,
    git_helper: Any,
    patch_clone_local: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = git_helper.make_repo(workspace, "owner_repo", initial_files={"README.md": "# hello\n"})
    repo.add_commit("feature", files={"feature.py": "x = 1\n"})
    first_head = repo.head
    eips = git_helper.make_repo(workspace, "eips_repo", branch="master", initial_files={"EIPS/eip-1.md": _EIP_DRAFT})

    await _seed_and_run_first(test_cfg, workspace, httpserver, git_helper, patch_clone_local, monkeypatch, repo, eips)

    repo.add_commit("second feature", files={"feature2.py": "y = 2\n"})

    with (
        override_agent(AnalysisResult, response_text='{"summary": "s2", "detail": "d2"}'),
        override_agent(TitleSummary, response_text='{"title": "T2", "summary": "u2"}'),
    ):
        second = await run(test_cfg)
    assert second.exit_code == 0

    assert second.results["repo"].status == "success"
    assert len(second.results["repo"].reports) == 1
    assert len(second.results["changelog"].reports) == 0
    assert len(second.results["proposal"].reports) == 0

    changelog_events = [e for e in second.results["changelog"].events if isinstance(e, ChangelogEvent)]
    proposal_events = [e for e in second.results["proposal"].events if isinstance(e, ProposalEvent)]
    assert changelog_events == []
    assert proposal_events == []

    async with db_view(test_cfg.state_home):
        rows = await Repository.all()
        assert len(rows) == 1
        assert rows[0].last_commit_hash == repo.head
        assert rows[0].last_commit_hash != first_head
