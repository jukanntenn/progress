"""CLI main entry point."""

import logging
from pathlib import Path

import click
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .analyzer import ClaudeCodeAnalyzer
from .changelog_tracker import ChangelogTrackerManager
from .config import Config
from .consts import DATABASE_PATH
from .db import close_db, create_tables, init_db, save_report
from .errors import ProgressException
from .i18n import gettext as _
from .i18n import initialize
from .log import setup as setup_log
from .markpost import MarkpostClient
from .models import DiscoveredRepository, Repository
from .notification import NotificationManager, NotificationMessage
from .owner import OwnerManager
from .proposal_tracking import ProposalTrackerManager
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

    proposal_manager = ProposalTrackerManager(analyzer, cfg)

    return notification_manager, markpost_client, repo_manager, proposal_manager, reporter


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


def _send_entity_notification(
    notification_manager: NotificationManager,
    markpost_client: MarkpostClient,
    analyzer: ClaudeCodeAnalyzer,
    new_repos: list[dict],
    timezone,
) -> None:
    now = get_now(timezone)
    lines: list[str] = [
        f"# New repositories discovered ({now.strftime('%Y-%m-%d %H:%M')})",
        "",
    ]

    grouped: dict[tuple[str, str], list[dict]] = {}
    for r in new_repos:
        key = (r.get("owner_type") or "", r.get("owner_name") or "")
        grouped.setdefault(key, []).append(r)

    for (owner_type, owner_name), repos in sorted(grouped.items()):
        lines.append(f"## {owner_name} ({owner_type})")
        lines.append("")
        for r in sorted(repos, key=lambda x: x.get("repo_name") or ""):
            lines.append(f"### {r.get('repo_name')}")
            lines.append("")
            repo_url = r.get("repo_url")
            if repo_url:
                lines.append(f"- URL: {repo_url}")
            if r.get("description"):
                lines.append(f"- Description: {r.get('description')}")
            created_at = r.get("created_at")
            if created_at and hasattr(created_at, "isoformat"):
                lines.append(f"- Created at: {created_at.isoformat()}")
            if r.get("readme_was_truncated"):
                lines.append("- README was truncated to 50KB for analysis")
            lines.append("")

            if not r.get("has_readme"):
                lines.append("This repository does not have a README file.")
                lines.append("")
                continue

            readme_summary = r.get("readme_summary")
            if readme_summary:
                lines.append("#### README Summary")
                lines.append(str(readme_summary))
                lines.append("")

            readme_detail = r.get("readme_detail")
            if readme_detail:
                lines.append("#### README Detail")
                lines.append(str(readme_detail))
                lines.append("")

    report_content = "\n".join(lines)

    try:
        title, summary = analyzer.generate_title_and_summary(report_content)
    except Exception as e:
        logger.warning(f"Failed to generate title/summary for owner monitoring: {e}")
        title = _("Progress Report for Open Source Projects - {date}").format(
            date=now.strftime("%Y-%m-%d %H:%M")
        )
        summary = ""

    markpost_url = markpost_client.upload(report_content, title=title)

    repo_statuses = {
        (r.get("name_with_owner") or r.get("repo_name") or str(r.get("id"))): "success"
        for r in new_repos
    }

    notification_manager.send(
        NotificationMessage(
            title=title,
            summary=summary or f"Discovered {len(new_repos)} new repositories",
            total_commits=len(new_repos),
            markpost_url=markpost_url,
            repo_statuses=repo_statuses,
        )
    )

    for r in new_repos:
        record_id = r.get("id")
        if record_id:
            record = DiscoveredRepository.get_by_id(record_id)
            if record:
                record.notified = True
                record.save()


