"""Report endpoints (spec 12).

Read-only against the ``reports`` table:

- ``GET /api/v1/reports`` — paginated list of summaries.
- ``GET /api/v1/reports/{id}`` — single report detail, with rendered HTML.
- ``GET /api/v1/reports/{id}/raw`` — raw markdown body.

Per spec 12, every response declares a ``response_model`` so OpenAPI is the
single source of truth for the frontend types. Rate limiting is wired through
the shared ``limiter`` instance registered by :mod:`progress.api.routes`.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from progress.api.auth import get_current_user
from progress.api.markdown import render_markdown
from progress.api.routes._limiter import limiter
from progress.api.schemas import (
    PaginatedResponse,
    RawMarkdownResponse,
    ReportDetail,
    ReportSummary,
)
from progress.db.models.report import Report

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reports"], dependencies=[Depends(get_current_user)])


@router.get(
    "/reports",
    response_model=PaginatedResponse[ReportSummary],
    status_code=status.HTTP_200_OK,
)
@limiter.limit("60 per minute")
async def list_reports(
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    report_type: Annotated[str | None, Query()] = None,
) -> PaginatedResponse[ReportSummary]:
    """Paginated list of report summaries (newest first)."""
    qs = Report.filter(repo_id__isnull=True).order_by("-created_at")
    if report_type:
        qs = qs.filter(report_type=report_type)
    total = await qs.count()
    offset = (page - 1) * page_size
    rows = await qs.offset(offset).limit(page_size)
    items = [ReportSummary.model_validate(_serialize_row(r)) for r in rows]
    return PaginatedResponse[ReportSummary](
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        has_next=(offset + page_size) < total,
    )


@router.get(
    "/reports/{report_id}",
    response_model=ReportDetail,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("120 per minute")
async def get_report(request: Request, report_id: int) -> ReportDetail:
    """Single report detail with rendered HTML (spec 12)."""
    row = await Report.get_or_none(id=report_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"report {report_id} not found")
    payload = _serialize_row(row)
    payload["content"] = row.content or ""
    payload["rendered_html"] = render_markdown(row.content or "")
    return ReportDetail.model_validate(payload)


@router.get(
    "/reports/{report_id}/raw",
    response_model=RawMarkdownResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("120 per minute")
async def get_report_raw(request: Request, report_id: int) -> RawMarkdownResponse:
    """Raw markdown body for the report (spec 12)."""
    row = await Report.get_or_none(id=report_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"report {report_id} not found")
    return RawMarkdownResponse(
        id=row.id,
        report_type=row.report_type,
        title=row.title,
        markdown=row.content or "",
    )


def _serialize_row(row: Report) -> dict:  # ty:ignore[missing-type-argument]
    """Flatten a Report row into a JSON-friendly dict (no content — summary only)."""
    return {
        "id": row.id,
        "report_type": row.report_type,
        "title": row.title,
        "commit_hash": row.commit_hash,
        "previous_commit_hash": row.previous_commit_hash,
        "commit_count": row.commit_count,
        "markpost_url": row.markpost_url,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


__all__ = ["router"]
