from django.db import migrations, models


class Migration(migrations.Migration):
    """Additive: when a live BodieZ session was chosen to stay on screen over other apps."""

    dependencies = [
        ("economy", "0242_anime_work"),
    ]

    operations = [
        migrations.AddField(
            model_name="bodiezsession",
            name="floated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
