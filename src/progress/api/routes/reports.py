from datetime import datetime

import pytz
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...db.models import Report
from ..markdown import render_markdown

router = APIRouter(prefix="/reports", tags=["reports"])

PAGE_SIZE = 10


class ReportResponse(BaseModel):
    id: int
    title: str | None
    created_at: str
    markpost_url: str | None


class ReportDetailResponse(BaseModel):
    id: int
    title: str | None
    created_at: str
    markpost_url: str | None
    content: str


class PaginatedReportsResponse(BaseModel):
    reports: list[ReportResponse]
    page: int
    total_pages: int
    total: int
    has_prev: bool
    has_next: bool


def format_datetime(dt, timezone) -> str:
    if dt is None:
        return ""
    if isinstance(dt, datetime):
        return dt.astimezone(timezone).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(dt, str):
        try:
            parsed = datetime.fromisoformat(dt)
            return parsed.astimezone(timezone).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return dt
    return str(dt)


@router.get("", response_model=PaginatedReportsResponse)
async def list_reports(page: int = 1, timezone_str: str = "UTC"):
    timezone = pytz.timezone(timezone_str)

    if page < 1:
        page = 1

    query = Report.filter(repo_id__isnull=True).order_by("-created_at")
    total = await query.count()
    # Preserve peewee's 1-indexed .paginate(page, size) semantics.
    reports = await query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)

    report_list = [
        ReportResponse(
            id=report.id,
            title=report.title,
            created_at=format_datetime(report.created_at, timezone),
            markpost_url=report.markpost_url,
        )
        for report in reports
    ]

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE or 1

    return PaginatedReportsResponse(
        reports=report_list,
        page=page,
        total_pages=total_pages,
        total=total,
        has_prev=page > 1,
        has_next=page < total_pages,
    )


@router.get("/{report_id}", response_model=ReportDetailResponse)
async def get_report(report_id: int, timezone_str: str = "UTC"):
    timezone = pytz.timezone(timezone_str)

    report = await Report.get_or_none(id=report_id)
    if report is None or report.repo_id is not None:  # ty: ignore[unresolved-attribute]  # tortoise exposes repo_id as the raw FK column; not in the model stubs
        raise HTTPException(status_code=404, detail="Report not found")

    return ReportDetailResponse(
        id=report.id,
        title=report.title,
        created_at=format_datetime(report.created_at, timezone),
        markpost_url=report.markpost_url,
        content=render_markdown(report.content or ""),
    )
