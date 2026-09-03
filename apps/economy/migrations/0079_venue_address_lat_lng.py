from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0078_journalentry_journalmention"),
    ]

    operations = [
        migrations.AddField(
            model_name="venue",
            name="address",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="venue",
            name="lat",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="venue",
            name="lng",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
