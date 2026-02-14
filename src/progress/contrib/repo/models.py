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


class GitHubOwner(BaseModel):
    owner_type = CharField()
    name = CharField()
    enabled = BooleanField(default=True)
    last_check_time = DateTimeField(null=True)
    last_tracked_repo = DateTimeField(null=True)
    created_at = DateTimeField(default=lambda: datetime.now(UTC))
    updated_at = DateTimeField(default=lambda: datetime.now(UTC))

    class Meta:
        table_name = "github_owners"
        indexes = ((("owner_type", "name"), True),)

    def save(self, *args, **kwargs):
        if self._pk is not None:
            self.updated_at = datetime.now(UTC)
        return super().save(*args, **kwargs)


class DiscoveredRepository(BaseModel):
    owner = ForeignKeyField(
        GitHubOwner, backref="discovered_repos", on_delete="CASCADE"
    )
    repo_name = CharField()
    repo_url = CharField()
    description = TextField(null=True)
    discovered_at = DateTimeField(default=lambda: datetime.now(UTC))
    updated_at = DateTimeField(default=lambda: datetime.now(UTC))
    has_readme = BooleanField(default=False)
    readme_summary = TextField(null=True)
    readme_detail = TextField(null=True)
    readme_was_truncated = BooleanField(default=False)
    notified = BooleanField(default=False)

    class Meta:
        table_name = "discovered_repositories"
        indexes = ((("owner", "repo_name"), True),)

    def save(self, *args, **kwargs):
        if self._pk is not None:
            self.updated_at = datetime.now(UTC)
        return super().save(*args, **kwargs)
