from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0079_profile_featured_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="battleentry",
            name="link",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
