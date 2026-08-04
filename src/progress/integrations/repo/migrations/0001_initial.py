from tortoise import fields, migrations
from tortoise.migrations import operations as ops

from progress.utils.timezone import now_utc


class Migration(migrations.Migration):
    initial = True

    operations = [
        ops.CreateModel(
            name="GitHubOwner",
            fields=[
                ("id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ("owner_type", fields.CharField(default="organization", max_length=32)),
                ("name", fields.CharField(max_length=255)),
                ("enabled", fields.BooleanField(default=True)),
                ("last_check_time", fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
                ("last_tracked_repo", fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
                ("created_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
                ("updated_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
            ],
            options={
                "table": "github_owners",
                "app": "repo",
                "unique_together": (("owner_type", "name"),),
                "pk_attr": "id",
                "table_description": "GitHub owner (organization or user) monitored for new repositories.",
            },
            bases=["BaseModel"],
        ),
        ops.CreateModel(
            name="Repository",
            fields=[
                ("id", fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ("name", fields.CharField(default="", max_length=255)),
                ("url", fields.CharField(unique=True, max_length=255)),
                ("branch", fields.CharField(default="main", max_length=255)),
                ("enabled", fields.BooleanField(default=True)),
                ("last_commit_hash", fields.CharField(null=True, max_length=255)),
                ("last_check_time", fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
                ("last_release_tag", fields.CharField(null=True, max_length=255)),
                ("last_release_commit_hash", fields.CharField(null=True, max_length=255)),
                ("last_release_check_time", fields.DatetimeField(null=True, auto_now=False, auto_now_add=False)),
                ("created_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
                ("updated_at", fields.DatetimeField(default=now_utc, auto_now=False, auto_now_add=False)),
            ],
            options={
                "table": "repositories",
                "app": "repo",
                "pk_attr": "id",
                "table_description": "Tracked GitHub repository with commit/release checkpoints (spec repo §2).",
            },
            bases=["BaseModel"],
        ),
    ]
