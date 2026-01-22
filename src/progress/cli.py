"""CLI main entry point."""

import logging

import click

from .analyzer import ClaudeCodeAnalyzer
from .config import Config
from .consts import DATABASE_PATH
from .db import close_db, create_tables, init_db, save_report
from .errors import ProgressException
from .i18n import initialize, gettext as _
from .log import setup as setup_log
from .markpost import MarkpostClient
from .models import Repository
from .notification import NotificationManager, NotificationMessage
from .reporter import MarkdownReporter
from .repository import RepositoryManager
from .utils import get_now

logger = logging.getLogger(__name__)


def initialize_components(cfg):
    """Initialize application components from configuration."""
    init_db(DATABASE_PATH)
    create_tables()

    notification_manager = NotificationManager.from_config(cfg.notification)
    markpost_client = MarkpostClient(cfg.markpost)

    analyzer = ClaudeCodeAnalyzer(
        max_diff_length=cfg.analysis.max_diff_length,
        timeout=cfg.analysis.timeout,
        language=cfg.analysis.language,
    )
    reporter = MarkdownReporter()

    repo_manager = RepositoryManager(analyzer, reporter, cfg)

    return notification_manager, markpost_client, repo_manager, reporter


def generate_report_title_and_content(
    analyzer, aggregated_report, timezone, batch_context=None
):
    """Generate report title and final content using analyzer or fallback to default.

    Args:
        analyzer: ClaudeCodeAnalyzer instance
        aggregated_report: Complete aggregated markdown report
        timezone: Timezone for timestamps
        batch_context: Optional dict with batch info:
            - batch_index: int (0-based)
            - total_batches: int
    """
    try:
        logger.info("Generating title and summary with Claude...")
        title, summary = analyzer.generate_title_and_summary(aggregated_report)
        final_report = (
            f"{summary.strip()}\n\n{aggregated_report}"
            if summary.strip()
            else aggregated_report
        )

        if batch_context and batch_context.get("total_batches", 1) > 1:
            batch_index = batch_context.get("batch_index", 0)
            total_batches = batch_context.get("total_batches", 1)
            title = f"{title} ({batch_index + 1}/{total_batches})"

        logger.info(f"Generated report title: {title}")
        return title, final_report
    except Exception as e:
        logger.warning(
            f"Failed to generate title and summary, using default title: {e}"
        )
        title = _("Progress Report for Open Source Projects - {date}").format(
            date=get_now(timezone).strftime("%Y-%m-%d %H:%M")
        )

        if batch_context and batch_context.get("total_batches", 1) > 1:
            batch_index = batch_context.get("batch_index", 0)
            total_batches = batch_context.get("total_batches", 1)
            title = f"{title} ({batch_index + 1}/{total_batches})"

        final_report = f"# {title}\n\n{aggregated_report}"
        return title, final_report


