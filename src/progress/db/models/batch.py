from tortoise import fields

from progress.db.base import BaseModel
from progress.utils.timezone import now_utc


class Batch(BaseModel):
    id = fields.IntField(primary_key=True)
    report_id = fields.IntField()
    title = fields.CharField(max_length=255, default="")
    markpost_url = fields.CharField(max_length=255, default="")
    seq = fields.IntField()
    created_at = fields.DatetimeField(default=now_utc)
    updated_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "batches"
        unique_together = (("report_id", "seq"),)


__all__ = ["Batch"]