def _send_proposal_event_notification(
    notification_manager: NotificationManager,
    markpost_client: MarkpostClient,
    analyzer: ClaudeCodeAnalyzer,
    events,
    timezone,
) -> None:
    now = get_now(timezone)
    template_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("proposal_events_report.j2")

    grouped: dict[str, list] = {}
    for e in events:
        grouped.setdefault(e.tracker_type, []).append(e)

    for k in grouped:
        grouped[k] = sorted(grouped[k], key=lambda x: (x.proposal_number, x.event_type))

    report_content = template.render(
        now=now.strftime("%Y-%m-%d %H:%M"),
        grouped_events=grouped,
    )

    try:
        title, summary = analyzer.generate_title_and_summary(report_content)
    except Exception as e:
        logger.warning(f"Failed to generate title/summary for proposal events: {e}")
        title = _("Progress Report for Open Source Projects - {date}").format(
            date=now.strftime("%Y-%m-%d %H:%M")
        )
        summary = f"{len(events)} proposal events"

    markpost_url = markpost_client.upload(report_content, title=title)
    repo_statuses = {
        f"{e.tracker_type}#{e.proposal_number}": "success" for e in events
    }
    notification_manager.send(
        NotificationMessage(
            title=title,
            summary=summary,
            total_commits=len(events),
            markpost_url=markpost_url,
            repo_statuses=repo_statuses,
        )
    )


def _send_changelog_update_notification(
    notification_manager: NotificationManager,
    markpost_client: MarkpostClient,
    updates,
    all_results,
    timezone,
) -> None:
    now = get_now(timezone)
    template_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("changelog_updates_report.j2")

    report_content = template.render(
        now=now.strftime("%Y-%m-%d %H:%M"),
        updates=updates,
    )

    title = f"Changelog Updates - {now.strftime('%Y-%m-%d %H:%M')}"
    markpost_url = markpost_client.upload(report_content, title=title)

    total_new_versions = sum(len(u.new_entries) for u in updates)
    parts = [f"{u.name} ({len(u.new_entries)})" for u in updates]
    summary = f"{len(updates)} trackers updated, {total_new_versions} new versions: " + ", ".join(
        parts[:10]
    )
    if len(parts) > 10:
        summary += f", ... and {len(parts) - 10} more"

    repo_statuses = {}
    for r in all_results:
        if r.status == "success" and r.new_entries:
            repo_statuses[r.name] = "success"
        elif r.status == "failed":
            repo_statuses[r.name] = "failed"
        else:
            repo_statuses[r.name] = "skipped"

    notification_manager.send(
        NotificationMessage(
            title=title,
            summary=summary,
            total_commits=total_new_versions,
            markpost_url=markpost_url,
            repo_statuses=repo_statuses,
        )
    )


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
@click.option(
    "--trackers-only",
    is_flag=True,
    default=False,
    help="Check only proposal trackers, skip repositories",
)
@click.pass_context
def check(ctx, trackers_only: bool):
    """Run repository checks and generate reports."""
    config = ctx.obj["config_path"]
    _run_check_command(config, trackers_only=trackers_only)


