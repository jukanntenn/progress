"""E2E golden path 1: all integrations first-run baseline (spec 15 §2.2.1).

One cfg configures repo + changelog + proposal (+ notification + AI). A single
``core.run`` verifies full-stack collaboration: the reports pipeline aggregates
each integration's ReportSections into persisted aggregated reports, AI produces
a unified title/summary, and notifications dispatch the integration-produced
events together (changelog ChangelogEvent + proposal ProposalEvent; repo's
contribution flows through the persisted aggregated report).

This is the first of three "round-robin" golden paths; all three integrations
run their first run here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from progress.cli.ai.agent import AnalysisResult, TitleSummary
from progress.cli.core import run
from progress.cli.notifications.events import ChangelogEvent, ProposalEvent
from progress.db.models.report import Report
from progress.integrations.changelog.config import ChangelogIntegrationConfig, ChangelogItemConfig
from progress.integrations.proposal.config import ProposalIntegrationConfig
from progress.integrations.repo.config import RepoIntegrationConfig, RepoItemConfig
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


@pytest.mark.asyncio
async def test_all_integrations_first_run_baseline(
    test_cfg: Any,
    workspace: Path,
    httpserver: Any,
    git_helper: Any,
    patch_clone_local: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    repo = git_helper.make_repo(
        workspace,
        "owner_repo",
        initial_files={"README.md": "# hello\n"},
    )
    repo.add_commit("feature", files={"feature.py": "x = 1\n"})
    patch_clone_local(monkeypatch, {"https://github.com/owner/repo.git": repo.bare_path})

    httpserver.expect_request("/vite.md").respond_with_data(_CHANGELOG_MD)

    eips = git_helper.make_repo(
        workspace,
        "eips_repo",
        branch="master",
        initial_files={"EIPS/eip-1.md": _EIP_DRAFT},
    )
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
        override_agent(TitleSummary, response_text='{"title": "Unified Baseline Report", "summary": "all green"}'),
    ):
        outcome = await run(test_cfg)

    assert outcome.exit_code == 0
    assert outcome.results["repo"].status == "success"
    assert outcome.results["changelog"].status == "success"
    assert outcome.results["proposal"].status == "success"

    async with db_view(test_cfg.state_home):
        rows = await Report.all()
        report_types = {row.report_type for row in rows}
        assert {"repo_update", "changelog", "proposal"}.issubset(report_types)

    all_events = outcome.all_events()
    assert any(isinstance(e, ChangelogEvent) for e in all_events)
    assert any(isinstance(e, ProposalEvent) for e in all_events)
