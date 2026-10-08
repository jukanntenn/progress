from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("changelog", "0002_changelog_learned_rule")]

    initial = False

    operations = [
        ops.AddField(
            model_name="ChangelogTracker",
            name="use_proxy",
            field=fields.BooleanField(default=False),
        ),
    ]
