"""Third batch of real, rights-cleared demo videos.

Three new rows — Dumbbell Row (a real gap: "Barbell Row" existed, no
dumbbell equivalent did), Zottman Curl (a distinct movement — pronated
lowering, supinated curling — not a variant of Bicep Curl or EZ Bar
Curl), Dumbbell Bench Press (flat pressing with dumbbells; "Dumbbell
Fly" is a different exercise and "Bench Press" is barbell-only). Two
existing rows from 0137 (Incline Dumbbell Press, Decline Dumbbell
Press) just get their demo_url set — they were seeded with the bench
angle in the name and no video, per that migration's own reasoning
about equipment vs. exercise name.
"""
from django.db import migrations

NEW_EXERCISES = [
    ("Dumbbell Row", "back", "dumbbell", "/exercise-demos/dumbbell-row.mp4"),
    ("Zottman Curl", "arms", "dumbbell", "/exercise-demos/zottman-curl.mp4"),
    ("Dumbbell Bench Press", "chest", "dumbbell", "/exercise-demos/dumbbell-bench-press.mp4"),
]

EXISTING_DEMOS = {
    "Incline Dumbbell Press": "/exercise-demos/dumbbell-incline-press.mp4",
    "Decline Dumbbell Press": "/exercise-demos/dumbbell-decline-press.mp4",
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
        ("economy", "0139_bodiez_shoulder_demo_videos"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
