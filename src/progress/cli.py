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


def generate_report_title_and_content(analyzer, aggregated_report, timezone):
    """Generate report title and final content using analyzer or fallback to default."""
    try:
        logger.info("Generating title and summary with Claude...")
        title, summary = analyzer.generate_title_and_summary(aggregated_report)
        final_report = (
            f"{summary.strip()}\n\n{aggregated_report}"
            if summary.strip()
            else aggregated_report
        )
        logger.info(f"Generated report title: {title}")
        return title, final_report
    except Exception as e:
        logger.warning(
            f"Failed to generate title and summary, using default title: {e}"
        )
        title = _("Progress Report for Open Source Projects - {date}").format(
            date=get_now(timezone).strftime("%Y-%m-%d %H:%M")
        )
        final_report = f"# {title}\n\n{aggregated_report}"
        return title, final_report


def process_reports(check_result, reporter, timezone, analyzer, markpost_client, notification_manager):
    """Process and upload repository reports."""
    success_count, failed_count, skipped_count = check_result.get_status_count()
    logger.info(
        f"Checked {len(check_result.reports)} repositories, "
        f"{check_result.total_commits} commits total "
        f"(success: {success_count}, failed: {failed_count}, skipped: {skipped_count})"
    )

    aggregated_report = reporter.generate_aggregated_report(
        check_result.reports,
        check_result.total_commits,
        check_result.repo_statuses,
        timezone,
    )

    title, final_report = generate_report_title_and_content(
        analyzer, aggregated_report, timezone
    )

    logger.info("Uploading aggregated report to Markpost...")
    markpost_url = markpost_client.upload(final_report, title)
    logger.info(f"Report uploaded: {markpost_url}")

    logger.info("Saving reports to database...")
    for report in check_result.reports:
        repo = Repository.get_or_none(Repository.name == report.repo_name)
        if repo:
            save_report(
                repo_id=repo.id,
                commit_hash=report.current_commit,
                previous_commit_hash=report.previous_commit or "",
                commit_count=report.commit_count,
                markpost_url=markpost_url,
                content=report.content,
            )
    logger.info(f"Saved {len(check_result.reports)} reports to database")

    summary_text = _(
        "This report covered {count} projects with {commits} commits total"
    ).format(
        count=len(check_result.reports), commits=check_result.total_commits
    )
    logger.info("Sending notifications...")
    notification_manager.send(
        NotificationMessage(
            title=_("Progress Report for Open Source Projects"),
            total_commits=check_result.total_commits,
            summary=summary_text,
            markpost_url=markpost_url,
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
