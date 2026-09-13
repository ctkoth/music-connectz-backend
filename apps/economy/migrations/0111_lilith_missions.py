# Generated migration for Lilith adaptive mission system

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0110_funnelevent_enhanced"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LilithMission",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("stage", models.CharField(
                    choices=[
                        ("onboarding", "Onboarding"),
                        ("engagement", "Engagement"),
                        ("active", "Active Community Member"),
                    ],
                    max_length=16,
                )),
                ("key", models.CharField(max_length=64)),
                ("title", models.CharField(max_length=128)),
                ("description", models.TextField()),
                ("action", models.CharField(max_length=64)),
                ("action_target", models.PositiveIntegerField(default=1)),
                ("reward_spinaz", models.PositiveIntegerField(default=0)),
                ("reward_energy", models.PositiveIntegerField(default=0)),
                ("is_priority", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lilith_missions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-is_priority", "created_at"],
                "unique_together": {("user", "key", "stage")},
            },
        ),
        migrations.CreateModel(
            name="LilithProgress",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("progress", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "mission",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="progress_track",
                        to="economy.lilithmission",
                    ),
                ),
            ],
        ),
    ]
