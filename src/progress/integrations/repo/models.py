"""Tortoise state models for the ``repo`` integration (spec 03 / spec repo §2).

Per spec 03, this is the "fat model" home for repo state: the model carries
both the schema and the small query helpers the tracker needs. There is no
separate repository/DAO layer.

Two models live here:

- :class:`Repository` — one row per tracked repo. Carries the commit/release
  checkpoints that the tracker advances (spec repo §2). The two checkpoint
  groups are intentionally orthogonal: a check may advance only one.
- :class:`GitHubOwner` — one row per monitored GitHub owner (org or user).
  Used to discover new repos under that owner.
"""

from __future__ import annotations

from typing import override

from tortoise import fields

from progress.db.base import BaseModel
from progress.utils.timezone import now_utc


class Repository(BaseModel):
    """Tracked GitHub repository with commit/release checkpoints (spec repo §2)."""

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255, default="")
    url = fields.CharField(max_length=255, unique=True)
    branch = fields.CharField(max_length=255, default="main")
    enabled = fields.BooleanField(default=True)
    track_commits = fields.BooleanField(default=True, db_default=True)
    track_releases = fields.BooleanField(default=True, db_default=True)
    last_commit_hash = fields.CharField(max_length=255, null=True)
    last_check_time = fields.DatetimeField(null=True)
    last_release_tag = fields.CharField(max_length=255, null=True)
    last_release_commit_hash = fields.CharField(max_length=255, null=True)
    last_release_check_time = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(default=now_utc)
    updated_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "repositories"

    @override
    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"<Repository id={self.id} url={self.url!r} branch={self.branch!r}>"


class GitHubOwner(BaseModel):
    """GitHub owner (organization or user) monitored for new repositories."""

    id = fields.IntField(primary_key=True)
    owner_type = fields.CharField(max_length=32, default="organization")
    name = fields.CharField(max_length=255)
    enabled = fields.BooleanField(default=True)
    last_check_time = fields.DatetimeField(null=True)
    last_tracked_repo = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(default=now_utc)
    updated_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "github_owners"
        unique_together = (("owner_type", "name"),)

    @override
    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"<GitHubOwner id={self.id} name={self.name!r} type={self.owner_type!r}>"


__all__ = ["GitHubOwner", "Repository"]
