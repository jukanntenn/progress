"""Report generation pipeline: aggregation, titling, batching, and publishing."""

import logging
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from .ai import Analyzer
from .config import Config
from .db import save_report
from .db.models import Repository
from .i18n import gettext as _
from .notification import NotificationConfig
from .publish import build_oversize_stub, byte_size, publish_report, publish_monolithic
from .telemetry import record_report_generated
from .templates import render
from .utils.markpost import MarkpostClient
from .utils.timezone import get_now

logger = logging.getLogger(__name__)


# Fraction of markpost.max_batch_size that collected report sections may fill
# within a single batch; the remainder is reserved for the unified summary and
# the aggregated-report template (status block + footer) added during assembly.
BATCH_MARGIN = 0.8


@dataclass
class ReportBatch:
    """A batch of repository reports."""

    reports: list[Any]
    total_size: int
    batch_index: int
    total_batches: int


def create_report_batches(reports: list[Any], max_batch_size: int) -> list[ReportBatch]:
    """Split repository reports into batches by size.

    Args:
        reports: List of RepositoryReport objects
        max_batch_size: Maximum size per batch in bytes

    Returns:
        List of ReportBatch objects

    Notes:
        - Each batch contains at least 1 report
        - If a single report exceeds the effective limit, it gets its own batch
          (and is stubbed or skipped by the caller during upload)
        - Batch size is calculated based on rendered report content
        - Uses BATCH_MARGIN (0.8) to reserve space for summary/template overhead
    """
    if not reports:
        return []

    effective_limit = int(max_batch_size * BATCH_MARGIN)
    logger.info(
        f"Batch size limit: {effective_limit} bytes ({BATCH_MARGIN} * {max_batch_size})"
    )

    batches = []
    current_batch = []
    current_size = 0

    for report in reports:
        report_size = len(report.content.encode("utf-8"))

        if report_size > effective_limit:
            if current_batch:
                batches.append(
                    ReportBatch(
                        reports=current_batch,
                        total_size=current_size,
                        batch_index=len(batches),
                        total_batches=0,
                    )
                )
                current_batch = []
                current_size = 0

            logger.warning(
                f"Report for {report.repo_name} ({report_size} bytes) exceeds "
                f"effective_limit ({effective_limit} bytes)"
            )
            batches.append(
                ReportBatch(
                    reports=[report],
                    total_size=report_size,
                    batch_index=len(batches),
                    total_batches=0,
                )
            )
            continue

        if current_batch and current_size + report_size > effective_limit:
            batches.append(
                ReportBatch(
                    reports=current_batch,
                    total_size=current_size,
                    batch_index=len(batches),
                    total_batches=0,
                )
            )
            current_batch = []
            current_size = 0

        current_batch.append(report)
        current_size += report_size

    if current_batch:
        batches.append(
            ReportBatch(
                reports=current_batch,
                total_size=current_size,
                batch_index=len(batches),
                total_batches=0,
            )
        )

    total_batches = len(batches)
    for batch in batches:
        batch.total_batches = total_batches

    logger.info(
        f"Created {total_batches} batch(es) from {len(reports)} report(s), "
        f"effective_limit={effective_limit} bytes"
    )

    return batches


def add_batch_suffix(title: str, batch_index: int, total_batches: int) -> str:
    if total_batches > 1:
        return f"{title} ({batch_index + 1}/{total_batches})"
    return title


async def generate_title_and_summary(
    analyzer: Analyzer, aggregated_report: str, language: str
) -> tuple[str, str]:
    prompt = render("title_summary_prompt.j2", language=language)
    output = (await analyzer.analyze(content=aggregated_report, prompt=prompt)).strip()
    title = _("Progress Report for Open Source Projects")
    summary = _("A progress report for open source projects.")
    for line in output.split("\n"):
        if line.startswith("TITLE:"):
            title = line[6:].strip()
        elif line.startswith("SUMMARY:"):
            summary = line[8:].strip()
    return title, summary


