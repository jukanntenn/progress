from tortoise import fields

from progress.db.base import BaseModel
from progress.utils.timezone import now_utc


class Config(BaseModel):
    section = fields.CharField(max_length=64, primary_key=True)
    data = fields.JSONField(default=dict)
    updated_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "config"


__all__ = ["Config"]
