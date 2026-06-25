from datetime import datetime
from zoneinfo import ZoneInfo

from peewee import (
    BooleanField,
    CharField,
    DateTimeField,
)

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
