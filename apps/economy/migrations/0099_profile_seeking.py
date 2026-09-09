# Generated migration for adding seeking field to Profile

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('economy', '0098_listenprogress'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='seeking',
            field=models.JSONField(blank=True, default=dict, help_text='{"active": bool, "help_needed": str, "status": str, "current_reach": str, "rate": str}'),
        ),
    ]
