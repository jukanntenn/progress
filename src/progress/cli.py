"""CLI main entry point."""

import logging
from datetime import datetime
from pathlib import Path, PurePath

import click
from jinja2 import Environment, FileSystemLoader, select_autoescape
from opentelemetry import context as otel_context
from opentelemetry import trace as otel_trace

from .ai import Analyzer, create_analyzer
from .config import Config
from .contrib.changelog.changelog_tracker import ChangelogTrackerManager
from .contrib.proposal import ProposalKind, ProposalReport, ProposalTracker
from .contrib.repo.owner import OwnerManager
from .contrib.repo.reporter import MarkdownReporter
from .contrib.repo.repository import RepositoryManager
from .db import (
    close_db,
    create_tables,
    init_db,
    log_db_state,
    resolve_db_path,
    save_report,
)
from .db.models import Repository
from .errors import ProgressException
from .github import GitClient
from .i18n import gettext as _
from .i18n import initialize
from .log import setup as setup_log
from .notification import (
    NotificationConfig,
    create_channel,
    create_message,
    create_proposal_message,
)
from .notification.utils import ChangelogEntry, DiscoveredRepo
from .telemetry import (
    get_tracer,
    record_notification_sent,
    record_report_generated,
    setup_observability,
    shutdown_observability,
)
from .utils import get_now
from .utils.markpost import MarkpostClient

logger = logging.getLogger(__name__)


def initialize_components(cfg, config_path: str | None = None):
    db_path = resolve_db_path(cfg.data_dir, config_path)
    init_db(db_path)
    create_tables()
    log_db_state()

    cfg = _resolve_runtime_config(cfg)

    markpost_client = None
    if cfg.markpost.enabled and cfg.markpost.url:
        markpost_client = MarkpostClient(cfg.markpost)

    analyzer = create_analyzer(config=cfg.analysis)
    reporter = MarkdownReporter()
    git_client = GitClient(timeout=cfg.github.git_timeout)

    repo_manager = RepositoryManager(analyzer, reporter, cfg)

    proposal_tracker = ProposalTracker(
        analyzer=analyzer,
        git_client=git_client,
        clock=lambda: get_now(cfg.get_timezone()),
        language=cfg.analysis.language,
    )

    return cfg, markpost_client, repo_manager, proposal_tracker, reporter


def _resolve_runtime_config(file_cfg: Config) -> Config:
    """Seed the DB config blob from the file config, then build the runtime config.

    The file is a one-time seed + infra provider; after the first run the blob
    is the source of truth, so the returned config reflects DB edits made via
    the web UI rather than later file changes.
    """
    from .config_store import (
        build_runtime_config,
        load_app_config,
        migrate_blob_schema,
        seed_app_config_if_needed,
        seed_lists_if_needed,
    )

    seed_app_config_if_needed(file_cfg.model_dump(mode="json"))
    migrate_blob_schema()
    seed_lists_if_needed(file_cfg)
    loaded = load_app_config()
    if loaded is None:
        return file_cfg
    blob_data, _ = loaded
    return build_runtime_config(
        blob_data,
        {
            "data_dir": file_cfg.data_dir,
            "workspace_dir": file_cfg.workspace_dir,
            "observability": file_cfg.observability.model_dump(mode="json"),
        },
    )


def send_notification(
    notification_config: NotificationConfig,
    *,
    is_proposal: bool = False,
    **data,
) -> None:
    if not notification_config.channels:
        return

    enabled_channels = [c for c in notification_config.channels if c.enabled]
    if not enabled_channels:
        return

    failures = 0
    for channel_config in enabled_channels:
        channel = create_channel(channel_config)
        if is_proposal:
            message = create_proposal_message(channel_config, channel)
            context = _build_proposal_context(channel_config.type, **data)
        else:
            message = create_message(channel_config, channel)
            context = _build_notification_context(channel_config.type, **data)
        if not message.send(context, fail_silently=True):
            failures += 1
        else:
            record_notification_sent(channel=channel_config.type)

    if failures:
        logger.warning(
            "Some notifications failed: %s/%s", failures, len(enabled_channels)
        )


