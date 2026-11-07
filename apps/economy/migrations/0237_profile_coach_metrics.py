from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0236_profile_coach_factors"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="coach_metrics",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
