# Generated migration for PersonalityResult model

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0107_offer_dismissal_and_prompt_walls"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PersonalityResult",
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
                    "test_type",
                    models.CharField(
                        choices=[
                            ("basic", "Basic 4-Question Test"),
                            ("detailed", "Detailed 8-Question Assessment"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "mbti_type",
                    models.CharField(
                        choices=[
                            ("ISTJ", "The Logistician"),
                            ("ISFJ", "The Defender"),
                            ("INFJ", "The Advocate"),
                            ("INTJ", "The Architect"),
                            ("ISTP", "The Virtuoso"),
                            ("ISFP", "The Adventurer"),
                            ("INFP", "The Mediator"),
                            ("INTP", "The Logician"),
                            ("ESTP", "The Entrepreneur"),
                            ("ESFP", "The Entertainer"),
                            ("ENFP", "The Campaigner"),
                            ("ENTP", "The Debater"),
                            ("ESTJ", "The Executive"),
                            ("ESFJ", "The Consul"),
                            ("ENFJ", "The Protagonist"),
                            ("ENTJ", "The Commander"),
                        ],
                        max_length=4,
                    ),
                ),
                ("answers", models.JSONField(default=list, help_text="Raw answers from the test")),
                (
                    "dimension_scores",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Score for each MBTI dimension (E/I, S/N, T/F, J/P)",
                        null=True,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="personality_results",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="personalityresult",
            index=models.Index(fields=["user", "-created_at"], name="economy_per_user_id_4c5a8b_idx"),
        ),
        migrations.AddIndex(
            model_name="personalityresult",
            index=models.Index(fields=["mbti_type"], name="economy_per_mbti_ty_9c3e2f_idx"),
        ),
    ]
