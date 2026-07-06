"""Batch model (table: batch — singular)."""

from tortoise import fields

from progress.db.models.base import BaseModel
from progress.db.models.report import Report
from progress.utils.timezone import now_utc


class Batch(BaseModel):
    """One published MarkPost article of a multi-part aggregated report."""

    id: int = fields.IntField(primary_key=True)  # ty: ignore[invalid-assignment]
    report: fields.ForeignKeyRelation[Report] = fields.ForeignKeyField(
        Report,
        related_name="batches",
        on_delete=fields.CASCADE,
    )
    title: str = fields.CharField(max_length=255)  # ty: ignore[invalid-assignment]
    markpost_url: str = fields.CharField(max_length=255, default="")  # ty: ignore[invalid-assignment]
    seq: int = fields.IntField()  # ty: ignore[invalid-assignment]
    created_at = fields.DatetimeField(default=now_utc)
    updated_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "batch"
        unique_together = (("report_id", "seq"),)


__all__ = ["Batch"]
