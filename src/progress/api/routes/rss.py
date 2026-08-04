"""RSS feed endpoint (spec 12).

``GET /api/v1/rss`` returns an RSS 2.0 feed of the most recent reports.
Uses ``feedgen`` (see ``.local/contexts/feedgen/feedgen/feed.py``) for XML
generation — same library the CLI used historically.

Per spec 09, feed content is nh3-sanitized markdown before being placed in
``<description>`` so a stored-XSS payload in a report cannot escape into a
reader that renders the field as HTML.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import Response
from feedgen.feed import FeedGenerator

from progress.api.deps import get_config
from progress.config.root import CoreConfig
from progress.db.models.report import Report
from progress.utils.i18n import get_locale, gettext as _
from progress.utils.markdown import render_markdown

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rss"])

DEFAULT_FEED_SIZE = 50
MAX_FEED_SIZE = 200


def _as_utc(value: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (assume UTC if naive)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@router.get(
    "/rss",
    response_class=Response,
    status_code=status.HTTP_200_OK,
)
async def get_rss(
    request: Request,
    cfg: Annotated[CoreConfig, Depends(get_config)],
    limit: Annotated[int, Query(ge=1, le=MAX_FEED_SIZE)] = DEFAULT_FEED_SIZE,
) -> Response:
    """RSS 2.0 feed of the most recent reports."""

    feed = FeedGenerator()
    base_url = (cfg.web.base_url or str(request.base_url)).rstrip("/")
    feed.title(_("Progress reports"))
    feed.description(_("Tracked GitHub repository changes and analyses"))
    feed.language(get_locale())
    feed.link(href=base_url, rel="self")
    feed.id(base_url)

    rows = await Report.all().order_by("-created_at").limit(limit)
    latest_updated = datetime.now(UTC)
    for row in rows:
        entry = feed.add_entry()
        entry.title(row.title or f"report #{row.id}")
        url = row.markpost_url or f"{base_url}/api/v1/reports/{row.id}"
        entry.link(href=url)
        entry.id(str(row.id))
        entry.description(render_markdown((row.content or "")[:280]))
        if row.created_at:
            published = _as_utc(row.created_at)
            entry.published(published)
            latest_updated = max(latest_updated, published)
    feed.updated(latest_updated)

    body = feed.rss_str(pretty=False)
    return Response(content=body, media_type="application/rss+xml; charset=utf-8")


__all__ = ["router"]
