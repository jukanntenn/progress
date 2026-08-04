from tortoise import fields, migrations
from tortoise.fields.base import OnDelete
from tortoise.migrations import operations as ops

from progress.utils.timezone import now_utc


class Migration(migrations.Migration):
    initial = True

    operations = [
        ops.CreateModel(
            name="ProposalTrackerState",
            fields=[
                ("id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ("kind", fields.CharField(unique=True, max_length=32)),
                ("last_seen_commit", fields.CharField(null=True, max_length=255)),
                ("last_check_time", fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
                ("created_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
                ("updated_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
            ],
            options={
                "table": "proposal_tracker_states",
                "app": "proposal",
                "pk_attr": "id",
                "table_description": "Checkpoint row for one proposal kind (e.g. ``eip``).",
            },
            bases=["BaseModel"],
        ),
        ops.CreateModel(
            name="Proposal",
            fields=[
                ("id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                (
                    "tracker",
                    fields.ForeignKeyField(
                        "proposal.ProposalTrackerState",
                        source_field="tracker_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="proposals",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                ("number", fields.CharField(max_length=64)),
                ("title", fields.CharField(null=True, max_length=512)),
                ("raw_status", fields.CharField(default="", max_length=128)),
                ("status", fields.CharField(max_length=64)),
                ("created_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
                ("updated_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
            ],
            options={
                "table": "proposals",
                "app": "proposal",
                "unique_together": (("tracker_id", "number"),),
                "pk_attr": "id",
                "table_description": "A single tracked proposal (spec proposal §2).",
            },
            bases=["BaseModel"],
        ),
    ]