def _build_notification_context(channel_type: str, **data):
    from .notification import ConsoleContext, EmailContext, FeishuContext

    kwargs = dict(
        title=data.get("title", ""),
        summary=data.get("summary", ""),
        total_commits=data.get("total_commits", 0),
        markpost_url=data.get("markpost_url"),
        repo_statuses=data.get("repo_statuses"),
        notification_type=data.get("notification_type", "repo_update"),
        changelog_entries=data.get("changelog_entries"),
        discovered_repos=data.get("discovered_repos"),
        batch_index=data.get("batch_index"),
        total_batches=data.get("total_batches"),
    )
    if channel_type == "feishu":
        return FeishuContext(**kwargs)
    if channel_type == "email":
        return EmailContext(**kwargs)
    return ConsoleContext(**kwargs)


def _build_proposal_context(channel_type: str, **data):
    from .notification import (
        ConsoleProposalContext,
        EmailProposalContext,
        FeishuProposalContext,
    )

    kwargs = dict(
        title=data.get("title", ""),
        markpost_url=data.get("markpost_url"),
        filenames=data.get("filenames"),
        more_count=data.get("more_count", 0),
    )
    if channel_type == "feishu":
        return FeishuProposalContext(**kwargs)
    if channel_type == "email":
        return EmailProposalContext(**kwargs)
    return ConsoleProposalContext(**kwargs)


def add_batch_suffix(title: str, batch_index: int, total_batches: int) -> str:
    if total_batches > 1:
        return f"{title} ({batch_index + 1}/{total_batches})"
    return title


def _generate_title_and_summary(
    analyzer: Analyzer, aggregated_report: str, language: str
) -> tuple[str, str]:
    prompt = f"""Your task: Analyze the aggregated code change report below and generate a title and summary.

Language requirement: The user-configured output language is "{language}". Use this language for ALL your output.

CRITICAL FORMAT REQUIREMENTS:
1. Output EXACTLY two lines
2. Line 1 MUST start with "TITLE:" followed by the title
3. Line 2 MUST start with "SUMMARY:" followed by the summary
4. Do NOT output any other text

Content requirements:
1. The title must be concise (maximum 10 words)
2. The summary must be a single paragraph (3-5 sentences)
"""
    output = analyzer.analyze(content=aggregated_report, prompt=prompt).strip()
    title = _("Progress Report for Open Source Projects")
    summary = _("A progress report for open source projects.")
    for line in output.split("\n"):
        if line.startswith("TITLE:"):
            title = line[6:].strip()
        elif line.startswith("SUMMARY:"):
            summary = line[8:].strip()
    return title, summary


