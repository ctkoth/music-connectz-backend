from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0235_challengez_filters"),
    ]

    operations = [
        migrations.AddField(
            model_name="venueevent",
            name="lat",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="venueevent",
            name="lng",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
