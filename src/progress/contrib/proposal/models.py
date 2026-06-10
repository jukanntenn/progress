from datetime import datetime
from zoneinfo import ZoneInfo

from peewee import (
    CharField,
    DateTimeField,
    ForeignKeyField,
    Model,
)
from playhouse.shortcuts import ThreadSafeDatabaseMetadata

from progress.db.models import database_proxy

UTC = ZoneInfo("UTC")


class ProposalTrackerState(Model):
    kind = CharField(unique=True)
    last_seen_commit = CharField(null=True)
    last_check_time = DateTimeField(null=True)
    created_at = DateTimeField(default=lambda: datetime.now(UTC))
    updated_at = DateTimeField(default=lambda: datetime.now(UTC))

    class Meta:
        table_name = "proposal_trackers"
        database = database_proxy
        model_metadata_class = ThreadSafeDatabaseMetadata

    def save(self, *args, **kwargs):
        if self._pk is not None:
            self.updated_at = datetime.now(UTC)
        return super().save(*args, **kwargs)


class Proposal(Model):
    tracker = ForeignKeyField(
        ProposalTrackerState, backref="proposals", on_delete="CASCADE"
    )
    number = CharField()
    title = CharField(null=True)
    raw_status = CharField(default="")
    status = CharField()
    created_at = DateTimeField(default=lambda: datetime.now(UTC))
    updated_at = DateTimeField(default=lambda: datetime.now(UTC))

    class Meta:
        table_name = "proposals"
        database = database_proxy
        model_metadata_class = ThreadSafeDatabaseMetadata
        indexes = ((("tracker_id", "number"), True),)

    def save(self, *args, **kwargs):
        if self._pk is not None:
            self.updated_at = datetime.now(UTC)
        return super().save(*args, **kwargs)
