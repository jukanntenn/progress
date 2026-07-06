"""AppConfig model (table: app_config — single-row config blob store)."""

from tortoise import fields

from progress.db.models.base import BaseModel
from progress.utils.timezone import now_utc


class AppConfig(BaseModel):
    """Single-row application configuration store.

    Holds the versioned JSON blob of editable app config. ``id`` is always 1.
    ``version`` drives optimistic concurrency control and ``schema_version``
    tracks which config-schema revision the blob was written under.
    """

    id: int = fields.IntField(primary_key=True)  # ty: ignore[invalid-assignment]
    version: int = fields.IntField(default=1)  # ty: ignore[invalid-assignment]
    schema_version: int = fields.IntField(default=0)  # ty: ignore[invalid-assignment]
    data: str = fields.TextField(default="{}")  # ty: ignore[invalid-assignment]
    updated_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "app_config"


__all__ = ["AppConfig"]
