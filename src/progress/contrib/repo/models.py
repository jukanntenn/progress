"""GitHubOwner model (table: github_owners)."""

from tortoise import fields

from progress.db.models.base import BaseModel
from progress.utils.timezone import now_utc


class GitHubOwner(BaseModel):
    """A monitored GitHub user/org whose repositories are discovered."""

    id: int = fields.IntField(primary_key=True)  # ty: ignore[invalid-assignment]
    owner_type: str = fields.CharField(max_length=255)  # ty: ignore[invalid-assignment]
    name: str = fields.CharField(max_length=255)  # ty: ignore[invalid-assignment]
    enabled: bool = fields.BooleanField(default=True)  # ty: ignore[invalid-assignment]
    last_check_time = fields.DatetimeField(null=True, default=None)
    last_tracked_repo = fields.DatetimeField(null=True, default=None)
    created_at = fields.DatetimeField(default=now_utc)
    updated_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "github_owners"
        unique_together = (("owner_type", "name"),)


__all__ = ["GitHubOwner"]
