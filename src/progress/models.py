"""Peewee ORM model definitions"""

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

UTC = ZoneInfo("UTC")

# Use DatabaseProxy for deferred database binding
database_proxy = DatabaseProxy()


class BaseModel(Model):
    """Base model class - supports thread-safe metadata"""

    class Meta:
        database = database_proxy
        model_metadata_class = ThreadSafeDatabaseMetadata


class Repository(BaseModel):
    """Repository model"""

    name = CharField()
    url = CharField(unique=True)
    branch = CharField()
    last_commit_hash = CharField(null=True)
    last_check_time = DateTimeField(null=True)
    enabled = BooleanField(default=True)
    created_at = DateTimeField(default=lambda: datetime.now(UTC))
    updated_at = DateTimeField(default=lambda: datetime.now(UTC))
    last_release_tag = CharField(null=True)
    last_release_commit_hash = CharField(null=True)
    last_release_check_time = DateTimeField(null=True)

    class Meta:
        table_name = "repositories"

    def save(self, *args, **kwargs):
        """Override save method to auto-update updated_at"""
        if self._pk is not None:
            self.updated_at = datetime.now(UTC)
        return super().save(*args, **kwargs)


class Report(BaseModel):
    """Report model"""

    repo = ForeignKeyField(
        Repository,
        backref="reports",
        on_delete="CASCADE",
        null=True,
    )
    title = CharField(default="")
    commit_hash = CharField()
    previous_commit_hash = CharField(null=True)
    commit_count = IntegerField(default=1)
    markpost_url = CharField(null=True)
    content = TextField(null=True)
    created_at = DateTimeField(default=lambda: datetime.now(UTC))

    class Meta:
        table_name = "reports"
