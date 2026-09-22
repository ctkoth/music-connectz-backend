"""Fourth batch of real, rights-cleared demo videos.

Three of the four match rows that have existed since 0130/0137 with no
video: "Bench Press" (flat barbell), "Incline Barbell Bench Press" and
"Decline Barbell Bench Press" — all barbell chest press, just missing
their bench-angle pair from 0137's own dumbbell trio. The fourth, Reverse
Barbell Curl, is a new row: a pronated-grip curl is a genuinely different
exercise from "Barbell Curl" (supinated grip) — it shifts the emphasis
toward the brachialis and forearms rather than being a filming variant of
the same movement, so it gets its own row rather than overwriting Barbell
Curl's demo_url.
"""
from django.db import migrations

NEW_EXERCISES = [
    ("Reverse Barbell Curl", "arms", "barbell", "/exercise-demos/reverse-barbell-curl.mp4"),
]

EXISTING_DEMOS = {
    "Bench Press": "/exercise-demos/barbell-bench-press.mp4",
    "Incline Barbell Bench Press": "/exercise-demos/barbell-incline-press.mp4",
    "Decline Barbell Bench Press": "/exercise-demos/barbell-decline-press.mp4",
}


def seed(apps, schema_editor):
    BodieZExercise = apps.get_model("economy", "BodieZExercise")
    for name, muscle_group, equipment, demo_url in NEW_EXERCISES:
        BodieZExercise.objects.get_or_create(
            name=name, defaults={"muscle_group": muscle_group, "equipment": equipment,
                                 "demo_url": demo_url})
    for name, demo_url in EXISTING_DEMOS.items():
        BodieZExercise.objects.filter(name=name).update(demo_url=demo_url)


def unseed(apps, schema_editor):
    BodieZExercise = apps.get_model("economy", "BodieZExercise")
    BodieZExercise.objects.filter(name__in=[n for n, _, _, _ in NEW_EXERCISES]).delete()
    BodieZExercise.objects.filter(name__in=EXISTING_DEMOS.keys()).update(demo_url="")


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0140_bodiez_more_demo_videos"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