def process_reports(
    check_result,
    reporter,
    timezone,
    analyzer,
    markpost_client,
    notification_manager,
    max_batch_size=None,
):
    """Process and upload repository reports with batch support.

    Args:
        check_result: CheckAllResult from repository check
        reporter: MarkdownReporter instance
        timezone: Timezone for timestamps
        analyzer: ClaudeCodeAnalyzer instance
        markpost_client: MarkpostClient instance
        notification_manager: NotificationManager instance
        max_batch_size: Maximum batch size in bytes (from config)

    Note:
        - Splits reports into batches if total size exceeds max_batch_size
        - Each batch generates independent title/summary and uploads separately
        - Database save always succeeds even if uploads fail
        - Partial upload failure is handled gracefully
    """
    from .utils import create_report_batches

    success_count, failed_count, skipped_count = check_result.get_status_count()
    logger.info(
        f"Checked {len(check_result.reports)} repositories, "
        f"{check_result.total_commits} commits total "
        f"(success: {success_count}, failed: {failed_count}, skipped: {skipped_count})"
    )

    if max_batch_size:
        batches = create_report_batches(check_result.reports, max_batch_size)
        logger.info(
            f"Split into {len(batches)} batch(es) based on max_batch_size={max_batch_size}"
        )
    else:
        batches = [create_report_batches(check_result.reports, 2**63 - 1)[0]]

    uploaded_urls = []
    upload_errors = []

    for batch in batches:
        try:
            logger.info(
                f"Processing batch {batch.batch_index + 1}/{batch.total_batches} "
                f"({len(batch.reports)} reports, {batch.total_size} bytes)"
            )

            batch_report = reporter.generate_aggregated_report(
                batch.reports,
                check_result.total_commits,
                check_result.repo_statuses,
                timezone,
            )

            batch_context = {
                "batch_index": batch.batch_index,
                "total_batches": batch.total_batches,
            }
            title, final_report = generate_report_title_and_content(
                analyzer, batch_report, timezone, batch_context
            )

            first_report = batch.reports[0]
            report_size = len(first_report.content.encode("utf-8"))
            is_oversized = (
                max_batch_size is not None
                and len(batch.reports) == 1
                and report_size > max_batch_size
            )

            if is_oversized:
                logger.error(
                    f"Skipping upload for batch {batch.batch_index + 1}: "
                    f"single report exceeds max_batch_size ({report_size} > {max_batch_size})"
                )
                upload_errors.append(
                    f"Batch {batch.batch_index + 1}: Report for {first_report.repo_name} "
                    f"exceeds size limit ({report_size} bytes)"
                )
                markpost_url = None
            else:
                logger.info(
                    f"Uploading batch {batch.batch_index + 1}/{batch.total_batches} to Markpost..."
                )
                markpost_url = markpost_client.upload_batch(
                    final_report,
                    title,
                    batch_index=batch.batch_index,
                    total_batches=batch.total_batches,
                )
                logger.info(f"Batch {batch.batch_index + 1} uploaded: {markpost_url}")
                uploaded_urls.append(markpost_url)

            logger.info("Saving batch reports to database...")
            for report in batch.reports:
                repo = Repository.get_or_none(
                    Repository.name == report.repo_name
                )
                if repo:
                    save_report(
                        repo_id=repo.id,
                        commit_hash=report.current_commit,
                        previous_commit_hash=report.previous_commit or "",
                        commit_count=report.commit_count,
                        markpost_url=markpost_url,
                        content=report.content,
                    )
            logger.info(f"Saved {len(batch.reports)} reports to database")

        except Exception as e:
            error_msg = f"Batch {batch.batch_index + 1}: {str(e)}"
            logger.error(
                f"Failed to process batch {batch.batch_index + 1}: {e}",
                exc_info=True,
            )
            upload_errors.append(error_msg)

            for report in batch.reports:
                repo = Repository.get_or_none(
                    Repository.name == report.repo_name
                )
                if repo:
                    try:
                        save_report(
                            repo_id=repo.id,
                            commit_hash=report.current_commit,
                            previous_commit_hash=report.previous_commit or "",
                            commit_count=report.commit_count,
                            markpost_url=None,
                            content=report.content,
                        )
                    except Exception as db_error:
                        logger.error(
                            f"Failed to save report for {report.repo_name}: {db_error}"
                        )

    if uploaded_urls:
        logger.info(f"Successfully uploaded {len(uploaded_urls)} batch(es)")
        for i, url in enumerate(uploaded_urls, 1):
            logger.info(f"  Batch {i}: {url}")

    if upload_errors:
        logger.warning(
            f"Encountered {len(upload_errors)} error(s) during batch processing:"
        )
        for error in upload_errors:
            logger.warning(f"  - {error}")

    summary_text = _(
        "This report covered {count} projects with {commits} commits total"
    ).format(
        count=len(check_result.reports), commits=check_result.total_commits
    )

    notification_url = uploaded_urls[0] if uploaded_urls else None

    logger.info("Sending notifications...")
    notification_manager.send(
        NotificationMessage(
            title=_("Progress Report for Open Source Projects"),
            total_commits=check_result.total_commits,
            summary=summary_text,
            markpost_url=notification_url,
            repo_statuses=check_result.repo_statuses,
        )
    )


@click.command()
@click.option("--config", "-c", default="config.toml", help="Configuration file path")
def main(config: str):
    """Progress Tracker - GitHub code change tracking tool."""
    setup_log()

    try:
        logger.info(f"Loading configuration file: {config}")
        cfg = Config.load_from_file(config)

        initialize(ui_language=cfg.language)

        notification_manager, markpost_client, repo_manager, reporter = initialize_components(cfg)

        sync_result = repo_manager.sync(cfg.repos)
        logger.info(f"Sync completed: {sync_result}")

        repos = repo_manager.list_enabled()
        logger.info(f"Starting to check {len(repos)} repositories")

        check_result = repo_manager.check_all(
            repos, concurrency=cfg.analysis.concurrency
        )

        if check_result.reports:
            process_reports(
                check_result,
                reporter,
                cfg.get_timezone(),
                repo_manager.analyzer,
                markpost_client,
                notification_manager,
                max_batch_size=cfg.markpost.max_batch_size,
            )
        else:
            logger.info(
                _("No repositories with new changes, skipping report generation")
            )

        logger.info(_("All repository checks completed"))

    except ProgressException as e:
        logger.error(f"Application error: {e}", exc_info=True)
        raise click.ClickException(str(e))
    except Exception as e:
        logger.error(f"Program execution failed: {e}", exc_info=True)
        raise click.ClickException(str(e))
    finally:
        close_db()


if __name__ == "__main__":
    main()
