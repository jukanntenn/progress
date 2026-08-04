"""Component tests for the proposal integration tracker (spec proposal §5-8, 11-12, 15).

Covers the main flow:
- setup (no/with token)
- sync (upsert + CASCADE delete on kind removal)
- first-run check (parse all + populate snapshot + only 1 report for newest)
- incremental check (git diff name-status, moved detection, changed/deleted handling)
- RFC PR title resolution (success / fallback / no client)
- snapshot vs notify separation (Draft→Review: snapshot updated, no notify)
- ProposalEvent emission only for notifiable reports
- AI failure fallback (empty summary/detail, tracking not blocked)

Uses real local git via the conftest git_helper fixture; the proposal tracker
is wired to clone from a local file:// path via monkeypatching the repo URL
resolver. AI is mocked via monkeypatching ``run_extraction``.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from unittest.mock import AsyncMock

import aiohttp
from pydantic import SecretStr
import pytest

from progress.cli.ai import AnalysisResult
from progress.cli.git import GitHubClient
from progress.config.root import CoreConfig, GitHubConfig
from progress.db import close_db, init_db, set_config
from progress.errors import ProgressException
from progress.integrations.base import Components
from progress.integrations.proposal.config import ProposalIntegrationConfig
from progress.integrations.proposal.models import Proposal, ProposalTrackerState
import progress.integrations.proposal.tracker as tracker_module
from progress.integrations.proposal.tracker import (
    _KIND_CONFIGS,
    ProposalIntegration,
    ProposalKindConfig,
    _detect_moves,
    _filter_files,
)


@pytest.fixture
async def db(tmp_state_home: str):
    await init_db(tmp_state_home)
    yield
    await close_db()


_EIP_1_DRAFT = """---
eip: 1
title: First EIP
status: Draft
type: Standards Track
category: Core
---

# First EIP

Body of the first EIP.
"""

_EIP_2_FINAL = """---
eip: 2
title: Second EIP
status: Final
type: Standards Track
---

# Second EIP

Body of the second EIP.
"""

_EIP_3_REVIEW = """---
eip: 3
title: Third EIP
status: Review
---

# Third EIP
"""


async def _setup(
    cfg: CoreConfig,
    session: aiohttp.ClientSession,
    plugin_cfg: ProposalIntegrationConfig | None = None,
) -> ProposalIntegration:
    integration = ProposalIntegration()
    if plugin_cfg is not None:
        await set_config("proposal", plugin_cfg.model_dump(mode="json"))
    await integration.setup(Components(cfg=cfg, session=session))
    return integration


def _patch_kind_repo_url(monkeypatch: pytest.MonkeyPatch, kind: str, local_bare: Path) -> None:
    """Redirect a kind's repo URL to a local bare repo path."""
    original = _KIND_CONFIGS[kind]
    monkeypatch.setitem(
        _KIND_CONFIGS,
        kind,
        ProposalKindConfig(
            kind=original.kind,
            repo_url=f"file://{local_bare}",
            branch=original.branch,
            subdirectory=original.subdirectory,
            file_pattern=original.file_pattern,
            tracker_url=original.tracker_url,
        ),
    )


def _patch_clone_to_local(
    monkeypatch: pytest.MonkeyPatch,
    integration: ProposalIntegration,
    local_bare: Path,
) -> None:
    """Patch ``_clone_or_update`` on the integration to clone from a local path.

    Keeps the kind's GitHub URL intact so ``parse_repo_url`` still works for
    RFC PR-title resolution.
    """

    async def _fake_clone_or_update(self, kind_cfg: ProposalKindConfig) -> Path:

        state_home = self._cfg.state_home if self._cfg else "data"
        slug = "rfcs_repo" if kind_cfg.kind == "rfc" else f"{kind_cfg.kind}_repo"
        dest = Path(state_home) / "proposal_repos" / slug
        if dest.is_dir():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)

        subprocess.run(
            ["git", "clone", "--branch", kind_cfg.branch, str(local_bare), str(dest)],
            check=True,
            capture_output=True,
        )
        return dest

    monkeypatch.setattr(ProposalIntegration, "_clone_or_update", _fake_clone_or_update)


