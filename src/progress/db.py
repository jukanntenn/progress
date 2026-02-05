"""Database initialization and operations."""

import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from peewee import CharField, DateTimeField
from playhouse.migrate import SqliteMigrator, migrate
from playhouse.pool import PooledSqliteDatabase

from .consts import DB_MAX_CONNECTIONS, DB_PRAGMAS, DB_STALE_TIMEOUT
from .models import Report, Repository, database_proxy

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
    migrator = SqliteMigrator(database)

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

    cursor = database.execute_sql("PRAGMA table_info(reports)")
    columns_info = cursor.fetchall()
    repo_column_info = next((c for c in columns_info if c[1] == "repo_id"), None)

    if repo_column_info and repo_column_info[3] != 0:
        logger.info("Migrating: Making 'repo' column nullable in reports table")
        database.execute_sql(
            "CREATE TABLE reports_new ("
            "id INTEGER PRIMARY KEY,"
            "repo_id INTEGER NULL REFERENCES repositories(id) ON DELETE CASCADE,"
            "title VARCHAR NOT NULL DEFAULT '',"
            "commit_hash VARCHAR NOT NULL,"
            "previous_commit_hash VARCHAR,"
            "commit_count INTEGER NOT NULL DEFAULT 1,"
            "markpost_url VARCHAR,"
            "content TEXT,"
            "created_at VARCHAR NOT NULL)"
        )
        database.execute_sql(
            "INSERT INTO reports_new (id, repo_id, commit_hash, previous_commit_hash, "
            "commit_count, markpost_url, content, created_at) "
            "SELECT id, repo_id, commit_hash, previous_commit_hash, "
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


def create_tables():
    """Create database tables and migrate schema."""
    database.create_tables([Repository, Report], safe=True)
    migrate_database()

    logger.info("Database tables created")


def close_db():
    """Close database connection."""
    global database
    if database:
        database.close()
        logger.info("Database connection closed")


def save_report(
    repo_id: int | None,
    commit_hash: str,
    previous_commit_hash: str,
    commit_count: int,
    markpost_url: str | None = None,
    content: str | None = None,
    title: str = "",
) -> int:
    """Save report."""
    with database.atomic():
        report = Report.create(
            repo=repo_id,
            title=title,
            commit_hash=commit_hash,
            previous_commit_hash=previous_commit_hash,
            commit_count=commit_count,
            markpost_url=markpost_url,
            content=content,
        )
        logger.info(f"Report saved: {report.id}")
        return report.id
