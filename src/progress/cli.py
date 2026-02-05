"""CLI main entry point."""

import logging

import click

from .analyzer import ClaudeCodeAnalyzer
from .config import Config
from .consts import DATABASE_PATH
from .db import close_db, create_tables, init_db, save_report
from .errors import ProgressException
from .i18n import gettext as _
from .i18n import initialize
from .log import setup as setup_log
from .markpost import MarkpostClient
from .models import Repository
from .notification import NotificationManager, NotificationMessage
from .reporter import MarkdownReporter
from .repository import RepositoryManager
from .utils import get_now
from .web import create_app

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


def add_batch_suffix(title: str, batch_index: int, total_batches: int) -> str:
    """Add batch suffix to title if multiple batches exist.

    Args:
        title: Original title
        batch_index: Current batch index (0-based)
        total_batches: Total number of batches

    Returns:
        Title with batch suffix if total_batches > 1, otherwise original title
    """
    if total_batches > 1:
        return f"{title} ({batch_index + 1}/{total_batches})"
    return title


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
    batch_index = batch_context.get("batch_index", 0) if batch_context else 0
    total_batches = batch_context.get("total_batches", 1) if batch_context else 1

    try:
        logger.info("Generating title and summary with Claude...")
        title, summary = analyzer.generate_title_and_summary(aggregated_report)
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
        - Generates single unified title/summary from full aggregated report
        - Splits reports into batches if total size exceeds max_batch_size
        - Each batch uses the same unified title and summary
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

    logger.info("Generating full aggregated report for title/summary...")
    full_aggregated_report = reporter.generate_aggregated_report(
        check_result.reports,
        check_result.total_commits,
        check_result.repo_statuses,
        timezone,
    )

    logger.info("Generating unified title and summary...")
    try:
        unified_title, unified_summary = analyzer.generate_title_and_summary(
            full_aggregated_report
        )
        logger.info(f"Generated unified title: {unified_title}")
    except Exception as e:
        logger.warning(f"Failed to generate title/summary: {e}, using defaults")
        unified_title = _("Progress Report for Open Source Projects - {date}").format(
            date=get_now(timezone).strftime("%Y-%m-%d %H:%M")
        )
        unified_summary = ""

    if max_batch_size:
        batches = create_report_batches(check_result.reports, max_batch_size)
        logger.info(
            f"Split into {len(batches)} batch(es) based on max_batch_size={max_batch_size}"
        )
    else:
        batches = [create_report_batches(check_result.reports, 2**63 - 1)[0]]

    uploaded_urls = []
    upload_errors = []
    first_batch_url = None

    for batch in batches:
        markpost_url = None

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
                batch_index=batch.batch_index,
                total_batches=batch.total_batches,
            )

            final_report = batch_report
            if unified_summary.strip():
                final_report = f"{unified_summary.strip()}\n\n{batch_report}"

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
            else:
                logger.info(
                    f"Uploading batch {batch.batch_index + 1}/{batch.total_batches} to Markpost..."
                )
                markpost_url = markpost_client.upload_batch(
                    final_report,
                    unified_title,
                    batch_index=batch.batch_index,
                    total_batches=batch.total_batches,
                )
                logger.info(f"Batch {batch.batch_index + 1} uploaded: {markpost_url}")
                uploaded_urls.append(markpost_url)
                if batch.batch_index == 0:
                    first_batch_url = markpost_url

        except Exception as e:
            error_msg = f"Batch {batch.batch_index + 1}: {str(e)}"
            logger.error(
                f"Failed to process batch {batch.batch_index + 1}: {e}",
                exc_info=True,
            )
            upload_errors.append(error_msg)

        logger.info("Saving batch reports to database...")
        for report in batch.reports:
            repo = Repository.get_or_none(Repository.name == report.repo_name)
            if repo:
                try:
                    save_report(
                        repo_id=repo.id,
                        commit_hash=report.current_commit,
                        previous_commit_hash=report.previous_commit or "",
                        commit_count=report.commit_count,
                        markpost_url="",
                        content=report.content,
                        title="",
                    )
                except Exception as db_error:
                    logger.error(
                        f"Failed to save report for {report.repo_name}: {db_error}"
                    )
        logger.info(f"Saved {len(batch.reports)} reports to database")

        if markpost_url:
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
            notification_manager.send(
                NotificationMessage(
                    title=_("Progress Report for Open Source Projects"),
                    total_commits=batch_commit_count,
                    summary=summary_text,
                    markpost_url=markpost_url,
                    repo_statuses=batch_repo_statuses,
                    batch_index=batch.batch_index,
                    total_batches=batch.total_batches,
                )
            )

    logger.info("Saving aggregated report to database...")
    try:
        aggregated_report_with_summary = full_aggregated_report
        if unified_summary.strip():
            aggregated_report_with_summary = (
                f"{unified_summary.strip()}\n\n{full_aggregated_report}"
            )

        aggregated_markpost_url = first_batch_url if len(batches) == 1 else ""
        save_report(
            repo_id=None,
            commit_hash="",
            previous_commit_hash="",
            commit_count=check_result.total_commits,
            markpost_url=aggregated_markpost_url,
            content=aggregated_report_with_summary,
            title=unified_title,
        )
        logger.info("Aggregated report saved to database")
    except Exception as db_error:
        logger.error(f"Failed to save aggregated report: {db_error}")

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


