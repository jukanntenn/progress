"""E2E: proposal incremental new proposal notifies (spec 15 §2.7).

Second run adds a new EIP file: a ``new`` event fires (old_status=None → always
notifiable), the notifiable report is aggregated + persisted, and a ProposalEvent
is emitted. Verifies the new-event contract through the full ``core.run``.
"""

from __future__ import annotations

from typing import Any

import pytest

from progress.cli.core import run
from progress.cli.notifications.events import ProposalEvent
from progress.integrations.proposal.config import ProposalIntegrationConfig
from tests.e2e.conftest import seed_config

_NEW_EIP = """\
---
eip: 3
title: Third EIP
status: Draft
type: Standards Track
---

# Third EIP

A newly added EIP.
"""


@pytest.mark.asyncio
async def test_incremental_new_proposal_notifies(
    test_cfg: Any,
    proposal_env: dict[str, Any],
) -> None:
    proposal_cfg = ProposalIntegrationConfig(trackers=["eip"])
    async with seed_config(test_cfg.state_home, "proposal", proposal_cfg):
        pass

    first = await run(test_cfg)
    assert first.exit_code == 0

    repo = proposal_env["repo"]
    repo.add_commit("Add EIP-3", files={"EIPS/eip-3.md": _NEW_EIP})

    second = await run(test_cfg)
    assert second.exit_code == 0
    proposal_result = second.results["proposal"]
    assert proposal_result.status == "success"
    assert len(proposal_result.reports) == 1

    events = [e for e in proposal_result.events if isinstance(e, ProposalEvent)]
    assert len(events) == 1
    assert events[0].number == 3
    assert events[0].proposal_kind == "eip"
