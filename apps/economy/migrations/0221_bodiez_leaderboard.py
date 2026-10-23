import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0220_mangaz"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="BodieZLeaderboard",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("opted_in_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                              related_name="bodiez_leaderboard",
                                              to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
