"""Report model (table: reports)."""

from tortoise import fields

from progress.db.models.base import BaseModel
from progress.db.models.repository import Repository
from progress.enums import ReportType
from progress.utils.timezone import now_utc


class Report(BaseModel):
    """Generated analysis report."""

    id: int = fields.IntField(primary_key=True)  # ty: ignore[invalid-assignment]
    report_type: str = fields.CharField(max_length=255, default=ReportType.REPO_UPDATE.value)  # ty: ignore[invalid-assignment]
    repo: fields.ForeignKeyNullableRelation[Repository] = fields.ForeignKeyField(
        Repository,
        related_name="reports",
        on_delete=fields.CASCADE,
        null=True,
    )
    title: str = fields.CharField(max_length=255, default="")  # ty: ignore[invalid-assignment]
    commit_hash: str = fields.CharField(max_length=255)  # ty: ignore[invalid-assignment]
    previous_commit_hash: str | None = fields.CharField(max_length=255, null=True)  # ty: ignore[invalid-assignment]
    commit_count: int = fields.IntField(default=1)  # ty: ignore[invalid-assignment]
    markpost_url: str | None = fields.CharField(max_length=255, null=True)  # ty: ignore[invalid-assignment]
    content: str | None = fields.TextField(null=True)  # ty: ignore[invalid-assignment]
    created_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "reports"


__all__ = ["Report"]
