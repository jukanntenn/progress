from tortoise import fields, migrations
from tortoise.migrations import operations as ops

from progress.utils.timezone import now_utc


class Migration(migrations.Migration):
    initial = True

    operations = [
        ops.CreateModel(
            name="FeedTracker",
            fields=[
                ("id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ("feed_id", fields.BigIntField(unique=True)),
                ("title", fields.CharField(max_length=512)),
                ("site_url", fields.CharField(null=True, max_length=1024)),
                ("last_entry_id", fields.BigIntField(null=True)),
                ("last_check_time", fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
                ("created_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
                ("updated_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
            ],
            options={
                "table": "feed_trackers",
                "app": "feed",
                "pk_attr": "id",
                "table_description": "One row per Miniflux feed tracked by the feed integration (spec feed §2).",
            },
            bases=["BaseModel"],
        ),
    ]
