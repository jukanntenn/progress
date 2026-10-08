from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("changelog", "0002_changelog_learned_rule")]

    initial = False

    operations = [
        ops.AddField(
            model_name="ChangelogTracker",
            name="proxy",
            # db_default must reach the DDL: SQLite refuses ADD COLUMN ... NOT NULL
            # without a database-level default, so a python-only default fails.
            field=fields.CharField(default="", db_default="", max_length=1024),
        ),
    ]
