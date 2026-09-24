"""Three more real, rights-cleared demo videos — the second batch after
0138. Two of the five clips in this round were byte-identical re-sends of
ones 0138 already used (tricep kickback, dumbbell tricep extension) and
are skipped here rather than overwritten with an indistinguishable copy.

Of the three new ones, only one matches an existing row: "Lateral Raise"
(shoulders, dumbbell) was seeded in 0130 and gets its demo_url set. Front
Raise and Dumbbell Shoulder Press are both new rows — Dumbbell Shoulder
Press is NOT the same exercise as the barbell-tagged "Overhead Press"
0130 already seeded (different equipment, different stabilization
demand), so this adds it rather than reassigning the barbell row's
equipment, the same reasoning 0137/0138 already applied to Barbell Curl
vs. Bicep Curl.
"""
from django.db import migrations

NEW_EXERCISES = [
    ("Dumbbell Front Raise", "shoulders", "dumbbell", "/exercise-demos/dumbbell-front-raise.mp4"),
    ("Dumbbell Shoulder Press", "shoulders", "dumbbell", "/exercise-demos/dumbbell-shoulder-press.mp4"),
]

EXISTING_DEMOS = {
    "Lateral Raise": "/exercise-demos/dumbbell-lateral-raise.mp4",
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
        ("economy", "0138_bodiez_demo_videos"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
