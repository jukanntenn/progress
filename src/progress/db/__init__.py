"""Database initialization and operations (tortoise-orm, async)."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from tortoise import Tortoise, connections
from tortoise.transactions import in_transaction

from progress.config import Config

logger = logging.getLogger(__name__)


def resolve_db_path(data_dir: str, config_path: str | None = None) -> str:
    """Resolve the SQLite database path to an absolute, CWD-independent location.

    PROGRESS_DB_PATH overrides everything. Otherwise ``<data_dir>/progress.db`` is
    anchored to PROGRESS_HOME, then the config file directory, then the CWD — so the
    active database no longer depends on which working directory a process starts in.
    """
    env_path = os.environ.get("PROGRESS_DB_PATH")
    if env_path:
        return str(Path(env_path).expanduser().resolve())

    base = Path(data_dir)
    if not base.is_absolute():
        home = os.environ.get("PROGRESS_HOME")
        if home:
            anchor = Path(home).expanduser()
        elif config_path:
            anchor = Path(config_path).expanduser().resolve().parent
        else:
            anchor = Path.cwd()
        base = anchor / base

    return str(base.joinpath("progress.db").resolve())


def _build_db_url(db_path: str) -> str:
    """Build the sqlite:// URL with the same PRAGMA set as the prior peewee pool.

    tortoise-orm already applies ``journal_mode=WAL``, ``journal_size_limit`` and
    ``foreign_keys=ON`` by default (see tortoise/backends/sqlite/client.py); the
    remaining pragmas (synchronous, busy_timeout, cache_size) are passed via the
    URL query string, which tortoise forwards to ``PRAGMA`` on connect.
    """
    return f"sqlite://{db_path}?synchronous=NORMAL&busy_timeout=5000&cache_size=-64000"


async def init_db(db_path: str) -> None:
    """Initialize the tortoise-orm connection to the SQLite database."""
    path = Path(db_path)
    await Tortoise.init(
        db_url=_build_db_url(db_path),
        modules={
            "models": [
                "progress.db.models",
                "progress.contrib.repo.models",
                "progress.contrib.changelog.models",
                "progress.contrib.proposal.models",
            ]
        },
        use_tz=True,
        timezone="UTC",
        _enable_global_fallback=True,
    )
    logger.info("Database connection initialized: %s", path.resolve())


async def close_db() -> None:
    """Close all tortoise-orm database connections."""
    await Tortoise.close_connections()
    logger.info("Database connection closed")


@asynccontextmanager
async def database_connection() -> AsyncIterator[None]:
    """Transaction-scoped database connection context manager.

    Replaces the prior peewee ``database_proxy.atomic()`` /
    ``database.connection_context()`` wrappers. tortoise-orm manages the
    connection itself, so this now only opens a transaction boundary.
    """
    async with in_transaction():
        yield


def _conn():
    return connections.get("default")


async def _table_exists(table_name: str) -> bool:
    _, rows = await _conn().execute_query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        [table_name],
    )
    return len(rows) > 0


async def _existing_columns(table_name: str) -> set[str]:
    _, rows = await _conn().execute_query(f"PRAGMA table_info({table_name})")
    return {row[1] for row in rows}


async def log_db_state() -> None:
    """Log a checkpoint summary so the active database is observable at startup."""
    from progress.db.models import Repository

    try:
        total = await Repository.all().count()
        with_checkpoint = await Repository.filter(
            last_commit_hash__not_isnull=True
        ).count()
    except Exception as e:
        logger.debug(f"Skipping database state summary: {e}")
        return

    logger.info(
        f"Database state: {total} repository record(s), "
        f"{with_checkpoint} with commit checkpoint"
    )


async def migrate_database() -> None:
    """Migrate database schema to latest version (idempotent).

    Ported 1:1 from the prior peewee ``migrate_database``: same SQL text, same
    ordering, same idempotency guards. Only the driver calls changed
    (``db.execute_sql`` -> ``execute_query`` / ``execute_script``).
    """
    conn = _conn()

    if await _table_exists("rustrfc") and not await _table_exists("rust_rfcs"):
        await conn.execute_script("ALTER TABLE rustrfc RENAME TO rust_rfcs")

    existing_columns = await _existing_columns("reports")

    if "title" not in existing_columns:
        logger.info("Migrating: Adding 'title' column to reports table")
        await conn.execute_script(
            "ALTER TABLE reports ADD COLUMN title VARCHAR NOT NULL DEFAULT ''"
        )
        logger.info("Migration completed: 'title' column added")

    if "report_type" not in existing_columns:
        logger.info("Migrating: Adding 'report_type' column to reports table")
        await conn.execute_script(
            "ALTER TABLE reports ADD COLUMN report_type VARCHAR NOT NULL DEFAULT 'repo_update'"
        )
        await conn.execute_script(
            "UPDATE reports SET report_type = 'repo_update' "
            "WHERE report_type IS NULL OR report_type = ''"
        )
        logger.info("Migration completed: 'report_type' column added")

    columns_info = await _existing_columns("reports")
    columns = columns_info
    repo_column_info = None
    _, rows = await _conn().execute_query("PRAGMA table_info(reports)")
    for c in rows:
        if c[1] == "repo_id":
            repo_column_info = c
            break

    if repo_column_info and repo_column_info[3] != 0:
        logger.info("Migrating: Making 'repo' column nullable in reports table")
        title_expr = "title" if "title" in columns else "''"
        report_type_expr = (
            "report_type" if "report_type" in columns else "'repo_update'"
        )
        await conn.execute_script(
            "CREATE TABLE reports_new ("
            "id INTEGER PRIMARY KEY,"
            "repo_id INTEGER NULL REFERENCES repositories(id) ON DELETE CASCADE,"
            "title VARCHAR NOT NULL DEFAULT '',"
            "report_type VARCHAR NOT NULL DEFAULT 'repo_update',"
            "commit_hash VARCHAR NOT NULL,"
            "previous_commit_hash VARCHAR,"
            "commit_count INTEGER NOT NULL DEFAULT 1,"
            "markpost_url VARCHAR,"
            "content TEXT,"
            "created_at VARCHAR NOT NULL)"
        )
        await conn.execute_script(
            "INSERT INTO reports_new (id, repo_id, title, report_type, commit_hash, previous_commit_hash, "
            "commit_count, markpost_url, content, created_at) "
            f"SELECT id, repo_id, {title_expr}, {report_type_expr}, commit_hash, previous_commit_hash, "
            "commit_count, markpost_url, content, created_at FROM reports"
        )
        await conn.execute_script("DROP TABLE reports")
        await conn.execute_script("ALTER TABLE reports_new RENAME TO reports")
        logger.info("Migration completed: 'repo' column is now nullable")

    repo_existing_columns = await _existing_columns("repositories")

    if "last_release_tag" not in repo_existing_columns:
        logger.info("Migrating: Adding release tracking columns to repositories table")
        await conn.execute_script(
            "ALTER TABLE repositories ADD COLUMN last_release_tag VARCHAR"
        )
        await conn.execute_script(
            "ALTER TABLE repositories ADD COLUMN last_release_commit_hash VARCHAR"
        )
        await conn.execute_script(
            "ALTER TABLE repositories ADD COLUMN last_release_check_time TIMESTAMP"
        )
        logger.info("Migration completed: release tracking columns added")

    old_proposal_tables = [
        "proposal_events",
        "eips",
        "rust_rfcs",
        "peps",
        "django_deps",
    ]
    for table in old_proposal_tables:
        if await _table_exists(table):
            logger.info(f"Migrating: Dropping old proposal table '{table}'")
            await conn.execute_script(f"DROP TABLE IF EXISTS {table}")
            logger.info(f"Migration completed: '{table}' dropped")

    if await _table_exists("proposal_trackers"):
        cols = await _existing_columns("proposal_trackers")
        if "tracker_type" in cols:
            logger.info(
                "Migrating: Dropping old proposal_trackers table for new schema"
            )
            await conn.execute_script("DROP TABLE IF EXISTS proposal_trackers")
            logger.info("Migration completed: old proposal_trackers dropped")

    if await _table_exists("discovered_repositories"):
        logger.info("Migrating: Dropping deprecated 'discovered_repositories' table")
        await conn.execute_script("DROP TABLE IF EXISTS discovered_repositories")
        logger.info("Migration completed: 'discovered_repositories' dropped")

    await _ensure_fk_indexes()


async def _ensure_fk_indexes() -> None:
    """Create indexes on FK columns to match the prior peewee auto-indexing.

    peewee automatically indexes every ``ForeignKeyField``; tortoise does not.
    These are non-unique ordinary indexes (the unique composite ones come from
    ``unique_together``). Idempotent via ``IF NOT EXISTS``; a no-op on the
    production DB which already has them.
    """
    conn = _conn()
    fk_indexes = [
        ("report_repo_id", "reports", "repo_id"),
        ("batch_report_id", "batch", "report_id"),
        ("proposal_tracker_id", "proposals", "tracker_id"),
    ]
    for index_name, table, column in fk_indexes:
        if await _table_exists(table):
            await conn.execute_script(
                f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table}" ("{column}")'
            )


async def create_tables() -> None:
    """Create database tables (additive) and migrate schema.

    ``generate_schemas(safe=True)`` emits ``CREATE TABLE IF NOT EXISTS`` — purely
    additive at the table level, so an existing populated database is left intact.
    The historical ``migrate_database()`` runs afterward (idempotent) to evolve
    columns on legacy schemas.
    """
    await Tortoise.generate_schemas(safe=True)
    await migrate_database()
    logger.info("Database tables created")


async def save_report(
    *,
    config: Config | None = None,
    repo_id: int | None = None,
    commit_hash: str = "",
    previous_commit_hash: str | None = None,
    commit_count: int = 0,
    markpost_url: str | None = None,
    content: str | None = None,
    title: str = "",
    report_type: str = "repo_update",
) -> int:
    from progress.db.models import Report

    report = await Report.create(
        report_type=report_type,
        repo_id=repo_id,
        title=title,
        commit_hash=commit_hash,
        previous_commit_hash=previous_commit_hash or "",
        commit_count=commit_count,
        markpost_url=markpost_url or "",
        content=content,
    )
    logger.info(f"Report saved: {report.id} (type={report_type})")
    return report.id


__all__ = [
    "close_db",
    "create_tables",
    "database_connection",
    "init_db",
    "log_db_state",
    "migrate_database",
    "resolve_db_path",
    "save_report",
]


def __getattr__(name: str) -> Any:
    if name == "_require_db":
        raise AttributeError(
            "Database handle access is no longer supported under tortoise-orm; "
            "use the model querysets or in_transaction() directly."
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
