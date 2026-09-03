from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0078_journalentry_journalmention"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="featured_url",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
    ]
