from tortoise import fields, migrations
from tortoise.migrations import operations as ops

from progress.utils.timezone import now_utc


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    initial = False

    operations = [
        ops.CreateModel(
            name="User",
            fields=[
                ("id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ("username", fields.CharField(unique=True, db_index=True, max_length=64)),
                ("email", fields.CharField(default="", max_length=255)),
                ("hashed_password", fields.CharField(max_length=255)),
                ("is_active", fields.BooleanField(default=True)),
                ("is_superuser", fields.BooleanField(default=False)),
                ("created_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
                ("updated_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
            ],
            options={"table": "users", "app": "core", "pk_attr": "id"},
            bases=["BaseModel"],
        ),
    ]
