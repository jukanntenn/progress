"""Database initialization and operations."""

import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from peewee import CharField, DateTimeField
from playhouse.migrate import SqliteMigrator, migrate
from playhouse.pool import PooledSqliteDatabase

from progress.config import Config
from progress.consts import DB_MAX_CONNECTIONS, DB_PRAGMAS, DB_STALE_TIMEOUT
from progress.db.models import (
    Batch,
    Report,
    Repository,
    database_proxy,
)

logger = logging.getLogger(__name__)

database = None
UTC = ZoneInfo("UTC")


def init_db(db_path: str):
    """Initialize database connection pool."""
    global database

    db_file = Path(db_path)
    db_dir = db_file.parent
    if db_dir and not db_dir.exists():
        db_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created database directory: {db_dir}")

    database = PooledSqliteDatabase(
        db_path,
        max_connections=DB_MAX_CONNECTIONS,
        stale_timeout=DB_STALE_TIMEOUT,
        pragmas=DB_PRAGMAS,
        check_same_thread=False,
    )

    database_proxy.initialize(database)
    logger.info(f"Database connection pool initialized: {db_path}")


def migrate_database():
    """Migrate database schema to latest version."""
    from progress.db.migration_add_owner_monitoring import (
        apply as migrate_owner_monitoring,
    )

    migrator = SqliteMigrator(database)

    migrate_owner_monitoring(database)

    def _table_exists(table_name: str) -> bool:
        row = database.execute_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None

    def _existing_columns(table_name: str) -> set[str]:
        cursor = database.execute_sql(f"PRAGMA table_info({table_name})")
        return {row[1] for row in cursor.fetchall()}

    if _table_exists("rustrfc") and not _table_exists("rust_rfcs"):
        database.execute_sql("ALTER TABLE rustrfc RENAME TO rust_rfcs")

    cursor = database.execute_sql("PRAGMA table_info(reports)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    if "title" not in existing_columns:
        logger.info("Migrating: Adding 'title' column to reports table")
        migrate(
            migrator.add_column(
                "reports",
                "title",
                CharField(default=""),
            )
        )
        logger.info("Migration completed: 'title' column added")

    if "report_type" not in existing_columns:
        logger.info("Migrating: Adding 'report_type' column to reports table")
        migrate(
            migrator.add_column(
                "reports",
                "report_type",
                CharField(default="repo_update"),
            )
        )
        database.execute_sql(
            "UPDATE reports SET report_type = 'repo_update' WHERE report_type IS NULL OR report_type = ''"
        )
        logger.info("Migration completed: 'report_type' column added")

    cursor = database.execute_sql("PRAGMA table_info(reports)")
    columns_info = cursor.fetchall()
    columns = {c[1] for c in columns_info}
    repo_column_info = next((c for c in columns_info if c[1] == "repo_id"), None)

    if repo_column_info and repo_column_info[3] != 0:
        logger.info("Migrating: Making 'repo' column nullable in reports table")
        title_expr = "title" if "title" in columns else "''"
        report_type_expr = (
            "report_type" if "report_type" in columns else "'repo_update'"
        )
        database.execute_sql(
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
        database.execute_sql(
            "INSERT INTO reports_new (id, repo_id, title, report_type, commit_hash, previous_commit_hash, "
            "commit_count, markpost_url, content, created_at) "
            f"SELECT id, repo_id, {title_expr}, {report_type_expr}, commit_hash, previous_commit_hash, "
            "commit_count, markpost_url, content, created_at FROM reports"
        )
        database.execute_sql("DROP TABLE reports")
        database.execute_sql("ALTER TABLE reports_new RENAME TO reports")
        logger.info("Migration completed: 'repo' column is now nullable")

    cursor = database.execute_sql("PRAGMA table_info(repositories)")
    repo_existing_columns = {row[1] for row in cursor.fetchall()}

    if "last_release_tag" not in repo_existing_columns:
        logger.info("Migrating: Adding release tracking columns to repositories table")
        migrate(
            migrator.add_column(
                "repositories",
                "last_release_tag",
                CharField(null=True),
            ),
            migrator.add_column(
                "repositories",
                "last_release_commit_hash",
                CharField(null=True),
            ),
            migrator.add_column(
                "repositories",
                "last_release_check_time",
                DateTimeField(null=True),
            ),
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
        if _table_exists(table):
            logger.info(f"Migrating: Dropping old proposal table '{table}'")
            database.execute_sql(f"DROP TABLE IF EXISTS {table}")
            logger.info(f"Migration completed: '{table}' dropped")

    if _table_exists("proposal_trackers"):
        cols = _existing_columns("proposal_trackers")
        if "tracker_type" in cols:
            logger.info(
                "Migrating: Dropping old proposal_trackers table for new schema"
            )
            database.execute_sql("DROP TABLE IF EXISTS proposal_trackers")
            logger.info("Migration completed: old proposal_trackers dropped")

    if _table_exists("discovered_repositories"):
        cols = _existing_columns("discovered_repositories")
        if "updated_at" not in cols:
            logger.info(
                "Migrating: Adding 'updated_at' column to discovered_repositories table"
            )
            migrate(
                migrator.add_column(
                    "discovered_repositories",
                    "updated_at",
                    DateTimeField(null=True),
                )
            )
            logger.info("Migration completed: 'updated_at' column added")


def close_db():
    """Close database connection."""
    global database
    if database:
        database.close()
        logger.info("Database connection closed")


def create_tables():
    """Create database tables and migrate schema."""
    from progress.contrib.changelog.models import ChangelogTracker
    from progress.contrib.proposal.models import Proposal, ProposalTrackerState
    from progress.contrib.repo.models import DiscoveredRepository, GitHubOwner

    database.create_tables(
        [
            Repository,
            Report,
            Batch,
            GitHubOwner,
            DiscoveredRepository,
            ChangelogTracker,
        ],
        safe=True,
    )

    migrate_database()

    database.create_tables(
        [
            ProposalTrackerState,
            Proposal,
        ],
        safe=True,
    )

    logger.info("Database tables created")


def save_report(
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
    report = Report.create(
        report_type=report_type,
        repo=repo_id,
        title=title,
        commit_hash=commit_hash,
        previous_commit_hash=previous_commit_hash or "",
        commit_count=commit_count,
        markpost_url=markpost_url or "",
        content=content,
    )
    logger.info(f"Report saved: {report.id} (type={report_type})")
    return report.id
