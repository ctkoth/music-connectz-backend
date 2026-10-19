"""Sixth batch of real, rights-cleared demo videos — the first ones done on
a cable stack.

All five match rows the library already has: "Tricep Pushdown" (arms) and
"Cable Row" (back) have carried the `cable` equipment tag since 0137 with no
video; "Cable Fly" (chest), "Cable Face Pull" (shoulders) and "Cable Crunch"
(core) are the same. No new rows this time — every name below was already a
seeded exercise, so this is only a demo_url update, the same shape 0142's
`EXISTING_DEMOS` used.
"""
from django.db import migrations

EXISTING_DEMOS = {
    "Tricep Pushdown": "/exercise-demos/tricep-pushdown.mp4",
    "Cable Row": "/exercise-demos/cable-row.mp4",
    "Cable Fly": "/exercise-demos/cable-fly.mp4",
    "Cable Face Pull": "/exercise-demos/cable-face-pull.mp4",
    "Cable Crunch": "/exercise-demos/cable-crunch.mp4",
}


def seed(apps, schema_editor):
    BodieZExercise = apps.get_model("economy", "BodieZExercise")
    for name, demo_url in EXISTING_DEMOS.items():
        BodieZExercise.objects.filter(name=name).update(demo_url=demo_url)


def unseed(apps, schema_editor):
    BodieZExercise = apps.get_model("economy", "BodieZExercise")
    BodieZExercise.objects.filter(name__in=EXISTING_DEMOS.keys()).update(demo_url="")


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0143_bodiez_day_tags_and_description"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
