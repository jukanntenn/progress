"""E2E: proposal RFC PR title resolution + fallback (spec 15 §2.7).

A single case exercises both branches of §12 RFC special parsing within the
spec-mandated 5-case proposal suite:
- with a PR number → aioresponses mocks the GitHub PR API → the PR title is used;
- without a PR number → the parser fallback (humanized Feature Name) is used.
Either way tracking is never blocked. Each branch runs against its own clean
state_home so the two runs do not share DB checkpoint state.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from pydantic import SecretStr
import pytest

from progress.cli.core import run
from progress.config.root import CoreConfig, GitHubConfig
from progress.integrations.proposal.config import ProposalIntegrationConfig
from progress.integrations.proposal.tracker import ProposalIntegration
from tests.e2e.conftest import seed_config

_RFC_WITH_PR = """\
- Feature Name: async_closures
- Start Date: 2024-01-01
- RFC PR: [#3456](https://github.com/rust-lang/rfcs/pull/3456)

# Summary

Async closures for Rust.
"""

_RFC_NO_PR = """\
- Feature Name: some_feature
- Start Date: 2024-02-01

# Summary

A feature without a PR.
"""

_PR_PAYLOAD = {"title": "RFC: Add async closures to the language", "number": 3456}


def _patch_rfc_clone(monkeypatch: pytest.MonkeyPatch, local_bare: Path, branch: str) -> None:
    async def _fake_clone(self: ProposalIntegration, kind_cfg: Any) -> Path:
        state_home = self._cfg.state_home if self._cfg else "data"
        dest = Path(state_home) / "proposal_repos" / "rfcs_repo"
        if dest.is_dir():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--branch", branch, str(local_bare), str(dest)],
            check=True,
            capture_output=True,
        )
        return dest

    monkeypatch.setattr(ProposalIntegration, "_clone_or_update", _fake_clone)


async def _run_rfc(
    state_home: str,
    workspace: Path,
    git_helper: Any,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    content: str,
) -> list[dict[str, Any]]:
    repo = git_helper.make_repo(
        workspace,
        "rfcs_repo",
        branch="master",
        initial_files={filename: content},
    )
    _patch_rfc_clone(monkeypatch, repo.bare_path, "master")
    cfg = CoreConfig(state_home=state_home, github=GitHubConfig(gh_token=SecretStr("fake-token")))
    async with seed_config(state_home, "proposal", ProposalIntegrationConfig(trackers=["rfc"])):
        pass
    outcome = await run(cfg)
    assert outcome.exit_code == 0
    proposal_result = outcome.results["proposal"]
    assert proposal_result.status == "success"
    return proposal_result.reports[0].payload.get("reports", [])


@pytest.mark.asyncio
async def test_rfc_pr_title_resolution(
    tmp_path: Path,
    git_helper: Any,
    monkeypatch: pytest.MonkeyPatch,
    gh_mock: Any,
) -> None:
    gh_mock.get(
        re.compile(r"^https://api\.github\.com/repos/rust-lang/rfcs/pulls/3456$"),
        payload=_PR_PAYLOAD,
        repeat=True,
    )
    with_pr_ws = tmp_path / "with_pr" / "ws"
    with_pr_ws.mkdir(parents=True)
    with_pr_state = str(tmp_path / "with_pr" / "state")
    Path(with_pr_state).mkdir(parents=True)
    with_pr = await _run_rfc(
        with_pr_state, with_pr_ws, git_helper, monkeypatch, "text/3456-async-closures.md", _RFC_WITH_PR
    )
    assert len(with_pr) == 1
    assert with_pr[0]["title"] == "RFC: Add async closures to the language"

    no_pr_ws = tmp_path / "no_pr" / "ws"
    no_pr_ws.mkdir(parents=True)
    no_pr_state = str(tmp_path / "no_pr" / "state")
    Path(no_pr_state).mkdir(parents=True)
    no_pr = await _run_rfc(no_pr_state, no_pr_ws, git_helper, monkeypatch, "text/7890-some-feature.md", _RFC_NO_PR)
    assert len(no_pr) == 1
    assert "Some feature" in no_pr[0]["title"]
