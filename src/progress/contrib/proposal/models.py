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


class ProposalTracker(BaseModel):
    tracker_type = CharField()
    repo_url = CharField()
    branch = CharField(default="main")
    enabled = BooleanField(default=True)
    proposal_dir = CharField(default="")
    file_pattern = CharField(default="")
    last_seen_commit = CharField(null=True)
    last_check_time = DateTimeField(null=True)
    created_at = DateTimeField(default=lambda: datetime.now(UTC))
    updated_at = DateTimeField(default=lambda: datetime.now(UTC))

    class Meta:
        table_name = "proposal_trackers"
        indexes = (
            (
                (
                    "tracker_type",
                    "repo_url",
                    "branch",
                    "proposal_dir",
                    "file_pattern",
                ),
                True,
            ),
        )

    def save(self, *args, **kwargs):
        if self._pk is not None:
            self.updated_at = datetime.now(UTC)
        return super().save(*args, **kwargs)


class EIP(BaseModel):
    eip_number = IntegerField()
    title = CharField()
    status = CharField()
    type = CharField(null=True)
    category = CharField(null=True)
    author = TextField(null=True)
    created_date = DateTimeField(null=True)
    file_path = CharField()
    last_seen_commit = CharField(null=True)
    last_check_time = DateTimeField(null=True)
    analysis_summary = TextField(null=True)
    analysis_detail = TextField(null=True)
    created_at = DateTimeField(default=lambda: datetime.now(UTC))
    updated_at = DateTimeField(default=lambda: datetime.now(UTC))

    class Meta:
        table_name = "eips"
        indexes = ((("eip_number",), True),)

    def save(self, *args, **kwargs):
        if self._pk is not None:
            self.updated_at = datetime.now(UTC)
        return super().save(*args, **kwargs)


class RustRFC(BaseModel):
    rfc_number = IntegerField()
    title = CharField()
    status = CharField()
    author = TextField(null=True)
    created_date = DateTimeField(null=True)
    file_path = CharField()
    last_seen_commit = CharField(null=True)
    last_check_time = DateTimeField(null=True)
    analysis_summary = TextField(null=True)
    analysis_detail = TextField(null=True)
    created_at = DateTimeField(default=lambda: datetime.now(UTC))
    updated_at = DateTimeField(default=lambda: datetime.now(UTC))

    class Meta:
        table_name = "rust_rfcs"
        indexes = ((("rfc_number",), True),)

    def save(self, *args, **kwargs):
        if self._pk is not None:
            self.updated_at = datetime.now(UTC)
        return super().save(*args, **kwargs)


class PEP(BaseModel):
    pep_number = IntegerField()
    title = CharField()
    status = CharField()
    type = CharField(null=True)
    topic = CharField(null=True)
    author = TextField(null=True)
    created_date = DateTimeField(null=True)
    file_path = CharField()
    last_seen_commit = CharField(null=True)
    last_check_time = DateTimeField(null=True)
    analysis_summary = TextField(null=True)
    analysis_detail = TextField(null=True)
    created_at = DateTimeField(default=lambda: datetime.now(UTC))
    updated_at = DateTimeField(default=lambda: datetime.now(UTC))

    class Meta:
        table_name = "peps"
        indexes = ((("pep_number",), True),)

    def save(self, *args, **kwargs):
        if self._pk is not None:
            self.updated_at = datetime.now(UTC)
        return super().save(*args, **kwargs)


class DjangoDEP(BaseModel):
    dep_number = IntegerField()
    title = CharField()
    status = CharField()
    type = CharField(null=True)
    created_date = DateTimeField(null=True)
    file_path = CharField()
    last_seen_commit = CharField(null=True)
    last_check_time = DateTimeField(null=True)
    analysis_summary = TextField(null=True)
    analysis_detail = TextField(null=True)
    created_at = DateTimeField(default=lambda: datetime.now(UTC))
    updated_at = DateTimeField(default=lambda: datetime.now(UTC))

    class Meta:
        table_name = "django_deps"
        indexes = ((("dep_number",), True),)

    def save(self, *args, **kwargs):
        if self._pk is not None:
            self.updated_at = datetime.now(UTC)
        return super().save(*args, **kwargs)


class ProposalEvent(BaseModel):
    eip = ForeignKeyField(EIP, backref="events", on_delete="CASCADE", null=True)
    rust_rfc = ForeignKeyField(
        RustRFC, backref="events", on_delete="CASCADE", null=True
    )
    pep = ForeignKeyField(PEP, backref="events", on_delete="CASCADE", null=True)
    django_dep = ForeignKeyField(
        DjangoDEP, backref="events", on_delete="CASCADE", null=True
    )
    event_type = CharField()
    old_status = CharField(null=True)
    new_status = CharField(null=True)
    commit_hash = CharField()
    detected_at = DateTimeField(default=lambda: datetime.now(UTC))
    metadata = JSONField(default=dict)

    class Meta:
        table_name = "proposal_events"

    @property
    def proposal(self):
        if self.eip_id is not None:
            return self.eip
        if self.rust_rfc_id is not None:
            return self.rust_rfc
        if self.pep_id is not None:
            return self.pep
        if self.django_dep_id is not None:
            return self.django_dep
        return None


def create_tables():
    """Create database tables and migrate schema."""
    from . import database

    database.create_tables(
        [
            ProposalTracker,
            EIP,
            RustRFC,
            PEP,
            DjangoDEP,
            ProposalEvent,
        ],
        safe=True,
    )

    logger.info("Database tables created")
