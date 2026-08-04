from tortoise import fields, migrations
from tortoise.migrations import operations as ops


class Migration(migrations.Migration):
    dependencies = [("changelog", "0001_initial")]

    initial = False

    operations = [
        ops.AddField(
            model_name="ChangelogTracker",
            name="learned_rule",
            field=fields.TextField(null=True, unique=False),
        ),
        ops.AddField(
            model_name="ChangelogTracker",
            name="rule_success_count",
            field=fields.IntField(default=0),
        ),
    ]
