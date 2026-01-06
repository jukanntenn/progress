"""Database initialization and operations."""

import logging
from pathlib import Path
from zoneinfo import ZoneInfo

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


def create_tables():
    """Create database tables and migrate schema."""
    database.create_tables([Repository, Report], safe=True)

    logger.info("Database tables created")


def close_db():
    """Close database connection."""
    global database
    if database:
        database.close()
        logger.info("Database connection closed")


def save_report(
    repo_id: int,
    commit_hash: str,
    previous_commit_hash: str,
    commit_count: int,
    markpost_url: str = None,
    content: str = None,
) -> int:
    """Save report."""
    with database.atomic():
        report = Report.create(
            repo=repo_id,
            commit_hash=commit_hash,
            previous_commit_hash=previous_commit_hash,
            commit_count=commit_count,
            markpost_url=markpost_url,
            content=content,
        )
        logger.info(f"Report saved: {report.id}")
        return report.id