def _run_check_command(config: str, trackers_only: bool = False):
    """Run the main check command logic."""
    try:
        logger.info(f"Loading configuration file: {config}")
        cfg = Config.load_from_file(config)

        initialize(ui_language=cfg.language)

        notification_manager, markpost_client, repo_manager, proposal_manager, reporter = (
            initialize_components(cfg)
        )

        try:
            changelog_manager = ChangelogTrackerManager.from_config(cfg)
            changelog_sync = changelog_manager.sync(cfg.changelog_trackers)
            logger.info(f"Changelog tracker sync completed: {changelog_sync}")

            changelog_result = changelog_manager.check_all()
            for r in changelog_result.results:
                extra = []
                if r.latest_version:
                    extra.append(f"latest={r.latest_version}")
                if r.error:
                    extra.append(f"error={r.error}")
                extra_str = f" ({', '.join(extra)})" if extra else ""
                logger.info(f"Changelog tracker {r.name}: {r.status}{extra_str}")

            updates = [
                r
                for r in changelog_result.results
                if r.status == "success" and r.new_entries
            ]
            if updates:
                _send_changelog_update_notification(
                    notification_manager,
                    markpost_client,
                    updates,
                    changelog_result.results,
                    cfg.get_timezone(),
                )
        except Exception as e:
            logger.warning(f"Changelog tracking startup check failed: {e}")

        if not trackers_only:
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

        tracker_sync = proposal_manager.sync(cfg.proposal_trackers)
        logger.info(f"Proposal tracker sync completed: {tracker_sync}")

        enabled_trackers = proposal_manager.list_enabled()
        if enabled_trackers:
            tracker_result = proposal_manager.check_all(
                enabled_trackers,
                concurrency=cfg.analysis.concurrency,
            )
            high_priority = [
                e for e in tracker_result.events if proposal_manager.is_high_priority_event(e.event_type)
            ]
            if high_priority:
                _send_proposal_event_notification(
                    notification_manager,
                    markpost_client,
                    repo_manager.analyzer,
                    high_priority,
                    cfg.get_timezone(),
                )
            else:
                logger.info("No high-priority proposal events, skipping notifications")
        else:
            logger.info("No enabled proposal trackers")

        owner_manager = OwnerManager(cfg.github.gh_token)
        owner_sync_result = owner_manager.sync_owners(cfg.owners)
        logger.info(f"Owner sync completed: {owner_sync_result}")

        new_repos = owner_manager.check_all()
        if new_repos:
            for repo_info in new_repos:
                if not repo_info.get("has_readme") or not repo_info.get("readme_content"):
                    continue

                try:
                    repo_name = repo_info.get("name_with_owner") or repo_info.get("repo_name") or ""
                    description = repo_info.get("description") or ""
                    readme_content = repo_info.get("readme_content") or ""

                    summary, detail = repo_manager.analyzer.analyze_readme(
                        repo_name,
                        description,
                        readme_content,
                    )
                    repo_info["readme_summary"] = summary
                    repo_info["readme_detail"] = detail

                    record_id = repo_info.get("id")
                    if record_id:
                        record = DiscoveredRepository.get_by_id(record_id)
                        if record:
                            record.readme_summary = summary
                            record.readme_detail = detail
                            record.save()
                except Exception as e:
                    logger.warning(
                        f"Failed to analyze README for {repo_info.get('name_with_owner')}: {e}"
                    )
                    repo_info["readme_summary"] = "README analysis unavailable"
                    repo_info["readme_detail"] = "README analysis failed or timed out."

            _send_entity_notification(
                notification_manager,
                markpost_client,
                repo_manager.analyzer,
                new_repos,
                cfg.get_timezone(),
            )
        else:
            logger.info("No new repositories discovered, skipping owner notifications")

        logger.info(_("All repository checks completed"))

    except ProgressException as e:
        logger.error(f"Application error: {e}", exc_info=True)
        raise click.ClickException(str(e))
    except Exception as e:
        logger.error(f"Program execution failed: {e}", exc_info=True)
        raise click.ClickException(str(e))
    finally:
        close_db()


@cli.command(name="track-proposals")
@click.pass_context
def track_proposals(ctx):
    config = ctx.obj["config_path"]
    try:
        cfg = Config.load_from_file(config)
        initialize(ui_language=cfg.language)

        notification_manager, markpost_client, repo_manager, proposal_manager, _ = (
            initialize_components(cfg)
        )
        proposal_manager.sync(cfg.proposal_trackers)
        enabled_trackers = proposal_manager.list_enabled()
        result = proposal_manager.check_all(
            enabled_trackers,
            concurrency=cfg.analysis.concurrency,
        )
        high_priority = [
            e for e in result.events if proposal_manager.is_high_priority_event(e.event_type)
        ]
        if high_priority:
            _send_proposal_event_notification(
                notification_manager,
                markpost_client,
                repo_manager.analyzer,
                high_priority,
                cfg.get_timezone(),
            )
    finally:
        close_db()


