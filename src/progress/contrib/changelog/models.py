import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from peewee import (
    BooleanField,
    CharField,
    DatabaseProxy,
    DateTimeField,
    ForeignKeyField,
    IntegerField,
    Model,
    TextField,
)
from playhouse.shortcuts import ThreadSafeDatabaseMetadata
from playhouse.sqlite_ext import JSONField

from progress.db.models import BaseModel

UTC = ZoneInfo("UTC")


class ChangelogTracker(BaseModel):
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

    def save(self, *args, **kwargs):
        if self._pk is not None:
            self.updated_at = datetime.now(UTC)
        return super().save(*args, **kwargs)


def create_tables():
    """Create database tables and migrate schema."""
    from . import database

    database.create_tables(
        [
            ChangelogTracker,
        ],
        safe=True,
    )

    logger.info("Database tables created")
