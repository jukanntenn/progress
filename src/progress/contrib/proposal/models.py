from datetime import datetime
from zoneinfo import ZoneInfo

from peewee import (
    CharField,
    DateTimeField,
    ForeignKeyField,
)

from progress.db.models import BaseModel

UTC = ZoneInfo("UTC")


class ProposalTrackerState(BaseModel):
    kind = CharField(unique=True)
    last_seen_commit = CharField(null=True)
    last_check_time = DateTimeField(null=True)
    created_at = DateTimeField(default=lambda: datetime.now(UTC))
    updated_at = DateTimeField(default=lambda: datetime.now(UTC))

    class Meta:
        table_name = "proposal_trackers"


class Proposal(BaseModel):
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
        indexes = ((("tracker_id", "number"), True),)
