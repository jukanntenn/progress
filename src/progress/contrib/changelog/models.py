"""ChangelogTracker model (table: changelog_trackers)."""

from tortoise import fields

from progress.db.models.base import BaseModel
from progress.utils.timezone import now_utc


class ChangelogTracker(BaseModel):
    """A remote changelog feed to monitor for new versions."""

    id: int = fields.IntField(primary_key=True)  # ty: ignore[invalid-assignment]
    name: str = fields.CharField(max_length=255)  # ty: ignore[invalid-assignment]
    url: str = fields.CharField(max_length=255, unique=True)  # ty: ignore[invalid-assignment]
    parser_type: str = fields.CharField(max_length=255)  # ty: ignore[invalid-assignment]
    last_seen_version: str | None = fields.CharField(max_length=255, null=True)  # ty: ignore[invalid-assignment]
    enabled: bool = fields.BooleanField(default=True)  # ty: ignore[invalid-assignment]
    last_check_time = fields.DatetimeField(null=True, default=None)
    created_at = fields.DatetimeField(default=now_utc)
    updated_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "changelog_trackers"


__all__ = ["ChangelogTracker"]
