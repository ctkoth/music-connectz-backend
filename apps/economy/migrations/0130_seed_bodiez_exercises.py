"""Seed the BodieZ movement library.

A member picks from this list rather than typing a free-text name (see
BodieZExercise's docstring), so the library has to exist before anyone can
build a routine. Reversible: it deletes only the rows it created, by name, so
it never touches an exercise a later migration or admin action added.
"""
from django.db import migrations

EXERCISES = [
    ("Bench Press", "chest", "barbell"),
    ("Push-Up", "chest", "bodyweight"),
    ("Dumbbell Fly", "chest", "dumbbell"),
    ("Pull-Up", "back", "bodyweight"),
    ("Barbell Row", "back", "barbell"),
    ("Lat Pulldown", "back", "machine"),
    ("Deadlift", "back", "barbell"),
    ("Overhead Press", "shoulders", "barbell"),
    ("Lateral Raise", "shoulders", "dumbbell"),
    ("Face Pull", "shoulders", "band"),
    ("Bicep Curl", "arms", "dumbbell"),
    ("Tricep Pushdown", "arms", "machine"),
    ("Dip", "arms", "bodyweight"),
    ("Squat", "legs", "barbell"),
    ("Leg Press", "legs", "machine"),
    ("Lunge", "legs", "dumbbell"),
    ("Romanian Deadlift", "legs", "barbell"),
    ("Calf Raise", "legs", "machine"),
    ("Plank", "core", "bodyweight"),
    ("Hanging Leg Raise", "core", "bodyweight"),
    ("Cable Crunch", "core", "machine"),
    ("Russian Twist", "core", "bodyweight"),
    ("Running", "cardio", "bodyweight"),
    ("Rowing Machine", "cardio", "machine"),
    ("Burpee", "full_body", "bodyweight"),
    ("Kettlebell Swing", "full_body", "dumbbell"),
    ("Clean and Press", "full_body", "barbell"),
]


def seed(apps, schema_editor):
    BodieZExercise = apps.get_model("economy", "BodieZExercise")
    for name, muscle_group, equipment in EXERCISES:
        BodieZExercise.objects.get_or_create(
            name=name, defaults={"muscle_group": muscle_group, "equipment": equipment})


def unseed(apps, schema_editor):
    BodieZExercise = apps.get_model("economy", "BodieZExercise")
    BodieZExercise.objects.filter(name__in=[n for n, _, _ in EXERCISES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0129_bodiezexercise_bodiezroutine_bodiezsession_bodiezset"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
