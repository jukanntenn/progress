import functools
from json import dumps, loads

from tortoise import fields, migrations
from tortoise.migrations import operations as ops

from progress.utils.timezone import now_utc


class Migration(migrations.Migration):
    initial = True

    operations = [
        ops.CreateModel(
            name="Batch",
            fields=[
                ("id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ("report_id", fields.IntField()),
                ("title", fields.CharField(default="", max_length=255)),
                ("markpost_url", fields.CharField(default="", max_length=255)),
                ("seq", fields.IntField()),
                ("created_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
                ("updated_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
            ],
            options={"table": "batches", "app": "core", "unique_together": (("report_id", "seq"),), "pk_attr": "id"},
            bases=["BaseModel"],
        ),
        ops.CreateModel(
            name="Config",
            fields=[
                ("section", fields.CharField(primary_key=True, unique=True, db_index=True, max_length=64)),
                (
                    "data",
                    fields.JSONField(
                        default=dict, encoder=functools.partial(dumps, separators=(",", ":")), decoder=loads
                    ),
                ),
                ("updated_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
            ],
            options={"table": "config", "app": "core", "pk_attr": "section"},
            bases=["BaseModel"],
        ),
        ops.CreateModel(
            name="Report",
            fields=[
                ("id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ("report_type", fields.CharField(default="repo_update", max_length=255)),
                ("repo_id", fields.IntField(null=True)),
                ("title", fields.CharField(default="", max_length=255)),
                ("commit_hash", fields.CharField(max_length=255)),
                ("previous_commit_hash", fields.CharField(null=True, max_length=255)),
                ("commit_count", fields.IntField(default=1)),
                ("markpost_url", fields.CharField(null=True, max_length=255)),
                ("content", fields.TextField(null=True, unique=False)),
                ("created_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
            ],
            options={"table": "reports", "app": "core", "pk_attr": "id"},
            bases=["BaseModel"],
        ),
    ]
