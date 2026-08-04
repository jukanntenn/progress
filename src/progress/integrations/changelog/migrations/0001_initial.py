from tortoise import fields, migrations
from tortoise.migrations import operations as ops

from progress.utils.timezone import now_utc


class Migration(migrations.Migration):
    initial = True

    operations = [
        ops.CreateModel(
            name="ChangelogTracker",
            fields=[
                ("id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ("name", fields.CharField(max_length=255)),
                ("url", fields.CharField(unique=True, max_length=1024)),
                ("parser_type", fields.CharField(default="markdown_heading", max_length=64)),
                ("enabled", fields.BooleanField(default=True)),
                ("last_seen_version", fields.CharField(null=True, max_length=255)),
                ("last_check_time", fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
                ("created_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
                ("updated_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
            ],
            options={
                "table": "changelog_trackers",
                "app": "changelog",
                "pk_attr": "id",
                "table_description": "Changelog source with last-seen version checkpoint (spec changelog §2).",
            },
            bases=["BaseModel"],
        ),
    ]