@click.group(invoke_without_command=True)
@click.option("--config", "-c", default="config.toml", help="Configuration file path")
@click.pass_context
def cli(ctx, config: str):
    """Progress Tracker - GitHub code change tracking tool."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    setup_log()

    if ctx.invoked_subcommand is None:
        ctx.invoke(check)


@cli.command(name="check")
@click.pass_context
def check(ctx):
    """Run repository checks and generate reports."""
    config = ctx.obj["config_path"]
    _run_check_command(config)


def _run_check_command(config: str):
    """Run the main check command logic."""
    try:
        logger.info(f"Loading configuration file: {config}")
        cfg = Config.load_from_file(config)

        initialize(ui_language=cfg.language)

        notification_manager, markpost_client, repo_manager, reporter = (
            initialize_components(cfg)
        )

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


@cli.command(name="serve")
@click.option("--host", "-h", default=None, help="Override host from config")
@click.option("--port", "-p", default=None, type=int, help="Override port from config")
@click.option(
    "--debug/--no-debug",
    default=None,
    help="Enable/disable debug mode (auto-enable in dev)",
)
@click.pass_context
def serve(ctx, host, port, debug):
    """Start development server with hot reload."""
    config_path = ctx.obj["config_path"]

    try:
        logger.info(f"Loading configuration file: {config_path}")
        cfg = Config.load_from_file(config_path)

        initialize(ui_language=cfg.language)

        host = host or cfg.web.host
        port = port or cfg.web.port

        if debug is None:
            debug = True

        if debug:
            logger.warning(
                "Debug mode is enabled. This should NOT be used in production."
            )
            if not hasattr(cfg.web, "debug") or not cfg.web.debug:
                logger.warning(
                    "Consider setting [web] debug = true in config.toml for development."
                )

        app = create_app(cfg)

        logger.info(f"Starting development server on {host}:{port}")
        logger.info(f"Debug mode: {'enabled' if debug else 'disabled'}")
        logger.info(f"Hot reload: {'enabled' if debug else 'disabled'}")

        app.run(host=host, port=port, debug=debug, use_reloader=debug)

    except ProgressException as e:
        logger.error(f"Application error: {e}", exc_info=True)
        raise click.ClickException(str(e))
    except Exception as e:
        logger.error(f"Program execution failed: {e}", exc_info=True)
        raise click.ClickException(str(e))


def main():
    """Legacy main function for backward compatibility."""
    cli(obj={})


if __name__ == "__main__":
    main()
