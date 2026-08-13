"""Tortoise state models for the ``v2ex`` integration (spec 03 / spec v2ex §5).

- :class:`V2exTracker` — one row per tracked source (currently a tab, e.g.
  ``tab:jobs``). Carries the per-source dedup water mark (``last_topic_id``:
  the highest V2EX topic id already processed). Rows are created / deleted by
  ``sync`` based on the configured ``tabs`` (config-driven, like changelog).
"""

from __future__ import annotations

from typing import override

from tortoise import fields

from progress.db.base import BaseModel
from progress.utils.timezone import now_utc


class V2exTracker(BaseModel):
    """One row per tracked V2EX source (spec v2ex §5).

    ``source`` is the identity key, generalised beyond tabs (``tab:jobs`` /
    ``tab:creative`` today; ``node:<slug>`` / ``member:<name>`` later without a
    rename). ``last_topic_id`` is the monotonic dedup water mark: the next run
    only processes topics whose id is greater (spec v2ex §4). Advanced only
    after a source's new topics have been classified (processed), covering
    every new topic — not just the selected top-K — so unselected but
    interested topics are not re-classified every run.
    """

    id = fields.IntField(primary_key=True)
    source = fields.CharField(max_length=64, unique=True)
    last_topic_id = fields.BigIntField(null=True)
    last_check_time = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(default=now_utc)
    updated_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "v2ex_trackers"

    @override
    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"<V2exTracker source={self.source!r} last_topic_id={self.last_topic_id}>"


__all__ = ["V2exTracker"]
