"""Tortoise state models for the ``proposal`` integration (spec 03 / spec proposal §2).

- :class:`ProposalTrackerState` — one row per enabled proposal kind (``eip``,
  ``erc``, ``pep``, …). Carries the git commit checkpoint (NOT a proposal
  number — incremental detection is git-diff based per spec proposal §2).
- :class:`Proposal` — one row per discovered proposal. FK to its tracker;
  ``on_delete=CASCADE`` so removing a kind from config drops its proposals
  (spec proposal §2).
"""

from __future__ import annotations

from typing import override

from tortoise import fields

from progress.db.base import BaseModel
from progress.utils.timezone import now_utc


class ProposalTrackerState(BaseModel):
    """Checkpoint row for one proposal kind (e.g. ``eip``).

    ``last_seen_commit`` is a git commit hash (not a proposal number) — the
    incremental detection compares HEAD against this hash via ``git diff``
    (spec proposal §2).
    """

    id = fields.IntField(primary_key=True)
    kind = fields.CharField(max_length=32, unique=True)
    last_seen_commit = fields.CharField(max_length=255, null=True)
    last_check_time = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(default=now_utc)
    updated_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "proposal_tracker_states"

    @override
    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"<ProposalTrackerState kind={self.kind!r} last_commit={self.last_seen_commit!r}>"


class Proposal(BaseModel):
    """A single tracked proposal (spec proposal §2)."""

    id = fields.IntField(primary_key=True)
    tracker: fields.ForeignKeyRelation = fields.ForeignKeyField(
        "proposal.ProposalTrackerState",
        related_name="proposals",
        on_delete=fields.CASCADE,
    )
    number = fields.CharField(max_length=64)
    title = fields.CharField(max_length=512, null=True)
    raw_status = fields.CharField(max_length=128, default="")
    status = fields.CharField(max_length=64)
    created_at = fields.DatetimeField(default=now_utc)
    updated_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "proposals"
        unique_together = (("tracker_id", "number"),)

    @override
    def __str__(self) -> str:  # pragma: no cover - debug aid
        tracker_id = getattr(self, "tracker_id", None)
        return f"<Proposal kind={tracker_id} #{self.number} {self.title!r}>"


__all__ = ["Proposal", "ProposalTrackerState"]
