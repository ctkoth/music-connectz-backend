from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0110_profile_verification_tracking"),
    ]

    operations = [
        migrations.AddField(
            model_name="membergroup",
            name="icon",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