def _disable_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make AI analysis return empty results (zero-config behavior)."""

    monkeypatch.setattr(tracker_module, "build_model_string", lambda cfg: None)


def _stub_ai_success(monkeypatch: pytest.MonkeyPatch, summary: str = "Summary", detail: str = "Detail") -> None:
    """Stub AI analysis to always succeed with fixed output."""

    monkeypatch.setattr(tracker_module, "build_model_string", lambda cfg: "test:test")

    async def _fake_invoke(prompt, cfg):
        return AnalysisResult(summary=summary, detail=detail)

    monkeypatch.setattr(tracker_module, "_invoke_agent", _fake_invoke)


class TestSetup:
    async def test_setup_no_token_no_gh_client(self, db: None, tmp_state_home: str) -> None:
        cfg = CoreConfig(state_home=tmp_state_home, github=GitHubConfig(gh_token=SecretStr("")))
        async with aiohttp.ClientSession() as session:
            integration = await _setup(cfg, session)
            assert integration._gh is None

    async def test_setup_with_token_creates_gh_client(
        self,
        db: None,
        tmp_state_home: str,
    ) -> None:
        cfg = CoreConfig(
            state_home=tmp_state_home,
            github=GitHubConfig(gh_token=SecretStr("fake_token")),
        )
        async with aiohttp.ClientSession() as session:
            integration = await _setup(cfg, session)
            assert integration._gh is not None

    async def test_setup_loads_plugin_config(self, db: None, tmp_state_home: str) -> None:
        cfg = CoreConfig(state_home=tmp_state_home)
        async with aiohttp.ClientSession() as session:
            plugin_cfg = ProposalIntegrationConfig(trackers=["eip", "rfc"])
            integration = await _setup(cfg, session, plugin_cfg)
            assert integration._plugin_cfg.trackers == ["eip", "rfc"]


class TestSync:
    async def test_sync_creates_tracker_states(self, db: None, tmp_state_home: str) -> None:
        cfg = CoreConfig(state_home=tmp_state_home)
        async with aiohttp.ClientSession() as session:
            plugin_cfg = ProposalIntegrationConfig(trackers=["eip", "rfc"])
            integration = await _setup(cfg, session, plugin_cfg)
            result = await integration.sync()
            assert result.created == 2
            rows = await ProposalTrackerState.all()
            kinds = {r.kind for r in rows}
            assert kinds == {"eip", "rfc"}

    async def test_sync_no_change_on_existing(self, db: None, tmp_state_home: str) -> None:
        cfg = CoreConfig(state_home=tmp_state_home)
        async with aiohttp.ClientSession() as session:
            plugin_cfg = ProposalIntegrationConfig(trackers=["eip"])
            integration = await _setup(cfg, session, plugin_cfg)
            await integration.sync()

            result = await integration.sync()
            assert result.created == 0
            assert result.deleted == 0

    async def test_sync_gc_cascade_deletes_proposals(
        self,
        db: None,
        tmp_state_home: str,
    ) -> None:
        cfg = CoreConfig(state_home=tmp_state_home)
        async with aiohttp.ClientSession() as session:
            plugin_cfg = ProposalIntegrationConfig(trackers=["eip"])
            integration = await _setup(cfg, session, plugin_cfg)
            await integration.sync()

            state = await ProposalTrackerState.filter(kind="eip").first()
            assert state is not None
            await Proposal.create(tracker_id=state.id, number="1", title="X", raw_status="", status="draft")

            plugin_cfg2 = ProposalIntegrationConfig(trackers=["rfc"])
            await set_config("proposal", plugin_cfg2.model_dump(mode="json"))
            integration._plugin_cfg = plugin_cfg2
            result = await integration.sync()
            assert result.deleted == 1
            assert await ProposalTrackerState.filter(kind="eip").count() == 0
            assert await Proposal.all().count() == 0


class TestFirstRun:
    async def test_first_run_populates_snapshots_and_reports_newest_only(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        repo = git_helper.make_repo(
            workspace,
            "eips_repo",
            branch="master",
            initial_files={
                "EIPS/eip-1.md": _EIP_1_DRAFT,
                "EIPS/eip-2.md": _EIP_2_FINAL,
            },
            commit_date="2024-01-01T00:00:00",
        )
        git_helper.add_commit(
            repo,
            "add eip-3",
            files={"EIPS/eip-3.md": _EIP_3_REVIEW},
            commit_date="2024-01-02T00:00:00",
        )

        _patch_kind_repo_url(monkeypatch, "eip", repo.bare_path)
        _disable_ai(monkeypatch)

        cfg = CoreConfig(state_home=tmp_state_home)
        async with aiohttp.ClientSession() as session:
            plugin_cfg = ProposalIntegrationConfig(trackers=["eip"])
            integration = await _setup(cfg, session, plugin_cfg)
            await integration.sync()

            result = await integration.run()
            assert len(result.reports) == 1
            reports = result.reports[0].payload.get("reports", [])
            assert len(reports) == 1
            assert reports[0]["number"] == "3"

            rows = await Proposal.all()
            numbers = {r.number for r in rows}
            assert numbers == {"1", "2", "3"}
            statuses = {r.number: r.status for r in rows}
            assert statuses["1"] == "draft"
            assert statuses["2"] == "final"
            assert statuses["3"] == "review"

            state = await ProposalTrackerState.filter(kind="eip").first()
            assert state is not None
            assert state.last_seen_commit is not None

    async def test_first_run_empty_dir_no_reports(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = git_helper.make_repo(workspace, "empty_eips", branch="master")
        _patch_kind_repo_url(monkeypatch, "eip", repo.bare_path)
        _disable_ai(monkeypatch)

        cfg = CoreConfig(state_home=tmp_state_home)
        async with aiohttp.ClientSession() as session:
            plugin_cfg = ProposalIntegrationConfig(trackers=["eip"])
            integration = await _setup(cfg, session, plugin_cfg)
            await integration.sync()

            result = await integration.run()
            assert len(result.reports) == 0
            assert await Proposal.all().count() == 0


class TestIncrementalRun:
    async def test_incremental_draft_to_final_emits_event(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = git_helper.make_repo(
            workspace,
            "eips_inc",
            branch="master",
            initial_files={"EIPS/eip-1.md": _EIP_1_DRAFT},
        )
        _patch_kind_repo_url(monkeypatch, "eip", repo.bare_path)
        _stub_ai_success(monkeypatch)

        cfg = CoreConfig(state_home=tmp_state_home)
        async with aiohttp.ClientSession() as session:
            plugin_cfg = ProposalIntegrationConfig(trackers=["eip"])
            integration = await _setup(cfg, session, plugin_cfg)
            await integration.sync()
            await integration.run()

            git_helper.add_commit(
                repo,
                "update eip-1 to Final",
                files={
                    "EIPS/eip-1.md": _EIP_1_DRAFT.replace("status: Draft", "status: Final"),
                },
            )

            result = await integration.run()
            assert len(result.reports) == 1
            reports = result.reports[0].payload.get("reports", [])
            assert len(reports) == 1
            assert reports[0]["new_status"] == "final"
            assert reports[0]["old_status"] == "draft"
            assert len(result.events) == 1
            assert result.events[0].status == "final"  # ty:ignore[unresolved-attribute]

    async def test_incremental_draft_to_review_no_event_but_snapshot_updated(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Spec proposal §11 — snapshot vs notify separation."""
        repo = git_helper.make_repo(
            workspace,
            "eips_snap",
            branch="master",
            initial_files={"EIPS/eip-1.md": _EIP_1_DRAFT},
        )
        _patch_kind_repo_url(monkeypatch, "eip", repo.bare_path)
        _stub_ai_success(monkeypatch)

        cfg = CoreConfig(state_home=tmp_state_home)
        async with aiohttp.ClientSession() as session:
            plugin_cfg = ProposalIntegrationConfig(trackers=["eip"])
            integration = await _setup(cfg, session, plugin_cfg)
            await integration.sync()
            await integration.run()

            git_helper.add_commit(
                repo,
                "eip-1 to Review",
                files={
                    "EIPS/eip-1.md": _EIP_1_DRAFT.replace("status: Draft", "status: Review"),
                },
            )

            result = await integration.run()
            assert len(result.events) == 0
            assert len(result.reports) == 0

            row = await Proposal.filter(number="1").first()
            assert row is not None
            assert row.status == "review"
            assert row.raw_status == "Review"

    async def test_same_commit_returns_empty(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = git_helper.make_repo(
            workspace,
            "eips_same",
            branch="master",
            initial_files={"EIPS/eip-1.md": _EIP_1_DRAFT},
        )
        _patch_kind_repo_url(monkeypatch, "eip", repo.bare_path)
        _disable_ai(monkeypatch)

        cfg = CoreConfig(state_home=tmp_state_home)
        async with aiohttp.ClientSession() as session:
            plugin_cfg = ProposalIntegrationConfig(trackers=["eip"])
            integration = await _setup(cfg, session, plugin_cfg)
            await integration.sync()
            await integration.run()

            result = await integration.run()
            assert len(result.reports) == 0
            assert len(result.events) == 0


class TestRfcTitleResolution:
    async def test_rfc_title_resolved_from_pr(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rfc_text = """- Feature Name: my_feature
- RFC PR: [rust-lang/rfcs#42](https://github.com/rust-lang/rfcs/pull/42)

# Body
"""
        repo = git_helper.make_repo(
            workspace,
            "rfcs_repo",
            branch="master",
            initial_files={"text/0042-some-rfc.md": rfc_text},
        )
        _stub_ai_success(monkeypatch)

        cfg = CoreConfig(
            state_home=tmp_state_home,
            github=GitHubConfig(gh_token=SecretStr("t")),
        )

        async with aiohttp.ClientSession() as session:
            gh_mock = AsyncMock(spec=GitHubClient)
            gh_mock.get_pull_request_title = AsyncMock(return_value="Some Cool RFC Title")
            plugin_cfg = ProposalIntegrationConfig(trackers=["rfc"])
            integration = await _setup(cfg, session, plugin_cfg)
            integration._gh = gh_mock
            _patch_clone_to_local(monkeypatch, integration, repo.bare_path)
            await integration.sync()

            result = await integration.run()
            assert len(result.reports) == 1
            reports = result.reports[0].payload.get("reports", [])
            assert reports[0]["title"] == "Some Cool RFC Title"

    async def test_rfc_title_fallback_when_no_client(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rfc_text = """- Feature Name: my_feature_name
- RFC PR: [rust-lang/rfcs#42](https://github.com/rust-lang/rfcs/pull/42)
"""
        repo = git_helper.make_repo(
            workspace,
            "rfcs_no_client",
            branch="master",
            initial_files={"text/0042-some.md": rfc_text},
        )
        _patch_kind_repo_url(monkeypatch, "rfc", repo.bare_path)
        _stub_ai_success(monkeypatch)

        cfg = CoreConfig(state_home=tmp_state_home, github=GitHubConfig(gh_token=SecretStr("")))

        async with aiohttp.ClientSession() as session:
            plugin_cfg = ProposalIntegrationConfig(trackers=["rfc"])
            integration = await _setup(cfg, session, plugin_cfg)
            await integration.sync()
            result = await integration.run()
            assert len(result.reports) == 1
            reports = result.reports[0].payload.get("reports", [])
            assert reports[0]["title"] == "My feature name"

    async def test_rfc_title_fallback_when_pr_lookup_fails(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rfc_text = """- Feature Name: my_feature_name
- RFC PR: [rust-lang/rfcs#42](https://github.com/rust-lang/rfcs/pull/42)
"""
        repo = git_helper.make_repo(
            workspace,
            "rfcs_pr_fail",
            branch="master",
            initial_files={"text/0042-some.md": rfc_text},
        )
        _stub_ai_success(monkeypatch)

        cfg = CoreConfig(
            state_home=tmp_state_home,
            github=GitHubConfig(gh_token=SecretStr("t")),
        )

        async with aiohttp.ClientSession() as session:
            gh_mock = AsyncMock(spec=GitHubClient)
            gh_mock.get_pull_request_title = AsyncMock(side_effect=ProgressException("404"))
            plugin_cfg = ProposalIntegrationConfig(trackers=["rfc"])
            integration = await _setup(cfg, session, plugin_cfg)
            integration._gh = gh_mock
            _patch_clone_to_local(monkeypatch, integration, repo.bare_path)
            await integration.sync()

            result = await integration.run()
            assert len(result.reports) == 1
            reports = result.reports[0].payload.get("reports", [])
            assert reports[0]["title"] == "My feature name"


class TestErrorAggregation:
    async def test_clone_failure_emits_error(
        self,
        db: None,
        tmp_state_home: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_kind_repo_url(monkeypatch, "eip", Path("/nonexistent/path/to/repo.git"))
        _disable_ai(monkeypatch)

        cfg = CoreConfig(state_home=tmp_state_home)
        async with aiohttp.ClientSession() as session:
            plugin_cfg = ProposalIntegrationConfig(trackers=["eip"])
            integration = await _setup(cfg, session, plugin_cfg)
            await integration.sync()

            result = await integration.run()
            assert result.status in {"partial", "failed"}
            assert len(result.errors) >= 1

    async def test_ai_failure_does_not_block(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = git_helper.make_repo(
            workspace,
            "eips_ai_fail",
            branch="master",
            initial_files={"EIPS/eip-1.md": _EIP_1_DRAFT},
        )
        _patch_kind_repo_url(monkeypatch, "eip", repo.bare_path)

        monkeypatch.setattr("progress.integrations.proposal.tracker.build_model_string", lambda cfg: "test:test")

        async def _failing_invoke(prompt, cfg):
            raise RuntimeError("AI failed")

        monkeypatch.setattr("progress.integrations.proposal.tracker._invoke_agent", _failing_invoke)

        cfg = CoreConfig(state_home=tmp_state_home)
        async with aiohttp.ClientSession() as session:
            plugin_cfg = ProposalIntegrationConfig(trackers=["eip"])
            integration = await _setup(cfg, session, plugin_cfg)
            await integration.sync()

            result = await integration.run()
            assert len(result.reports) == 1
            reports = result.reports[0].payload.get("reports", [])
            assert len(reports) == 1
            assert reports[0]["analysis_summary"] is None or reports[0]["analysis_summary"] == ""


class TestConcurrency:
    async def test_run_accepts_concurrency_kwarg(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = git_helper.make_repo(
            workspace,
            "eips_conc",
            branch="master",
            initial_files={"EIPS/eip-1.md": _EIP_1_DRAFT},
        )
        _patch_kind_repo_url(monkeypatch, "eip", repo.bare_path)
        _disable_ai(monkeypatch)

        cfg = CoreConfig(state_home=tmp_state_home)
        async with aiohttp.ClientSession() as session:
            plugin_cfg = ProposalIntegrationConfig(trackers=["eip"])
            integration = await _setup(cfg, session, plugin_cfg)
            await integration.sync()

            result = await integration.run(concurrency=2)
            assert result.name == "proposal"


class TestMoveAndDelete:
    async def test_moved_file_detected_by_number(
        self,
        db: None,
        tmp_state_home: str,
        workspace: Path,
        git_helper,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        moves = _detect_moves([("M", "EIPS/eip-1.md"), ("D", "EIPS/old-eip-1.md")])
        assert "1" in moves

    async def test_filter_files_subdirectory_match(
        self,
        db: None,
    ) -> None:

        kind_cfg = _KIND_CONFIGS["eip"]
        filtered = _filter_files(
            [
                ("M", "EIPS/eip-1.md"),
                ("A", "README.md"),
                ("M", "ERCS/erc-1.md"),
            ],
            kind_cfg,
        )
        assert len(filtered) == 1
        assert filtered[0][1] == "EIPS/eip-1.md"

    async def test_filter_files_no_subdir_matches_root(
        self,
        db: None,
    ) -> None:

        kind_cfg = _KIND_CONFIGS["pep"]
        filtered = _filter_files(
            [
                ("M", "pep-0001.rst"),
                ("A", "README.md"),
            ],
            kind_cfg,
        )
        assert len(filtered) == 1
        assert filtered[0][1] == "pep-0001.rst"
