from tortoise import fields

from progress.db.base import BaseModel
from progress.utils.timezone import now_utc


class User(BaseModel):
    id = fields.IntField(primary_key=True)
    username = fields.CharField(max_length=64, unique=True, index=True)
    email = fields.CharField(max_length=255, default="")
    hashed_password = fields.CharField(max_length=255)
    is_active = fields.BooleanField(default=True)
    is_superuser = fields.BooleanField(default=False)
    created_at = fields.DatetimeField(default=now_utc)
    updated_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "users"


__all__ = ["User"]