@cli.command(name="sync-proposal-trackers")
@click.pass_context
def sync_proposal_trackers(ctx):
    config = ctx.obj["config_path"]
    try:
        cfg = Config.load_from_file(config)
        initialize(ui_language=cfg.language)
        _, _, _, proposal_manager, _ = initialize_components(cfg)
        result = proposal_manager.sync(cfg.proposal_trackers)
        click.echo(str(result))
    finally:
        close_db()


@cli.command(name="list-proposals")
@click.option(
    "--type",
    "proposal_type",
    type=click.Choice(["eip", "rust_rfc", "pep", "django_dep"], case_sensitive=False),
    default=None,
)
@click.pass_context
def list_proposals(ctx, proposal_type: str | None):
    config = ctx.obj["config_path"]
    try:
        cfg = Config.load_from_file(config)
        initialize(ui_language=cfg.language)
        init_db(DATABASE_PATH)
        create_tables()

        from .models import DjangoDEP, EIP, PEP, RustRFC

        rows: list[str] = []
        if proposal_type in (None, "eip"):
            for p in EIP.select().order_by(EIP.eip_number):
                rows.append(f"eip\t{p.eip_number}\t{p.status}\t{p.title}")
        if proposal_type in (None, "rust_rfc"):
            for p in RustRFC.select().order_by(RustRFC.rfc_number):
                rows.append(f"rust_rfc\t{p.rfc_number}\t{p.status}\t{p.title}")
        if proposal_type in (None, "pep"):
            for p in PEP.select().order_by(PEP.pep_number):
                rows.append(f"pep\t{p.pep_number}\t{p.status}\t{p.title}")
        if proposal_type in (None, "django_dep"):
            for p in DjangoDEP.select().order_by(DjangoDEP.dep_number):
                rows.append(f"django_dep\t{p.dep_number}\t{p.status}\t{p.title}")

        click.echo("type\tnumber\tstatus\ttitle")
        for r in rows:
            click.echo(r)
    finally:
        close_db()


@cli.command(name="list-proposal-events")
@click.option(
    "--type",
    "proposal_type",
    type=click.Choice(["eip", "rust_rfc", "pep", "django_dep"], case_sensitive=False),
    required=True,
)
@click.option("--number", type=int, required=True)
@click.pass_context
def list_proposal_events(ctx, proposal_type: str, number: int):
    config = ctx.obj["config_path"]
    try:
        cfg = Config.load_from_file(config)
        initialize(ui_language=cfg.language)
        init_db(DATABASE_PATH)
        create_tables()

        from .models import DjangoDEP, EIP, PEP, ProposalEvent, RustRFC

        proposal = None
        if proposal_type == "eip":
            proposal = EIP.select().where(EIP.eip_number == number).first()
        elif proposal_type == "rust_rfc":
            proposal = RustRFC.select().where(RustRFC.rfc_number == number).first()
        elif proposal_type == "pep":
            proposal = PEP.select().where(PEP.pep_number == number).first()
        elif proposal_type == "django_dep":
            proposal = DjangoDEP.select().where(DjangoDEP.dep_number == number).first()

        if proposal is None:
            raise click.ClickException("Proposal not found")

        query = ProposalEvent.select().order_by(ProposalEvent.detected_at)
        if proposal_type == "eip":
            query = query.where(ProposalEvent.eip == proposal)
        elif proposal_type == "rust_rfc":
            query = query.where(ProposalEvent.rust_rfc == proposal)
        elif proposal_type == "pep":
            query = query.where(ProposalEvent.pep == proposal)
        elif proposal_type == "django_dep":
            query = query.where(ProposalEvent.django_dep == proposal)

        click.echo("detected_at\tevent_type\told_status\tnew_status\tcommit")
        for e in query:
            click.echo(
                f"{e.detected_at.isoformat()}\t{e.event_type}\t{e.old_status or ''}\t{e.new_status or ''}\t{e.commit_hash}"
            )
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
