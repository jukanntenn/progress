from tortoise import fields

from progress.db.base import BaseModel
from progress.utils.timezone import now_utc


class Report(BaseModel):
    id = fields.IntField(primary_key=True)
    report_type = fields.CharField(max_length=255, default="repo_update")
    repo_id = fields.IntField(null=True)
    title = fields.CharField(max_length=255, default="")
    commit_hash = fields.CharField(max_length=255)
    previous_commit_hash = fields.CharField(max_length=255, null=True)
    commit_count = fields.IntField(default=1)
    markpost_url = fields.CharField(max_length=255, null=True)
    content = fields.TextField(null=True)
    created_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "reports"


__all__ = ["Report"]
