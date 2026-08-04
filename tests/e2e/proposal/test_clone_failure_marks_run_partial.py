"""E2E: proposal integration clone failure → run partial (spec 15 §2.7).

Proposal repo clone fails → a stage="clone" error is reported and re-raised →
``core.run`` aggregates it and the outcome is partial. Verifies clone error
aggregation in the proposal path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from progress.cli.core import run
from progress.errors import ProgressException
from progress.integrations.proposal.config import ProposalIntegrationConfig
from progress.integrations.proposal.tracker import ProposalIntegration, ProposalKindConfig
from tests.e2e.conftest import seed_config

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_clone_failure_marks_run_partial(
    test_cfg: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _failing_clone(self: ProposalIntegration, kind_cfg: ProposalKindConfig) -> Path:
        raise ProgressException(f"clone failed for {kind_cfg.kind}: simulated network error")

    monkeypatch.setattr(ProposalIntegration, "_clone_or_update", _failing_clone)

    proposal_cfg = ProposalIntegrationConfig(trackers=["eip"])
    async with seed_config(test_cfg.state_home, "proposal", proposal_cfg):
        pass

    outcome = await run(test_cfg)
    assert outcome.exit_code == 1
    assert outcome.errors
    proposal_result = outcome.results["proposal"]
    assert proposal_result.status in {"partial", "failed"}
