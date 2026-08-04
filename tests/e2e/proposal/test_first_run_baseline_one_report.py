"""E2E: proposal integration first-run baseline (spec 15 §2.7).

Fresh EIP repo: ALL proposals are imported into the Proposal snapshot table,
but only ONE report is produced (the newest-created file). Verifies the
"first run all imported + only 1 report" deliberate design (spec proposal §6)
+ checkpoint advancement.
"""

from __future__ import annotations

from typing import Any

import pytest

from progress.cli.core import run
from progress.integrations.proposal.config import ProposalIntegrationConfig
from progress.integrations.proposal.models import Proposal, ProposalTrackerState
from tests.e2e.conftest import db_view, seed_config


@pytest.mark.asyncio
async def test_first_run_baseline_one_report(
    test_cfg: Any,
    proposal_env: dict[str, Any],
) -> None:
    proposal_cfg = ProposalIntegrationConfig(trackers=["eip"])
    async with seed_config(test_cfg.state_home, "proposal", proposal_cfg):
        pass

    outcome = await run(test_cfg)
    assert outcome.exit_code == 0

    proposal_result = outcome.results["proposal"]
    assert proposal_result.status == "success"
    assert len(proposal_result.reports) == 1
    notifiable = proposal_result.reports[0].payload.get("reports", [])
    assert len(notifiable) == 1

    async with db_view(test_cfg.state_home):
        proposals = await Proposal.all()
        assert len(proposals) == 2
        states = await ProposalTrackerState.filter(kind="eip")
        assert len(states) == 1
        assert states[0].last_seen_commit is not None
