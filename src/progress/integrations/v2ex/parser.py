"""Pure HTML parser for V2EX tab pages (spec v2ex §2).

``parse_tab_page`` turns a tab page's HTML (``GET /?tab=<id>``) into a list of
:class:`RawTopic` — decoded plain text, no HTML tags. It is a pure function
(no IO), so it is unit-testable with a captured fixture. Selectors were
verified against the live V2EX markup.

The tab page sorts topics by last-active (a new reply bumps a topic), NOT by
topic id, so the newest-created topic can sit anywhere in the 50-item list —
callers must scan the whole page and dedup by monotonic topic id (see
:func:`progress.integrations.v2ex.fetcher.filter_new_topics`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import re

import lxml.html

logger = logging.getLogger(__name__)

_TOPIC_ID_RE = re.compile(r"/t/(\d+)")
_REPLY_ANCHOR_RE = re.compile(r"#reply(\d+)")


@dataclass(frozen=True)
class RawTopic:
    """Normalised metadata for one V2EX topic shown on a tab page.

    All text fields are decoded plain text (lxml has already restored HTML
    entities like ``&amp;`` → ``&``), safe to feed to the AI and render.
    ``created_at`` is an aware UTC datetime (converted from the ``+08:00`` title
    attribute). ``last_replier`` is ``""`` for 0-reply topics (no such segment).
    """

    topic_id: int
    title: str
    node_slug: str
    node_name: str
    author: str
    created_at: datetime
    replies: int
    last_replier: str
    url: str
    source: str


def _strip(text: str | None) -> str:
    return (text or "").strip()


def parse_tab_page(
    html: str,
    *,
    source: str,
    base_url: str = "https://www.v2ex.com",
) -> list[RawTopic]:
    """Parse a V2EX tab page into normalised :class:`RawTopic` records.

    Malformed rows (missing topic id / title) are skipped with a warning rather
    than aborting the whole page — a partial parse beats no parse. A failed
    timestamp is non-fatal: the topic is kept with ``created_at = now(UTC)``.
    """
    tree = lxml.html.fromstring(html)
    cells = tree.xpath('//div[contains(@class, "cell") and contains(@class, "item")]')
    topics: list[RawTopic] = []
    for cell in cells:
        topic = _parse_cell(cell, source=source, base_url=base_url)
        if topic is not None:
            topics.append(topic)
    return topics


def _parse_cell(cell, *, source: str, base_url: str) -> RawTopic | None:
    title_a = cell.xpath('.//span[@class="item_title"]/a')
    if not title_a:
        return None
    title_anchor = title_a[0]
    topic_id = _topic_id_from_anchor(title_anchor)
    if topic_id is None:
        logger.warning("v2ex parser: cell without parseable topic id; skipping")
        return None
    title = _strip(title_anchor.text_content())
    if not title:
        return None

    node_slug, node_name = _node(cell)
    author = _author(cell)
    created_at = _created_at(cell)
    replies = _replies(cell, title_anchor)
    last_replier = _last_replier(cell)

    return RawTopic(
        topic_id=topic_id,
        title=title,
        node_slug=node_slug,
        node_name=node_name,
        author=author,
        created_at=created_at,
        replies=replies,
        last_replier=last_replier,
        url=f"{base_url}/t/{topic_id}",
        source=source,
    )


def _topic_id_from_anchor(anchor) -> int | None:
    raw_id = anchor.get("id", "")
    if raw_id.startswith("topic-link-"):
        digits = raw_id.removeprefix("topic-link-")
        if digits.isdigit():
            return int(digits)
    match = _TOPIC_ID_RE.search(anchor.get("href", ""))
    return int(match.group(1)) if match else None


def _node(cell) -> tuple[str, str]:
    node_a = cell.xpath('.//span[@class="topic_info"]/a[@class="node"]')
    if not node_a:
        return "", ""
    slug = (node_a[0].get("href") or "").replace("/go/", "")
    return slug, _strip(node_a[0].text_content())


def _author(cell) -> str:
    author_a = cell.xpath('.//span[@class="topic_info"]/strong/a')
    return _strip(author_a[0].text_content()) if author_a else ""


def _created_at(cell) -> datetime:
    ts_span = cell.xpath('.//span[@class="topic_info"]/span[@title]')
    if not ts_span:
        return datetime.now(UTC)
    raw = _strip(ts_span[0].get("title"))
    try:
        return datetime.fromisoformat(raw).astimezone(UTC)
    except (ValueError, TypeError):
        return datetime.now(UTC)


def _replies(cell, title_anchor) -> int:
    count = cell.xpath('.//a[@class="count_livid"]/text()')
    if count and _strip(count[0]).isdigit():
        return int(_strip(count[0]))
    match = _REPLY_ANCHOR_RE.search(title_anchor.get("href", ""))
    if match:
        return int(match.group(1))
    return 0


def _last_replier(cell) -> str:
    info = cell.xpath('.//span[@class="topic_info"]')
    if not info or "最后回复来自" not in info[0].text_content():
        return ""
    repliers = cell.xpath('.//span[@class="topic_info"]/strong/a')
    return _strip(repliers[-1].text_content()) if repliers else ""


__all__ = ["RawTopic", "parse_tab_page"]