async def generate_report_title_and_content(
    analyzer: Analyzer, aggregated_report, timezone, language, batch_context=None
):
    batch_index = batch_context.get("batch_index", 0) if batch_context else 0
    total_batches = batch_context.get("total_batches", 1) if batch_context else 1

    try:
        logger.info("Generating title and summary with Claude...")
        title, summary = await generate_title_and_summary(
            analyzer, aggregated_report, language
        )
        final_report = (
            f"{summary.strip()}\n\n{aggregated_report}"
            if summary.strip()
            else aggregated_report
        )

        title = add_batch_suffix(title, batch_index, total_batches)
        logger.info(f"Generated report title: {title}")
        return title, final_report
    except Exception as e:
        logger.warning(
            f"Failed to generate title and summary, using default title: {e}"
        )
        title = _("Progress Report for Open Source Projects - {date}").format(
            date=get_now(timezone).strftime("%Y-%m-%d %H:%M")
        )

        title = add_batch_suffix(title, batch_index, total_batches)
        final_report = f"# {title}\n\n{aggregated_report}"
        return title, final_report


def assemble_batch_body(
    reporter,
    sections: list[str],
    summary: str,
    repo_statuses: dict[str, str],
    total_commits: int,
    timezone,
    batch_index: int,
    total_batches: int,
) -> str:
    body = reporter.render_aggregated_body(
        sections,
        total_commits,
        repo_statuses,
        timezone,
        batch_index,
        total_batches,
    )
    if summary.strip():
        body = f"{summary.strip()}\n\n{body}"
    return body


async def publish_monolithic_report(
    *,
    report_id: int,
    title: str,
    body: str,
    config: Config,
    markpost_client: MarkpostClient | None,
) -> str:
    web_base_url = str(config.web.base_url) if config.web.base_url else None
    return await publish_monolithic(
        report_id=report_id,
        title=title,
        body=body,
        web_base_url=web_base_url,
        max_batch_size=config.markpost.max_batch_size,
        markpost_client=markpost_client,
    )


