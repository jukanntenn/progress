"""Tortoise state models for the ``feed`` integration (spec 03 / spec feed §2).

- :class:`FeedTracker` — one row per Miniflux feed tracked. Carries the per-feed
  dedup water mark (``last_entry_id``) and display metadata (``title`` /
  ``site_url``). Rows are created / updated / GC'd by ``run`` based on what
  Miniflux actually returns (spec feed §1 rule 1 — data-source driven, not
  config driven), so ``sync`` is a no-op.
"""

from __future__ import annotations

from typing import override

from tortoise import fields

from progress.db.base import BaseModel
from progress.utils.timezone import now_utc


class FeedTracker(BaseModel):
    """One row per Miniflux feed tracked by the feed integration (spec feed §2).

    ``feed_id`` is the identity key (the Miniflux feed id, stable inside
    Miniflux). ``last_entry_id`` is the monotonic dedup water mark: the next
    run only processes entries with id greater than it (spec feed §1 rule 2).
    ``last_check_time`` is stamped on every run that sees this feed.
    """

    id = fields.IntField(primary_key=True)
    feed_id = fields.BigIntField(unique=True)
    title = fields.CharField(max_length=512)
    site_url = fields.CharField(max_length=1024, null=True)
    last_entry_id = fields.BigIntField(null=True)
    last_check_time = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(default=now_utc)
    updated_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "feed_trackers"

    @override
    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"<FeedTracker feed_id={self.feed_id} title={self.title!r} last_entry_id={self.last_entry_id}>"


__all__ = ["FeedTracker"]
