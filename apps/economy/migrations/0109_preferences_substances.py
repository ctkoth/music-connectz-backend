# Generated migration for UserPreferences and UserSubstances models

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0108_personality_result"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserVybeZPreferences",
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
                (
                    "gender_interested",
                    models.CharField(
                        choices=[
                            ("men", "Men"),
                            ("women", "Women"),
                            ("non_binary", "Non-binary"),
                            ("everyone", "Everyone"),
                        ],
                        default="everyone",
                        max_length=16,
                    ),
                ),
                (
                    "relationship_type",
                    models.CharField(
                        choices=[
                            ("collabs", "Collaborations only"),
                            ("dating", "Dating / Romance"),
                            ("both", "Both"),
                        ],
                        default="both",
                        max_length=16,
                    ),
                ),
                (
                    "long_term",
                    models.CharField(
                        choices=[
                            ("short", "Short-term / casual"),
                            ("long", "Long-term"),
                            ("either", "Either"),
                        ],
                        default="either",
                        max_length=16,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="vybez_preferences",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "VybeZ Preferences",
            },
        ),
        migrations.CreateModel(
            name="UserVybeZSubstances",
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
                (
                    "alcohol",
                    models.CharField(
                        choices=[
                            ("none", "Don't use"),
                            ("occasionally", "Occasionally"),
                            ("regularly", "Regularly"),
                            ("prefer_not", "Prefer not to say"),
                        ],
                        default="prefer_not",
                        max_length=16,
                    ),
                ),
                (
                    "cannabis",
                    models.CharField(
                        choices=[
                            ("none", "Don't use"),
                            ("occasionally", "Occasionally"),
                            ("regularly", "Regularly"),
                            ("prefer_not", "Prefer not to say"),
                        ],
                        default="prefer_not",
                        max_length=16,
                    ),
                ),
                (
                    "tobacco",
                    models.CharField(
                        choices=[
                            ("none", "Don't use"),
                            ("occasionally", "Occasionally"),
                            ("regularly", "Regularly"),
                            ("prefer_not", "Prefer not to say"),
                        ],
                        default="prefer_not",
                        max_length=16,
                    ),
                ),
                (
                    "psychedelics",
                    models.CharField(
                        choices=[
                            ("never", "Never tried"),
                            ("tried", "Tried before"),
                            ("open", "Open to trying"),
                            ("prefer_not", "Prefer not to say"),
                        ],
                        default="prefer_not",
                        max_length=16,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="vybez_substances",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "VybeZ Substances",
            },
        ),
    ]
