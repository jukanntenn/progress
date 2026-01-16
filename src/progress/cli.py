"""CLI main entry point."""

import logging

import click
import requests

from .analyzer import ClaudeCodeAnalyzer
from .config import Config
from .consts import DATABASE_PATH, TIMEOUT_HTTP_REQUEST
from .db import close_db, create_tables, init_db, save_report
from .errors import ProgressException
from .i18n import initialize, gettext as _
from .log import setup as setup_log
from .models import Repository
from .notifier import EmailNotifier, FeishuNotifier
from .reporter import MarkdownReporter
from .repository import RepositoryManager
from .utils import get_now

logger = logging.getLogger(__name__)


@click.command()
@click.option("--config", "-c", default="config.toml", help="Configuration file path")
def main(config: str):
    """Progress Tracker - GitHub code change tracking tool."""

    setup_log()

    try:
        logger.info(f"Loading configuration file: {config}")
        cfg = Config.load_from_file(config)

        initialize(ui_language=cfg.language)

        init_db(DATABASE_PATH)
        create_tables()

        notifier = FeishuNotifier(
            cfg.notification.feishu.webhook_url,
            timeout=cfg.notification.feishu.timeout,
        )
        email_notifier = _create_email_notifier(cfg.notification.email)

        analyzer = ClaudeCodeAnalyzer(
            max_diff_length=cfg.analysis.max_diff_length,
            timeout=cfg.analysis.timeout,
            language=cfg.analysis.language,
        )
        reporter = MarkdownReporter()

        repo_manager = RepositoryManager(analyzer, reporter, cfg)

        sync_result = repo_manager.sync(cfg.repos)
        logger.info(f"Sync completed: {sync_result}")

        repos = repo_manager.list_enabled()
        logger.info(f"Starting to check {len(repos)} repositories")

        check_result = repo_manager.check_all(
            repos, concurrency=cfg.analysis.concurrency
        )

        if check_result.reports:
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
                cfg.get_timezone(),
            )

            try:
                logger.info("Generating title and summary with Claude...")
                title, summary = analyzer.generate_title_and_summary(aggregated_report)
                final_report = (
                    f"{summary.strip()}\n\n{aggregated_report}"
                    if summary.strip()
                    else aggregated_report
                )
                logger.info(f"Generated report title: {title}")
            except Exception as e:
                logger.warning(
                    f"Failed to generate title and summary, using default title: {e}"
                )
                title = _("Progress Report for Open Source Projects - {date}").format(
                    date=get_now(cfg.get_timezone()).strftime("%Y-%m-%d %H:%M")
                )
                final_report = f"# {title}\n\n{aggregated_report}"

            logger.info("Uploading aggregated report to Markpost...")
            markpost_url = _upload_to_markpost(
                final_report,
                title,
                cfg.markpost.url,
                timeout=cfg.markpost.timeout,
            )
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

            logger.info("Sending Feishu notification...")
            summary_text = _(
                "This report covered {count} projects with {commits} commits total"
            ).format(
                count=len(check_result.reports), commits=check_result.total_commits
            )
            notifier.send_notification(
                title=_("Progress Report for Open Source Projects"),
                total_commits=check_result.total_commits,
                summary=summary_text,
                markpost_url=markpost_url,
                repo_statuses=check_result.repo_statuses,
                reports=check_result.reports,
            )

            if email_notifier:
                logger.info("Sending email notification...")
                email_notifier.send_notification(
                    subject=_("Progress Report for Open Source Projects"),
                    total_commits=check_result.total_commits,
                    summary=summary_text,
                    markpost_url=markpost_url,
                    repo_statuses=check_result.repo_statuses,
                    reports=check_result.reports,
                    _=_,
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


def _create_email_notifier(email_config) -> EmailNotifier | None:
    """Create email notifier.

    Args:
        email_config: Email configuration object (may be None)

    Returns:
        EmailNotifier instance or None
    """
    if not email_config:
        return None
    return EmailNotifier(
        host=email_config.host,
        port=email_config.port,
        user=email_config.user,
        password=email_config.password,
        from_addr=email_config.from_addr,
        recipient=email_config.recipient,
        starttls=email_config.starttls,
        ssl=email_config.ssl,
    )


def _upload_to_markpost(
    content: str, title: str, markpost_url: str, timeout: int = TIMEOUT_HTTP_REQUEST
) -> str:
    """Upload content to Markpost."""
    url = str(markpost_url)
    payload = {"title": title, "body": content}

    try:
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()

        result = response.json()
        post_id = result.get("id")

        parts = str(markpost_url).rstrip("/").rsplit("/", 1)
        base_url = parts[0] if len(parts) > 1 else str(markpost_url)
        return f"{base_url}/{post_id}"
    except requests.RequestException as e:
        logger.error(f"Failed to upload to Markpost: {e}")
        raise ProgressException(f"Failed to upload to Markpost: {e}") from e


if __name__ == "__main__":
    main()
