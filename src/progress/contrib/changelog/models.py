import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from peewee import AutoField, BooleanField, CharField, DateTimeField
from progress.db.models import BaseModel

logger = logging.getLogger(__name__)

UTC = ZoneInfo("UTC")


class ChangelogTracker(BaseModel):
    id = AutoField()
    name = CharField()
    url = CharField(unique=True)
    parser_type = CharField()
    last_seen_version = CharField(null=True)
    enabled = BooleanField(default=True)
    last_check_time = DateTimeField(null=True)
    created_at = DateTimeField(default=lambda: datetime.now(UTC))
    updated_at = DateTimeField(default=lambda: datetime.now(UTC))

    class Meta:
        table_name = "changelog_trackers"


def create_tables():
    """Create database tables and migrate schema."""
    from ...db import _require_db

    _require_db().create_tables(
        [
            ChangelogTracker,
        ],
        safe=True,
    )

    logger.info("Database tables created")
