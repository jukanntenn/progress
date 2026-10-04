from tortoise import fields, migrations
from tortoise.migrations import operations as ops

from progress.utils.timezone import now_utc


class Migration(migrations.Migration):
    initial = True

    operations = [
        ops.CreateModel(
            name="V2exTracker",
            fields=[
                ("id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ("source", fields.CharField(max_length=64, unique=True)),
                ("last_topic_id", fields.BigIntField(null=True)),
                ("last_check_time", fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
                ("created_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
                ("updated_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
            ],
            options={
                "table": "v2ex_trackers",
                "app": "v2ex",
                "pk_attr": "id",
                "table_description": "One row per tracked V2EX source (spec v2ex §5).",
            },
            bases=["BaseModel"],
        ),
    ]
