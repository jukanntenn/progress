from datetime import datetime

import pytz
from fastapi import APIRouter, Request
from fastapi.responses import Response
from feedgen.feed import FeedGenerator

from ...db.models import Report
from ..markdown import render_markdown

router = APIRouter(tags=["rss"])


@router.get("/rss")
def get_rss(request: Request, timezone_str: str = "UTC", language: str = "en"):
    timezone = pytz.timezone(timezone_str)

    fg = FeedGenerator()
    fg.title("Progress Reports")
    fg.link(href=str(request.base_url))
    fg.description("Open source project progress reports")
    fg.language(language)

    reports = (
        Report.select().where(Report.repo.is_null()).order_by(Report.created_at.desc()).limit(50)
    )

    for report in reports:
        fe = fg.add_entry()
        fe.title(report.title or "Untitled Report")
        fe.link(href=f"{request.base_url}report/{report.id}")

        content = render_markdown(report.content or "")
        fe.content(content)

        if report.created_at:
            if isinstance(report.created_at, datetime):
                created_at = report.created_at.astimezone(timezone)
            else:
                created_at = report.created_at
            fe.published(
                created_at.strftime("%a, %d %b %Y %H:%M:%S %Z")
                if isinstance(created_at, datetime)
                else str(created_at)
            )
            fe.updated(
                created_at.strftime("%a, %d %b %Y %H:%M:%S %Z")
                if isinstance(created_at, datetime)
                else str(created_at)
            )

    rss_feed = fg.rss_str(pretty=True)
    return Response(content=rss_feed, media_type="application/rss+xml; charset=utf-8")
