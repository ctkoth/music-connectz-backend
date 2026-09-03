from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0080_battleentry_link"),
    ]

    operations = [
        migrations.AddField(
            model_name="journalentry",
            name="link",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
