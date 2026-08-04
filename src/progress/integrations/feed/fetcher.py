"""Fetch + group + dedup helpers for the feed integration (spec feed §5.1/§5.2).

Pure functions operating on :class:`~progress.integrations.feed.client.RawEntry`
and the per-feed water marks loaded from :class:`FeedTracker`. No IO — the
client and DB live in :mod:`client` / :mod:`tracker` respectively.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from progress.integrations.feed.client import RawEntry

#: Max entries processed per feed per run (spec feed §3 code constant).
#: Prevents a single backlogged feed from flooding one report; older entries
#: past this cut-off are permanently skipped (spec feed §5.2 intentional).
MAX_ENTRIES_PER_FEED: int = 50


@dataclass
class Feed:
    """A feed's metadata + its new (post-water-mark) entries for this run."""

    feed_id: int
    title: str
    site_url: str
    entries: list[RawEntry] = field(default_factory=list)

    @property
    def entry_count(self) -> int:
        return len(self.entries)


def filter_new_entries(
    entries: list[RawEntry],
    *,
    water_marks: dict[int, int | None],
) -> dict[int, list[RawEntry]]:
    """Group ``entries`` by feed and drop those at/below the per-feed water mark.

    Per spec feed §5.2: keep entries whose ``id > last_entry_id`` (when the
    water mark is ``None`` keep all — first time seeing the feed), then sort
    each feed's survivors by id descending and take the newest
    :data:`MAX_ENTRIES_PER_FEED`. Feeds with no survivors are still keys in the
    returned dict (with an empty list) so the tracker can stamp
    ``last_check_time`` on them.
    """
    grouped: dict[int, list[RawEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.feed_id, []).append(entry)

    result: dict[int, list[RawEntry]] = {}
    for feed_id, feed_entries in grouped.items():
        water_mark = water_marks.get(feed_id)
        kept = list(feed_entries) if water_mark is None else [e for e in feed_entries if e.id > water_mark]
        kept.sort(key=lambda e: e.id, reverse=True)
        result[feed_id] = kept[:MAX_ENTRIES_PER_FEED]
    return result


def build_feed(
    feed_id: int,
    *,
    title: str,
    site_url: str,
    entries: list[RawEntry],
) -> Feed:
    """Assemble a :class:`Feed` from grouping output (sorted newest-first)."""
    return Feed(feed_id=feed_id, title=title, site_url=site_url, entries=entries)


def max_entry_id(entries: list[RawEntry]) -> int | None:
    """Return the highest entry id in ``entries`` (None when empty).

    Used to advance the per-feed water mark after a successful analysis
    (spec feed §5.3).
    """
    if not entries:
        return None
    return max(e.id for e in entries)


def first_entry_meta(
    entries: list[RawEntry],
    *,
    fallback_title: str,
) -> tuple[int, str, str]:
    """Derive ``(feed_id, title, site_url)`` display metadata from a feed's entries.

    Used when a feed exists in Miniflux's unread set but has no
    :class:`FeedTracker` row yet — the per-entry ``feed`` object carries the
    title / site_url we display. ``fallback_title`` is used when the feed
    object is missing the title.
    """
    if not entries:
        raise ValueError("cannot derive feed metadata from empty entry list")
    first = entries[0]
    feed_obj = first.feed or {}
    title = str(feed_obj.get("title") or fallback_title)
    site_url = str(feed_obj.get("site_url") or "")
    return first.feed_id, title, site_url


def format_published_at(dt: datetime) -> str:
    """Format a publication timestamp for report display (ISO-like, no tz shift).

    Local-timezone conversion is the report layer's concern; here we emit a
    stable sortable representation. The template converts to local time via
    the core timezone (spec feed §7.1).
    """
    return dt.strftime("%Y-%m-%d %H:%M:%S")


__all__ = [
    "MAX_ENTRIES_PER_FEED",
    "Feed",
    "build_feed",
    "filter_new_entries",
    "first_entry_meta",
    "format_published_at",
    "max_entry_id",
]