async def process_reports(
    config: Config,
    check_result,
    reporter,
    timezone,
    analyzer,
    markpost_client,
    notification_config: NotificationConfig,
    *,
    send_notification_fn,
    max_batch_size=None,
):
    success_count, failed_count, skipped_count = check_result.get_status_count()
    logger.info(
        f"Checked {len(check_result.reports)} repositories, "
        f"{check_result.total_commits} commits total "
        f"(success: {success_count}, failed: {failed_count}, skipped: {skipped_count})"
    )

    logger.info("Generating full aggregated report for title/summary...")
    full_sections = [
        reporter.generate_repository_report(report, timezone)
        for report in check_result.reports
    ]
    for report, section in zip(check_result.reports, full_sections):
        report.content = section
    full_aggregated_report = reporter.render_aggregated_body(
        full_sections,
        check_result.total_commits,
        check_result.repo_statuses,
        timezone,
    )

    logger.info("Generating unified title and summary...")
    try:
        unified_title, unified_summary = await generate_title_and_summary(
            analyzer, full_aggregated_report, config.analysis.language
        )
        logger.info(f"Generated unified title: {unified_title}")
    except Exception as e:
        logger.warning(f"Failed to generate title/summary: {e}, using defaults")
        unified_title = _("Progress Report for Open Source Projects - {date}").format(
            date=get_now(timezone).strftime("%Y-%m-%d %H:%M")
        )
        unified_summary = ""

    full_content = (
        f"{unified_summary.strip()}\n\n{full_aggregated_report}"
        if unified_summary.strip()
        else full_aggregated_report
    )

    logger.info("Saving aggregated report to database...")
    try:
        aggregated_report_id = await save_report(
            config=config,
            commit_count=check_result.total_commits,
            markpost_url="",
            content=full_content,
            title=unified_title,
        )
    except Exception as db_error:
        logger.error(f"Failed to save aggregated report: {db_error}")
        return

    logger.info("Saving per-repository reports to database...")
    for report in check_result.reports:
        repo = await Repository.get_or_none(name=report.repo_name)
        if repo:
            try:
                await save_report(
                    config=config,
                    repo_id=repo.id,
                    commit_hash=report.current_commit,
                    previous_commit_hash=report.previous_commit or "",
                    commit_count=report.commit_count,
                    content=report.content,
                )
                record_report_generated(storage="db")
            except Exception as db_error:
                logger.error(
                    f"Failed to save report for {report.repo_name}: {db_error}"
                )

    web_base_url = str(config.web.base_url) if config.web.base_url else None

    if markpost_client is None:
        logger.info("Markpost disabled, skipping upload")
        return

    if max_batch_size:
        batches = create_report_batches(check_result.reports, max_batch_size)
        logger.info(
            f"Split into {len(batches)} batch(es) based on max_batch_size={max_batch_size}"
        )
    else:
        batches = [create_report_batches(check_result.reports, 2**63 - 1)[0]]

    upload_errors = []
    batch_bodies: list[str] = []
    batch_meta: list[Any] = []

    for batch in batches:
        logger.info(
            f"Processing batch {batch.batch_index + 1}/{batch.total_batches} "
            f"({len(batch.reports)} reports, {batch.total_size} bytes)"
        )

        try:
            sections = [report.content for report in batch.reports]
            body = assemble_batch_body(
                reporter,
                sections,
                unified_summary,
                check_result.repo_statuses,
                check_result.total_commits,
                timezone,
                batch.batch_index,
                batch.total_batches,
            )

            if max_batch_size and byte_size(body) > max_batch_size:
                stub = build_oversize_stub(web_base_url, aggregated_report_id)
                if stub is not None and len(batch.reports) == 1:
                    logger.warning(
                        f"Batch {batch.batch_index + 1}: report for "
                        f"{batch.reports[0].repo_name} exceeds the MarkPost size "
                        f"limit ({byte_size(body)} > {max_batch_size} bytes); "
                        f"publishing a WebUI stub"
                    )
                    body = assemble_batch_body(
                        reporter,
                        [stub],
                        unified_summary,
                        check_result.repo_statuses,
                        check_result.total_commits,
                        timezone,
                        batch.batch_index,
                        batch.total_batches,
                    )
                else:
                    reason = (
                        "web.base_url is unset"
                        if stub is None
                        else "multi-repo batch exceeds the size limit"
                    )
                    logger.error(
                        f"Skipping batch {batch.batch_index + 1}: {reason} "
                        f"({byte_size(body)} > {max_batch_size} bytes)"
                    )
                    upload_errors.append(
                        f"Batch {batch.batch_index + 1}: {reason} "
                        f"({byte_size(body)} bytes)"
                    )
                    continue
        except Exception as e:
            logger.error(
                f"Failed to assemble batch {batch.batch_index + 1}: {e}",
                exc_info=True,
            )
            upload_errors.append(f"Batch {batch.batch_index + 1}: {e}")
            continue

        batch_bodies.append(body)
        batch_meta.append(batch)

    result = await publish_report(
        report_id=aggregated_report_id,
        title=unified_title,
        bodies=batch_bodies,
        markpost_client=markpost_client,
    )

    for batch, url in zip(batch_meta, result.batch_urls):
        batch_commit_count = sum(r.commit_count for r in batch.reports)
        summary_text = _(
            "This report covered {count} projects with {commits} commits total"
        ).format(count=len(batch.reports), commits=batch_commit_count)

        batch_repo_statuses = {
            name: status
            for name, status in check_result.repo_statuses.items()
            if any(r.repo_name == name for r in batch.reports)
        }

        logger.info(f"Sending notification for batch {batch.batch_index + 1}...")
        await send_notification_fn(
            notification_config,
            title=_("Progress Report for Open Source Projects"),
            total_commits=batch_commit_count,
            summary=summary_text,
            markpost_url=url,
            repo_statuses=batch_repo_statuses,
            batch_index=batch.batch_index,
            total_batches=batch.total_batches,
        )

    if result.batch_urls:
        logger.info(f"Successfully uploaded {len(result.batch_urls)} batch(es)")
        for i, url in enumerate(result.batch_urls, 1):
            logger.info(f"  Batch {i}: {url}")

    if upload_errors:
        logger.warning(
            f"Encountered {len(upload_errors)} error(s) during batch processing:"
        )
        for error in upload_errors:
            logger.warning(f"  - {error}")
