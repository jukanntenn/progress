"""Repository model (table: repositories)."""

from tortoise import fields

from progress.db.models.base import BaseModel
from progress.enums import ReportType  # noqa: F401  # re-exported for callers
from progress.utils.timezone import now_utc


class Repository(BaseModel):
    """Tracked GitHub repository."""

    id: int = fields.IntField(primary_key=True)  # ty: ignore[invalid-assignment]
    name: str = fields.CharField(max_length=255)  # ty: ignore[invalid-assignment]
    url: str = fields.CharField(max_length=255, unique=True)  # ty: ignore[invalid-assignment]
    branch: str = fields.CharField(max_length=255)  # ty: ignore[invalid-assignment]
    last_commit_hash: str | None = fields.CharField(max_length=255, null=True)  # ty: ignore[invalid-assignment]
    last_check_time = fields.DatetimeField(null=True, default=None)
    enabled: bool = fields.BooleanField(default=True)  # ty: ignore[invalid-assignment]
    created_at = fields.DatetimeField(default=now_utc)
    updated_at = fields.DatetimeField(default=now_utc)
    last_release_tag: str | None = fields.CharField(max_length=255, null=True)  # ty: ignore[invalid-assignment]
    last_release_commit_hash: str | None = fields.CharField(max_length=255, null=True)  # ty: ignore[invalid-assignment]
    last_release_check_time = fields.DatetimeField(null=True, default=None)

    class Meta:
        table = "repositories"


__all__ = ["Repository"]
