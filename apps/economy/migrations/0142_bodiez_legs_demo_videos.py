"""Fifth batch of real, rights-cleared demo videos — the first to touch legs.

Three match rows that have existed since 0130 with no video: "Squat"
(barbell), "Deadlift" (barbell) and "Leg Press" (machine). The other two are
new rows: Dumbbell Squat and Dumbbell Deadlift are genuinely different
movements from what the library already has — a dumbbell squat (weights held
at the sides) is a different load path from the existing "Kettlebell Goblet
Squat" (one weight held at the chest) and from the barbell back squat, and a
dumbbell deadlift (weights at the sides, shorter range) is a different
movement from the barbell "Deadlift" and "Romanian Deadlift" — so both get
their own rows rather than overwriting an existing demo_url.
"""
from django.db import migrations

NEW_EXERCISES = [
    ("Dumbbell Squat", "legs", "dumbbell", "/exercise-demos/dumbbell-squat.mp4"),
    ("Dumbbell Deadlift", "back", "dumbbell", "/exercise-demos/dumbbell-deadlift.mp4"),
]

EXISTING_DEMOS = {
    "Squat": "/exercise-demos/barbell-squat.mp4",
    "Deadlift": "/exercise-demos/barbell-deadlift.mp4",
    "Leg Press": "/exercise-demos/leg-press.mp4",
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
        ("economy", "0141_bodiez_chest_and_reverse_curl_videos"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
