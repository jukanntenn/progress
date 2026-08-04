"""E2E golden path 3: third run with changelog increment (spec 15 §2.2.1).

Same cfg, but the second run adds versions to the changelog only; repo and
proposal are no-op (idempotent). Verifies changelog's increment is reflected
correctly while repo/proposal confirm idempotency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from progress.cli.ai.agent import AnalysisResult, TitleSummary
from progress.cli.core import run
from progress.cli.notifications.events import ChangelogEvent, ProposalEvent
from progress.integrations.changelog.config import ChangelogIntegrationConfig, ChangelogItemConfig
from progress.integrations.changelog.models import ChangelogTracker
from progress.integrations.proposal.config import ProposalIntegrationConfig
from progress.integrations.repo.config import RepoIntegrationConfig, RepoItemConfig
from tests.e2e.conftest import _patch_kind_repo_url, _patch_proposal_clone

from .conftest import db_view, override_agent, seed_config

if TYPE_CHECKING:
    from pathlib import Path

_CHANGELOG_INITIAL = """\
# Changelog

## [1.0.0] - 2024-04-01
Initial release.
"""

_CHANGELOG_INCREMENTED = """\
# Changelog

## [2.0.0] - 2024-05-01
Second release.

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
async def test_all_integrations_third_run_no_changes(
    test_cfg: Any,
    workspace: Path,
    httpserver: Any,
    git_helper: Any,
    patch_clone_local: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    repo = git_helper.make_repo(workspace, "owner_repo", initial_files={"README.md": "# hello\n"})
    repo.add_commit("feature", files={"feature.py": "x = 1\n"})
    patch_clone_local(monkeypatch, {"https://github.com/owner/repo.git": repo.bare_path})
    httpserver.expect_request("/vite.md").respond_with_data(_CHANGELOG_INITIAL)
    eips = git_helper.make_repo(workspace, "eips_repo", branch="master", initial_files={"EIPS/eip-1.md": _EIP_DRAFT})
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
    first_event = first.results["changelog"].events[0] if first.results["changelog"].events else None
    first_seen = first_event.version if isinstance(first_event, ChangelogEvent) else None

    httpserver.clear_all_handlers()
    httpserver.expect_request("/vite.md").respond_with_data(_CHANGELOG_INCREMENTED)

    with (
        override_agent(AnalysisResult, response_text='{"summary": "s2", "detail": "d2"}'),
        override_agent(TitleSummary, response_text='{"title": "T2", "summary": "u2"}'),
    ):
        second = await run(test_cfg)
    assert second.exit_code == 0

    cl_result = second.results["changelog"]
    assert cl_result.status == "success"
    new_versions = [e["version"] for e in cl_result.reports[0].payload.get("new_entries", [])]
    assert new_versions == ["2.0.0"]

    changelog_events = [e for e in cl_result.events if isinstance(e, ChangelogEvent)]
    assert len(changelog_events) == 1
    assert changelog_events[0].version == "2.0.0"
    assert first_seen == "1.0.0"

    assert len(second.results["repo"].reports) == 1
    assert second.results["repo"].reports[0].payload.get("status") == "skipped"
    assert len(second.results["proposal"].reports) == 0
    assert not [e for e in second.results["proposal"].events if isinstance(e, ProposalEvent)]

    async with db_view(test_cfg.state_home):
        rows = await ChangelogTracker.all()
        assert rows[0].last_seen_version == "2.0.0"
