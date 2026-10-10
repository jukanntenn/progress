"""Tortoise state model for the ``changelog`` integration (spec 03 / spec changelog §2).

A single :class:`ChangelogTracker` row holds the source URL (the identity key),
parser type, and the last-seen version checkpoint that the tracker advances.

Per spec changelog §2 the **URL is the identity key** (unique, used for upsert
and GC). Changing the URL is equivalent to delete + create (the watermark is
not carried over). ``name``/``parser_type``/``enabled``/``proxy`` are mutable fields that
trigger updates without rebuilding the watermark.
"""

from __future__ import annotations

from typing import override

from tortoise import fields

from progress.db.base import BaseModel
from progress.utils.timezone import now_utc


class ChangelogTracker(BaseModel):
    """Changelog source with last-seen version checkpoint (spec changelog §2)."""

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255)
    url = fields.CharField(max_length=1024, unique=True)
    parser_type = fields.CharField(max_length=64, default="auto")
    enabled = fields.BooleanField(default=True)
    # db_default is required for the ADD COLUMN DDL: SQLite rejects a NOT NULL
    # column without a database-level default (migration 0003).
    proxy = fields.CharField(max_length=1024, default="", db_default="")
    last_seen_version = fields.CharField(max_length=255, null=True)
    last_check_time = fields.DatetimeField(null=True)
    # Feature 6: a deterministic ChangelogRule (JSON) learned from the AI
    # fallback so subsequent parses skip the AI call entirely.
    learned_rule = fields.TextField(null=True)
    rule_success_count = fields.IntField(default=0)
    created_at = fields.DatetimeField(default=now_utc)
    updated_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "changelog_trackers"

    @override
    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"<ChangelogTracker id={self.id} name={self.name!r} url={self.url!r}>"


__all__ = ["ChangelogTracker"]
