from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("repo", "0001_initial")]

    initial = False

    operations = [
        ops.AddField(
            model_name="Repository",
            name="track_commits",
            field=fields.BooleanField(default=True, db_default=True),
        ),
        ops.AddField(
            model_name="Repository",
            name="track_releases",
            field=fields.BooleanField(default=True, db_default=True),
        ),
    ]
