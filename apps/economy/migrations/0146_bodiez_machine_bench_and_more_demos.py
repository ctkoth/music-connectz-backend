"""Seventh batch of real, rights-cleared demo videos.

"Machine Bench Press" is a NEW row — a fixed-path machine press is a
different movement from every existing "Bench Press" row (all barbell or
dumbbell, free-weight), the same distinction 0137 already drew between
Dumbbell Squat and the barbell/kettlebell squat variants: different load
path, different row, never a relabel of an existing one.

Cable Woodchopper and Barbell Row both already existed (0130/0137) with no
video; this only sets their demo_url, same shape 0144's EXISTING_DEMOS used.

Cable Crunch is NOT touched here. It already carries a real demo_url from
migration 0144 (`cable-crunch.mp4`) — a second real clip of the same
exercise was in this batch too, but overwriting a working video with
another one needs a reason ("the first one was wrong", "this one shows the
setup better"), and neither was true here. Skipped rather than swapped
without cause.
"""
from django.db import migrations

NEW_EXERCISES = [
    ("Machine Bench Press", "chest", "machine", "/exercise-demos/machine-bench-press.mp4"),
]

EXISTING_DEMOS = {
    "Cable Woodchopper": "/exercise-demos/cable-woodchopper.mp4",
    "Barbell Row": "/exercise-demos/barbell-row.mp4",
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
        ("economy", "0145_bodiez_jefit_muscle_groups"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
