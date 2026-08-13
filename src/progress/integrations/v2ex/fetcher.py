"""Pure helpers for the v2ex integration (spec v2ex §4/§7).

No IO — water-mark dedup, global top-K ranking, and source-key encoding live
here so they are unit-testable without network or DB. ``ClassifiedPost`` is the
in-memory join of a :class:`RawTopic` with its AI classification + summary; the
merge key is ALWAYS ``topic_id`` (never the per-batch ``post_index``, which is
re-numbered independently for the classify and summarize batches — spec v2ex
§7.1).
"""

from __future__ import annotations

from dataclasses import dataclass

from progress.integrations.v2ex.parser import RawTopic


@dataclass
class ClassifiedPost:
    """A topic joined with its AI classification + (optional) summary.

    ``interested`` and ``score`` are the two independent classification signals
    (spec v2ex §6): ``interested`` is the absolute match verdict, ``score``
    (0-10) drives global top-K ranking. ``takeaway`` is empty until the
    summarize stage fills it; an unfilled takeaway degrades to ``reason`` at
    render time.
    """

    topic: RawTopic
    interested: bool = False
    score: int = 0
    reason: str = ""
    takeaway: str = ""


def source_key(tab: str) -> str:
    """Encode a tab id as the tracker identity key (``tab:jobs``)."""
    return f"tab:{tab}"


def parse_source(key: str) -> str:
    """Recover the tab id from a source key (``tab:jobs`` → ``jobs``).

    Returns the raw key unchanged for unknown prefixes, so future ``node:`` /
    ``member:`` sources do not break the parser.
    """
    if key.startswith("tab:"):
        return key.removeprefix("tab:")
    return key


def filter_new_topics(topics: list[RawTopic], *, last_topic_id: int | None) -> list[RawTopic]:
    """Keep topics with ``topic_id > last_topic_id`` (spec v2ex §4).

    ``last_topic_id is None`` (first run for this source) → keep all. The tab
    page sorts by last-active, not by id, so this scans every topic on the page.
    """
    if last_topic_id is None:
        return list(topics)
    return [t for t in topics if t.topic_id > last_topic_id]


def max_topic_id(topics: list[RawTopic]) -> int | None:
    """Highest topic id in ``topics`` (None when empty) — used to advance the water mark."""
    if not topics:
        return None
    return max(t.topic_id for t in topics)


def select_top_k(items: list[ClassifiedPost], k: int) -> list[ClassifiedPost]:
    """Global top-K selection of interested posts (spec v2ex §7).

    Only ``interested`` posts are candidates. Sort by ``(-score, -replies,
    -topic_id)`` so ties break deterministically (busier topic wins, then newer
    topic wins), then take K.
    """
    interested = [p for p in items if p.interested]
    interested.sort(key=lambda p: (-p.score, -p.topic.replies, -p.topic.topic_id))
    return interested[: max(0, k)]


__all__ = [
    "ClassifiedPost",
    "filter_new_topics",
    "max_topic_id",
    "parse_source",
    "select_top_k",
    "source_key",
]
