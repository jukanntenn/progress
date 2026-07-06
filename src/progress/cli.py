"""CLI entry point: Typer command definitions and check orchestration."""

import asyncio
import logging
import typing
from contextvars import Token
from functools import wraps
from pathlib import Path

import typer
from opentelemetry import context as otel_context
from opentelemetry import trace as otel_trace
from opentelemetry.context.context import Context
from opentelemetry.trace import Span

from .bootstrap import initialize_components
from .config import Config
from .contrib.changelog.changelog_tracker import ChangelogTrackerManager
from .contrib.proposal import ProposalKind
from .contrib.proposal.tracker import ProposalTracker
from .contrib.repo.owner import OwnerManager
from .contrib.repo.reporter import MarkdownReporter
from .contrib.repo.repository import RepositoryManager
from .db import close_db, create_tables, init_db, resolve_db_path
from .errors import ProgressException
from .i18n import gettext as _
from .i18n import initialize
from .log import setup as setup_log
from .notification.dispatch import (
    send_changelog_update_notification,
    send_entity_notification,
    send_notification,
    send_proposal_notification,
)
from .reporting import process_reports
from .telemetry import (
    get_tracer,
    setup_observability,
    shutdown_observability,
)
from .utils.markpost import MarkpostClient

logger = logging.getLogger(__name__)


def _fail(message: str) -> typing.NoReturn:
    """Print an error message to stderr and exit with code 1."""
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=1)


def _run_async(coro):
    """Run an async coroutine to completion under a single event loop.

    Mirrors feeber's ``_handle_run_errors``: typer command callbacks stay
    synchronous (typer does not natively await), and each invokes exactly one
    ``asyncio.run`` spanning the whole command so DB init, queries and shutdown
    share one loop and one tortoise-orm context.
    """

    @wraps(coro)
    def wrapper(*args, **kwargs):
        return asyncio.run(coro(*args, **kwargs))

    return wrapper


app = typer.Typer(
    invoke_without_command=True,
    help="Progress Tracker - GitHub code change tracking tool.",
)
config_app = typer.Typer(
    help="Manage application configuration (DB blob <-> file)."
)
app.add_typer(config_app, name="config")


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    config: str = typer.Option(
        "config.toml", "--config", "-c", help="Configuration file path"
    ),
) -> None:
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    setup_log()

    if ctx.invoked_subcommand is None:
        _run_async(_run_check_command)(config)


@app.command(name="check")
def check(
    ctx: typer.Context,
    trackers_only: bool = typer.Option(
        False,
        "--trackers-only",
        help="Check only proposal trackers, skip repositories",
    ),
) -> None:
    """Run repository checks and generate reports."""
    config: str = ctx.obj["config_path"]
    _run_async(_run_check_command)(config, trackers_only=trackers_only)


async def _run_check_command(config: str, trackers_only: bool = False) -> None:
    """Run the main check command logic."""
    root_span: Span | None = None
    otel_token: Token[Context] | None = None
    try:
        logger.info(f"Loading configuration file: {config}")
        cfg = Config.load_from_file(config)
        setup_observability(cfg.observability, component="cli")

        initialize(ui_language=cfg.language)

        cfg, markpost_client, repo_manager, proposal_tracker, reporter = (
            await initialize_components(cfg, config)
        )

        root_span = get_tracer().start_span(
            "progress.check",
            attributes={"progress.trackers_only": trackers_only},
        )
        otel_token = otel_context.attach(
            otel_trace.set_span_in_context(root_span)
        )

        await _run_changelog_check(cfg, markpost_client)

        if not trackers_only:
            await _run_repo_check(
                cfg, repo_manager, reporter, markpost_client, root_span
            )

        await _run_proposal_check(cfg, markpost_client, repo_manager, proposal_tracker)
        await _run_owner_check(cfg, markpost_client, repo_manager)

        logger.info(_("All repository checks completed"))

    except ProgressException as e:
        if root_span is not None:
            root_span.record_exception(e)
            root_span.set_status(
                otel_trace.Status(otel_trace.StatusCode.ERROR, str(e))
            )
        logger.error(f"Application error: {e}", exc_info=True)
        _fail(str(e))
    except Exception as e:
        if root_span is not None:
            root_span.record_exception(e)
            root_span.set_status(
                otel_trace.Status(otel_trace.StatusCode.ERROR, str(e))
            )
        logger.error(f"Program execution failed: {e}", exc_info=True)
        _fail(str(e))
    finally:
        if otel_token is not None:
            otel_context.detach(otel_token)
        if root_span is not None:
            root_span.end()
        shutdown_observability()
        await close_db()


async def _run_changelog_check(
    cfg: Config, markpost_client: MarkpostClient | None
) -> None:
    try:
        changelog_manager = ChangelogTrackerManager.from_config(cfg)
        changelog_sync = await changelog_manager.sync(cfg.changelog_trackers)
        logger.info(f"Changelog tracker sync completed: {changelog_sync}")

        changelog_result = await changelog_manager.check_all()
        for r in changelog_result.results:
            extra: list[str] = []
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
            await send_changelog_update_notification(
                cfg,
                cfg.notification,
                markpost_client,
                updates,
                changelog_result.results,
                cfg.get_timezone(),
            )
    except Exception as e:
        logger.warning(f"Changelog tracking startup check failed: {e}")


