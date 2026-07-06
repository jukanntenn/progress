"""ProposalTrackerState and Proposal models (tables: proposal_trackers, proposals)."""

from tortoise import fields

from progress.db.models.base import BaseModel
from progress.utils.timezone import now_utc


class ProposalTrackerState(BaseModel):
    """Per-tracker checkpoint state for proposal discovery."""

    id: int = fields.IntField(primary_key=True)  # ty: ignore[invalid-assignment]
    kind: str = fields.CharField(max_length=255, unique=True)  # ty: ignore[invalid-assignment]
    last_seen_commit: str | None = fields.CharField(max_length=255, null=True)  # ty: ignore[invalid-assignment]
    last_check_time = fields.DatetimeField(null=True, default=None)
    created_at = fields.DatetimeField(default=now_utc)
    updated_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "proposal_trackers"


class Proposal(BaseModel):
    """A tracked proposal (RFC/EIP/etc.) and its status."""

    id: int = fields.IntField(primary_key=True)  # ty: ignore[invalid-assignment]
    tracker: fields.ForeignKeyRelation[ProposalTrackerState] = fields.ForeignKeyField(
        ProposalTrackerState,
        related_name="proposals",
        on_delete=fields.CASCADE,
    )
    number: str = fields.CharField(max_length=255)  # ty: ignore[invalid-assignment]
    title: str | None = fields.CharField(max_length=255, null=True)  # ty: ignore[invalid-assignment]
    raw_status: str = fields.CharField(max_length=255, default="")  # ty: ignore[invalid-assignment]
    status: str = fields.CharField(max_length=255)  # ty: ignore[invalid-assignment]
    created_at = fields.DatetimeField(default=now_utc)
    updated_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "proposals"
        unique_together = (("tracker_id", "number"),)


__all__ = ["Proposal", "ProposalTrackerState"]
