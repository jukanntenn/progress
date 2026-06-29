"""MarkPost publishing: size-aware batching, WebUI stubs, and Report/Batch rows.

The database always stores the complete, unstubbed report (there is no size
limit). MarkPost rejects bodies over ``markpost.max_batch_size``, so a report
may be split into multiple batches (each uploaded as its own post) or, when
even a single batch is too large, replaced by a short stub linking back to the
full report in the WebUI.

Persistence follows the rule agreed with the sibling ``feeber`` project:

- one successful upload  -> ``Report.markpost_url`` = that URL, no Batch rows
- several uploads        -> ``Report.markpost_url`` = "" plus one Batch row per
                            upload (``seq`` from 1, clean title without "(n/m)")
- no upload              -> ``Report.markpost_url`` stays ""

The "(n/m)" sequence suffix is a presentation concern for the MarkPost post
title only; it is never stored on the ``Batch`` row.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .db.models import Batch, Report
from .i18n import gettext as _
from .utils.markpost import MarkpostClient

logger = logging.getLogger(__name__)


def byte_size(text: str) -> int:
    """UTF-8 byte length of ``text`` (MarkPost sizes bodies in bytes)."""
    return len(text.encode("utf-8"))


def build_report_url(web_base_url: str | None, report_id: int) -> str:
    """Absolute WebUI URL of the report detail page."""
    return f"{str(web_base_url).rstrip('/')}/report/{report_id}"


def build_oversize_stub(web_base_url: str | None, report_id: int) -> str | None:
    """Markdown stub linking to the full report in the WebUI.

    Returns None when no ``web_base_url`` is configured, signalling that the
    caller cannot stub and must fall back to skipping the upload.
    """
    if not web_base_url:
        return None
    url = build_report_url(web_base_url, report_id)
    return _(
        "> ⚠️ This content is too large to publish here. "
        "[View the complete report in the WebUI]({url})."
    ).format(url=url)


@dataclass
class PublishResult:
    """Outcome of :func:`publish_report`."""

    markpost_url: str
    batch_urls: list[str]


def publish_report(
    *,
    report_id: int,
    title: str,
    bodies: list[str],
    markpost_client: MarkpostClient | None,
) -> PublishResult:
    """Upload ``bodies`` to MarkPost and persist Report/Batch rows.

    The ``Report`` row must already exist (created by the caller with the full,
    unstubbed content and ``markpost_url=""``). Each body is uploaded as a
    separate MarkPost post. Failed uploads are skipped; the rest are persisted
    per the single/multi rule described in the module docstring.
    """
    if markpost_client is None or not bodies:
        return PublishResult(markpost_url="", batch_urls=[])

    urls: list[str] = []
    total = len(bodies)
    for idx, body in enumerate(bodies):
        batch_title = f"{title} ({idx + 1}/{total})" if total > 1 else title
        try:
            url = markpost_client.upload(body, title=batch_title)
            urls.append(url)
        except Exception as exc:
            logger.warning(
                "Batch %d/%d upload failed, continuing with remaining batches: %s",
                idx + 1,
                total,
                exc,
            )

    if len(urls) <= 1:
        markpost_url = urls[0] if urls else ""
    else:
        markpost_url = ""
        for seq, url in enumerate(urls, start=1):
            Batch.create(
                report=report_id,
                title=title,
                markpost_url=url,
                seq=seq,
            )

    Report.update(markpost_url=markpost_url).where(Report.id == report_id).execute()
    logger.info(
        "Published report %s: %d/%d batch(es) uploaded (markpost_url=%r)",
        report_id,
        len(urls),
        total,
        markpost_url,
    )
    return PublishResult(markpost_url=markpost_url, batch_urls=urls)


def publish_monolithic(
    *,
    report_id: int,
    title: str,
    body: str,
    web_base_url: str | None,
    max_batch_size: int,
    markpost_client: MarkpostClient | None,
) -> str:
    """Publish a single-body report, stubbing it when it exceeds the size limit.

    Used by the non-aggregated report paths (discovered repos, proposals,
    changelogs) whose body is the final MarkPost content. Returns the resulting
    ``Report.markpost_url``: the upload URL, the stub URL, or "" when MarkPost
    is disabled or the oversized report could not be stubbed.
    """
    if markpost_client is None:
        return ""

    if byte_size(body) <= max_batch_size:
        bodies = [body]
    else:
        stub = build_oversize_stub(web_base_url, report_id)
        if stub is None:
            logger.warning(
                "Report %s exceeds the MarkPost size limit (%d > %d bytes) and "
                "web.base_url is unset; skipping upload",
                report_id,
                byte_size(body),
                max_batch_size,
            )
            return ""
        logger.info(
            "Report %s exceeds the MarkPost size limit (%d > %d bytes); "
            "publishing a WebUI stub instead of the body",
            report_id,
            byte_size(body),
            max_batch_size,
        )
        bodies = [stub]

    result = publish_report(
        report_id=report_id,
        title=title,
        bodies=bodies,
        markpost_client=markpost_client,
    )
    return result.markpost_url


__all__ = [
    "PublishResult",
    "build_oversize_stub",
    "build_report_url",
    "byte_size",
    "publish_monolithic",
    "publish_report",
]