def generate_report_title_and_content(
    analyzer: Analyzer, aggregated_report, timezone, language, batch_context=None
):
    batch_index = batch_context.get("batch_index", 0) if batch_context else 0
    total_batches = batch_context.get("total_batches", 1) if batch_context else 1

    try:
        logger.info("Generating title and summary with Claude...")
        title, summary = _generate_title_and_summary(
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


def _assemble_batch_body(
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


def _publish_monolithic_report(
    *,
    report_id: int,
    title: str,
    body: str,
    config: Config,
    markpost_client: MarkpostClient | None,
) -> str:
    from .publish import publish_monolithic

    web_base_url = str(config.web.base_url) if config.web.base_url else None
    return publish_monolithic(
        report_id=report_id,
        title=title,
        body=body,
        web_base_url=web_base_url,
        max_batch_size=config.markpost.max_batch_size,
        markpost_client=markpost_client,
    )


def process_reports(
    config: Config,
    check_result,
    reporter,
    timezone,
    analyzer,
    markpost_client,
    notification_config: NotificationConfig,
    max_batch_size=None,
):
    from .publish import build_oversize_stub, byte_size, publish_report
    from .utils import create_report_batches

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
        unified_title, unified_summary = _generate_title_and_summary(
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
        aggregated_report_id = save_report(
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
        repo = Repository.get_or_none(Repository.name == report.repo_name)
        if repo:
            try:
                save_report(
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
    batch_meta: list = []

    for batch in batches:
        logger.info(
            f"Processing batch {batch.batch_index + 1}/{batch.total_batches} "
            f"({len(batch.reports)} reports, {batch.total_size} bytes)"
        )

        try:
            sections = [report.content for report in batch.reports]
            body = _assemble_batch_body(
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
                    body = _assemble_batch_body(
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

    result = publish_report(
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
        send_notification(
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


def _send_entity_notification(
    config: Config,
    notification_config: NotificationConfig,
    markpost_client: MarkpostClient | None,
    analyzer: Analyzer,
    new_repos: list[dict],
    timezone,
) -> None:
    if not new_repos:
        return

    sorted_repos = sorted(
        new_repos, key=lambda r: r.get("created_at") or datetime.min, reverse=True
    )

    for r in sorted_repos:
        r.setdefault("readme_summary", None)
        r.setdefault("readme_detail", None)

    for r in sorted_repos:
        created_at = r.get("created_at")
        if created_at:
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except ValueError:
                    created_at = None
            if created_at and hasattr(created_at, "strftime"):
                r["discovered_at"] = created_at.strftime("%Y-%m-%d %H:%M:%S")
            else:
                r["discovered_at"] = "Unknown"
        else:
            r["discovered_at"] = "Unknown"

        if "owner_name" not in r:
            name_with_owner = r.get("name_with_owner", "")
            if "/" in name_with_owner:
                r["owner_name"] = name_with_owner.split("/")[0]
            else:
                r["owner_name"] = "Unknown"

    reporter = MarkdownReporter()
    report_content = reporter.generate_discovered_repos_report(sorted_repos, timezone)

    try:
        title, summary = _generate_title_and_summary(
            analyzer, report_content, config.analysis.language
        )
    except Exception as e:
        logger.warning(f"Failed to generate title/summary for owner monitoring: {e}")
        now = get_now(timezone)
        title = _("Progress Report for Open Source Projects - {date}").format(
            date=now.strftime("%Y-%m-%d %H:%M")
        )
        summary = f"Discovered {len(new_repos)} new repositories"

    report_id = save_report(
        config=config,
        title=title,
        content=report_content,
        report_type="repo_new",
        commit_count=len(new_repos),
    )
    markpost_url = _publish_monolithic_report(
        report_id=report_id,
        title=title,
        body=report_content,
        config=config,
        markpost_client=markpost_client,
    )

    discovered_repos = [
        DiscoveredRepo(
            name=r.get("name_with_owner") or r.get("repo_name") or str(r.get("id")),
            url=r.get("repo_url")
            or f"https://github.com/{r.get('name_with_owner', '')}",
        )
        for r in sorted_repos
    ]

    send_notification(
        notification_config,
        title=title,
        summary=summary or f"Discovered {len(new_repos)} new repositories",
        total_commits=0,
        markpost_url=markpost_url,
        notification_type="discovered_repos",
        discovered_repos=discovered_repos,
    )


def _send_proposal_notification(
    config: Config,
    notification_config: NotificationConfig,
    markpost_client: MarkpostClient | None,
    analyzer: Analyzer,
    reports: list[ProposalReport],
    timezone,
) -> None:
    template_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["basename"] = lambda p: PurePath(p).name
    template = env.get_template("proposal_events_report.j2")

    from .contrib.proposal.types import KIND_CONFIGS

    grouped: dict[str, list] = {}
    for r in reports:
        grouped.setdefault(r.kind.value, []).append(r)

    for k in grouped:
        grouped[k] = sorted(grouped[k], key=lambda x: x.number)

    tracker_urls = {k.value: KIND_CONFIGS[k].repo_url for k in KIND_CONFIGS}

    report_content = template.render(
        grouped_events=grouped,
        tracker_urls=tracker_urls,
    )

    try:
        title, summary = _generate_title_and_summary(
            analyzer, report_content, config.analysis.language
        )
    except Exception as e:
        logger.warning(f"Failed to generate title/summary for proposal events: {e}")
        title = "Proposal Updates"
        summary = ""

    report_id = save_report(
        config=config,
        title=title,
        content=report_content,
        report_type="proposal",
        commit_count=len(reports),
    )
    markpost_url = _publish_monolithic_report(
        report_id=report_id,
        title=title,
        body=report_content,
        config=config,
        markpost_client=markpost_client,
    )

    filenames = [PurePath(r.file_path).name for r in reports][:5]
    more_count = max(0, len(reports) - len(filenames))
    send_notification(
        notification_config,
        is_proposal=True,
        title=title,
        summary=summary,
        total_commits=len(reports),
        markpost_url=markpost_url,
        filenames=filenames,
        more_count=more_count,
    )


def _send_changelog_update_notification(
    config: Config,
    notification_config: NotificationConfig,
    markpost_client: MarkpostClient | None,
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

    total_new_versions = sum(len(u.new_entries) for u in updates)
    report_id = save_report(
        config=config,
        title=title,
        content=report_content,
        report_type="changelog",
        commit_count=total_new_versions,
    )
    markpost_url = _publish_monolithic_report(
        report_id=report_id,
        title=title,
        body=report_content,
        config=config,
        markpost_client=markpost_client,
    )

    parts = [f"{u.name} ({len(u.new_entries)})" for u in updates]
    summary = (
        f"{len(updates)} trackers updated, {total_new_versions} new versions: "
        + ", ".join(parts[:10])
    )
    if len(parts) > 10:
        summary += f", ... and {len(parts) - 10} more"

    changelog_entries = [
        ChangelogEntry(name=u.name, version=u.new_entries[0].version, url=u.url)
        for u in updates
    ]

    send_notification(
        notification_config,
        title=title,
        summary=summary,
        total_commits=total_new_versions,
        markpost_url=markpost_url,
        notification_type="changelog",
        changelog_entries=changelog_entries,
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
    root_span = None
    otel_token = None
    try:
        logger.info(f"Loading configuration file: {config}")
        cfg = Config.load_from_file(config)
        setup_observability(cfg.observability, component="cli")

        initialize(ui_language=cfg.language)

        cfg, markpost_client, repo_manager, proposal_tracker, reporter = (
            initialize_components(cfg, config)
        )

        root_span = get_tracer().start_span(
            "progress.check",
            attributes={"progress.trackers_only": trackers_only},
        )
        otel_token = otel_context.attach(otel_trace.set_span_in_context(root_span))

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
                    cfg,
                    cfg.notification,
                    markpost_client,
                    updates,
                    changelog_result.results,
                    cfg.get_timezone(),
                )
        except Exception as e:
            logger.warning(f"Changelog tracking startup check failed: {e}")

        if not trackers_only:
            repos = repo_manager.list_enabled()
            if root_span is not None:
                root_span.set_attribute("progress.repo_count", len(repos))
            logger.info(f"Starting to check {len(repos)} repositories")

            check_result = repo_manager.check_all(
                repos, concurrency=cfg.analysis.concurrency
            )

            if check_result.reports:
                process_reports(
                    cfg,
                    check_result,
                    reporter,
                    cfg.get_timezone(),
                    repo_manager.analyzer,
                    markpost_client,
                    cfg.notification,
                    max_batch_size=cfg.markpost.max_batch_size,
                )
            else:
                logger.info(
                    _("No repositories with new changes, skipping report generation")
                )

        if cfg.proposal_trackers:
            from .contrib.proposal.status import should_notify

            kinds = [ProposalKind(k) for k in cfg.proposal_trackers]
            proposal_reports = proposal_tracker.check_all(
                kinds,
                concurrency=cfg.analysis.concurrency,
            )
            notifiable = [
                r for r in proposal_reports if should_notify(r.old_status, r.new_status)
            ]
            if notifiable:
                _send_proposal_notification(
                    cfg,
                    cfg.notification,
                    markpost_client,
                    repo_manager.analyzer,
                    notifiable,
                    cfg.get_timezone(),
                )
            else:
                logger.info("No notifiable proposal changes, skipping notifications")
        else:
            logger.info("No proposal trackers configured")

        owner_manager = OwnerManager(cfg.github.gh_token, cfg.github.proxy)

        new_repos = owner_manager.check_all()
        if new_repos:
            for repo_info in new_repos:
                if not repo_info.get("has_readme") or not repo_info.get(
                    "readme_content"
                ):
                    continue

                try:
                    repo_name = (
                        repo_info.get("name_with_owner")
                        or repo_info.get("repo_name")
                        or ""
                    )
                    description = repo_info.get("description") or ""
                    readme_content = repo_info.get("readme_content") or ""

                    from .contrib.repo.analysis import analyze_readme

                    summary, detail = analyze_readme(
                        repo_manager.analyzer,
                        repo_name,
                        description,
                        readme_content,
                        cfg.analysis.language,
                    )
                    repo_info["readme_summary"] = summary
                    repo_info["readme_detail"] = detail
                except Exception as e:
                    logger.warning(
                        f"Failed to analyze README for {repo_info.get('name_with_owner')}: {e}"
                    )
                    repo_info["readme_summary"] = "README analysis unavailable"
                    repo_info["readme_detail"] = "README analysis failed or timed out."

            _send_entity_notification(
                cfg,
                cfg.notification,
                markpost_client,
                repo_manager.analyzer,
                new_repos,
                cfg.get_timezone(),
            )
        else:
            logger.info("No new repositories discovered, skipping owner notifications")

        logger.info(_("All repository checks completed"))

    except ProgressException as e:
        if root_span is not None:
            root_span.record_exception(e)
            root_span.set_status(otel_trace.Status(otel_trace.StatusCode.ERROR, str(e)))
        logger.error(f"Application error: {e}", exc_info=True)
        raise click.ClickException(str(e))
    except Exception as e:
        if root_span is not None:
            root_span.record_exception(e)
            root_span.set_status(otel_trace.Status(otel_trace.StatusCode.ERROR, str(e)))
        logger.error(f"Program execution failed: {e}", exc_info=True)
        raise click.ClickException(str(e))
    finally:
        if otel_token is not None:
            otel_context.detach(otel_token)
        if root_span is not None:
            root_span.end()
        shutdown_observability()
        close_db()


@cli.command(name="track-proposals")
@click.pass_context
def track_proposals(ctx):
    config = ctx.obj["config_path"]
    try:
        cfg = Config.load_from_file(config)
        initialize(ui_language=cfg.language)

        cfg, markpost_client, repo_manager, proposal_tracker, _ = initialize_components(
            cfg, config
        )

        if cfg.proposal_trackers:
            from .contrib.proposal.status import should_notify

            kinds = [ProposalKind(k) for k in cfg.proposal_trackers]
            proposal_reports = proposal_tracker.check_all(
                kinds,
                concurrency=cfg.analysis.concurrency,
            )
            notifiable = [
                r for r in proposal_reports if should_notify(r.old_status, r.new_status)
            ]
            if notifiable:
                _send_proposal_notification(
                    cfg,
                    cfg.notification,
                    markpost_client,
                    repo_manager.analyzer,
                    notifiable,
                    cfg.get_timezone(),
                )
        else:
            logger.info("No proposal trackers configured")
    finally:
        close_db()


@cli.group(name="config")
def config_group():
    """Manage application configuration (DB blob <-> file)."""


@config_group.command(name="import")
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite the DB blob even if already seeded.",
)
@click.pass_context
def config_import(ctx, force: bool):
    """Import the config file into the DB blob (file -> DB)."""
    config = ctx.obj["config_path"]
    try:
        file_cfg = Config.load_from_file(config)
        db_path = resolve_db_path(file_cfg.data_dir, config)
        init_db(db_path)
        create_tables()

        from .config_store import import_app_config, is_seeded
        from .contrib.repo.owner import replace_owners
        from .contrib.repo.repository import replace_repositories

        if is_seeded() and not force:
            raise click.ClickException(
                "DB config already seeded. Re-run with --force to overwrite."
            )
        version = import_app_config(file_cfg.model_dump(mode="json"))
        repo_result = replace_repositories(file_cfg.repos, file_cfg.github.protocol)
        owner_result = replace_owners(file_cfg.owners)
        click.echo(
            f"Imported configuration into DB (version {version}). "
            f"Repos: {repo_result}. Owners: created={owner_result['created']}, "
            f"updated={owner_result['updated']}, deleted={owner_result['deleted']}."
        )
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(str(e))
    finally:
        close_db()


@config_group.command(name="export")
@click.option(
    "--output",
    "-o",
    default=None,
    help="Output file path (defaults to stdout).",
)
@click.pass_context
def config_export(ctx, output: str | None):
    """Export the DB config blob to a TOML file (DB -> file)."""
    import tomlkit

    config = ctx.obj["config_path"]
    try:
        file_cfg = Config.load_from_file(config)
        db_path = resolve_db_path(file_cfg.data_dir, config)
        init_db(db_path)
        create_tables()

        from .config_store import INFRA_FIELDS, load_app_config

        loaded = load_app_config()
        if loaded is None:
            raise click.ClickException("DB config has not been seeded.")
        data = dict(loaded[0])
        for field in INFRA_FIELDS:
            data.setdefault(field, getattr(file_cfg, field, None))

        def drop_none(node):
            if isinstance(node, dict):
                return {k: drop_none(v) for k, v in node.items() if v is not None}
            if isinstance(node, list):
                return [drop_none(v) for v in node if v is not None]
            return node

        toml_text = tomlkit.dumps(tomlkit.item(drop_none(data)))
        if output:
            Path(output).write_text(toml_text, encoding="utf-8")
            click.echo(f"Exported configuration to {output}.")
        else:
            click.echo(toml_text)
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(str(e))
    finally:
        close_db()


def main():
    """Legacy main function for backward compatibility."""
    cli(obj={})


if __name__ == "__main__":
    main()
