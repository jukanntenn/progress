"""E2E: proposal status-change notify filter (spec 15 §2.7).

Two status changes in one incremental run: Draft→Final (notifiable) and
Draft→Review (not notifiable). Both snapshots are updated, but only the Final
change is persisted as a report + notified. Verifies the "snapshot update vs
notification filter separation" (spec proposal §11) — the proposal's key design.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from progress.cli.core import run
from progress.cli.notifications.events import ProposalEvent
from progress.integrations.proposal.config import ProposalIntegrationConfig
from progress.integrations.proposal.models import Proposal
from tests.e2e.conftest import _patch_kind_repo_url, _patch_proposal_clone, db_view, seed_config

if TYPE_CHECKING:
    from pathlib import Path

_EIP_1_DRAFT = """\
---
eip: 1
title: First EIP
status: Draft
type: Standards Track
category: Core
---

# First EIP

Body of the first EIP.
"""

_EIP_2_DRAFT = """\
---
eip: 2
title: Second EIP
status: Draft
type: Standards Track
---

# Second EIP

Body of the second EIP.
"""

_EIP_1_REVIEW = """\
---
eip: 1
title: First EIP
status: Review
type: Standards Track
category: Core
---

# First EIP

Body of the first EIP.
"""

_EIP_2_FINAL = """\
---
eip: 2
title: Second EIP
status: Final
type: Standards Track
---

# Second EIP

Body of the second EIP.
"""


@pytest.mark.asyncio
async def test_incremental_status_change_notify_filter(
    test_cfg: Any,
    workspace: Path,
    git_helper: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    repo = git_helper.make_repo(
        workspace,
        "eips_repo",
        branch="master",
        initial_files={
            "EIPS/eip-1.md": _EIP_1_DRAFT,
            "EIPS/eip-2.md": _EIP_2_DRAFT,
        },
    )
    _patch_kind_repo_url(monkeypatch, "eip", repo.bare_path)
    _patch_proposal_clone(monkeypatch, repo.bare_path, "master")

    proposal_cfg = ProposalIntegrationConfig(trackers=["eip"])
    async with seed_config(test_cfg.state_home, "proposal", proposal_cfg):
        pass

    first = await run(test_cfg)
    assert first.exit_code == 0

    repo.add_commit(
        "Status changes",
        files={
            "EIPS/eip-1.md": _EIP_1_REVIEW,
            "EIPS/eip-2.md": _EIP_2_FINAL,
        },
    )

    second = await run(test_cfg)
    assert second.exit_code == 0
    proposal_result = second.results["proposal"]
    assert proposal_result.status == "success"

    notifiable = proposal_result.reports[0].payload.get("reports", [])
    notifiable_numbers = {r["number"] for r in notifiable}
    assert notifiable_numbers == {"2"}

    events = [e for e in proposal_result.events if isinstance(e, ProposalEvent)]
    assert len(events) == 1
    assert events[0].number == 2
    assert events[0].status == "final"

    async with db_view(test_cfg.state_home):
        proposals = {p.number: p for p in await Proposal.all()}
        assert proposals["1"].status == "review"
        assert proposals["2"].status == "final"