async def _run_repo_check(
    cfg: Config,
    repo_manager: RepositoryManager,
    reporter: MarkdownReporter,
    markpost_client: MarkpostClient | None,
    root_span: Span | None,
) -> None:
    repos = await repo_manager.list_enabled()
    if root_span is not None:
        root_span.set_attribute("progress.repo_count", len(repos))
    logger.info(f"Starting to check {len(repos)} repositories")

    check_result = await repo_manager.check_all(
        repos, concurrency=cfg.analysis.concurrency
    )

    if check_result.reports:
        await process_reports(
            cfg,
            check_result,
            reporter,
            cfg.get_timezone(),
            repo_manager.analyzer,
            markpost_client,
            cfg.notification,
            send_notification_fn=send_notification,
            max_batch_size=cfg.markpost.max_batch_size,
        )
    else:
        logger.info(
            _("No repositories with new changes, skipping report generation")
        )


async def _run_proposal_check(
    cfg: Config,
    markpost_client: MarkpostClient | None,
    repo_manager: RepositoryManager,
    proposal_tracker: ProposalTracker,
) -> None:
    if cfg.proposal_trackers:
        from .contrib.proposal.status import should_notify

        kinds = [ProposalKind(k) for k in cfg.proposal_trackers]
        proposal_reports = await proposal_tracker.check_all(
            kinds,
            concurrency=cfg.analysis.concurrency,
        )
        notifiable = [
            r for r in proposal_reports if should_notify(r.old_status, r.new_status)
        ]
        if notifiable:
            await send_proposal_notification(
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


async def _run_owner_check(
    cfg: Config,
    markpost_client: MarkpostClient | None,
    repo_manager: RepositoryManager,
) -> None:
    owner_manager = OwnerManager(cfg.github.gh_token, cfg.github.proxy)

    new_repos = await owner_manager.check_all()
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

                summary, detail = await analyze_readme(
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

        await send_entity_notification(
            cfg,
            cfg.notification,
            markpost_client,
            repo_manager.analyzer,
            new_repos,
            cfg.get_timezone(),
        )
    else:
        logger.info("No new repositories discovered, skipping owner notifications")


@app.command(name="track-proposals")
def track_proposals(ctx: typer.Context) -> None:
    config: str = ctx.obj["config_path"]
    _run_async(_track_proposals)(config)


async def _track_proposals(config: str) -> None:
    try:
        cfg = Config.load_from_file(config)
        initialize(ui_language=cfg.language)

        cfg, markpost_client, repo_manager, proposal_tracker, _ = (
            await initialize_components(cfg, config)
        )

        if cfg.proposal_trackers:
            from .contrib.proposal.status import should_notify

            kinds = [ProposalKind(k) for k in cfg.proposal_trackers]
            proposal_reports = await proposal_tracker.check_all(
                kinds,
                concurrency=cfg.analysis.concurrency,
            )
            notifiable = [
                r for r in proposal_reports if should_notify(r.old_status, r.new_status)
            ]
            if notifiable:
                await send_proposal_notification(
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
        await close_db()


@config_app.command(name="import")
def config_import(
    ctx: typer.Context,
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite the DB blob even if already seeded.",
    ),
) -> None:
    """Import the config file into the DB blob (file -> DB)."""
    config: str = ctx.obj["config_path"]
    _run_async(_config_import)(config, force=force)


async def _config_import(config: str, *, force: bool) -> None:
    try:
        file_cfg = Config.load_from_file(config)
        db_path = resolve_db_path(file_cfg.data_dir, config)
        await init_db(db_path)
        await create_tables()

        from .config_store import import_app_config, is_seeded
        from .contrib.repo.owner import replace_owners
        from .contrib.repo.repository import replace_repositories

        if await is_seeded() and not force:
            _fail(
                "DB config already seeded. Re-run with --force to overwrite."
            )
        version = await import_app_config(file_cfg.model_dump(mode="json"))
        repo_result = await replace_repositories(
            file_cfg.repos, file_cfg.github.protocol
        )
        owner_result = await replace_owners(file_cfg.owners)
        typer.echo(
            f"Imported configuration into DB (version {version}). "
            f"Repos: {repo_result}. Owners: created={owner_result['created']}, "
            f"updated={owner_result['updated']}, deleted={owner_result['deleted']}."
        )
    except typer.Exit:
        raise
    except Exception as e:
        _fail(str(e))
    finally:
        await close_db()


@config_app.command(name="export")
def config_export(
    ctx: typer.Context,
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path (defaults to stdout).",
    ),
) -> None:
    """Export the DB config blob to a TOML file (DB -> file)."""
    _run_async(_config_export)(ctx.obj["config_path"], output=output)


async def _config_export(config: str, *, output: str | None) -> None:
    import tomlkit

    try:
        file_cfg = Config.load_from_file(config)
        db_path = resolve_db_path(file_cfg.data_dir, config)
        await init_db(db_path)
        await create_tables()

        from .config_store import INFRA_FIELDS, load_app_config

        loaded = await load_app_config()
        if loaded is None:
            _fail("DB config has not been seeded.")
        data = dict(loaded[0])
        for field in INFRA_FIELDS:
            data.setdefault(field, getattr(file_cfg, field, None))

        def drop_none(node: object) -> object:
            if isinstance(node, dict):
                return {k: drop_none(v) for k, v in node.items() if v is not None}
            if isinstance(node, list):
                return [drop_none(v) for v in node if v is not None]
            return node

        toml_text = tomlkit.dumps(
            tomlkit.item(drop_none(data))  # ty: ignore[no-matching-overload]  # drop_none returns a dict but recursive type narrowing through isinstance can't be expressed statically
        )
        if output:
            Path(output).write_text(toml_text, encoding="utf-8")
            typer.echo(f"Exported configuration to {output}.")
        else:
            typer.echo(toml_text)
    except typer.Exit:
        raise
    except Exception as e:
        _fail(str(e))
    finally:
        await close_db()


cli = app


def main() -> None:
    """Legacy main function for backward compatibility."""
    app()


if __name__ == "__main__":
    main()
