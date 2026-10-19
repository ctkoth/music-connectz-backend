"""Real exercise demo videos — the first ones this app has had rights to.

`BodieZExercise.demo_url` shipped in 0136 deliberately blank: no media
pipeline existed for exercise photography and no third party's GIFs were
ours to host. Corey supplied five self-recorded clips with the rights to
use them, so this is the first time that field gets to do its job.

Four of the five don't match any seeded exercise — "Tricep Kickback",
"Dumbbell Tricep Extension" and "Barbell Tricep Extension" are all real,
distinct movements the library never had a row for (the EZ Bar variant
already existed as "EZ Bar Skullcrusher"), and "Barbell Curl" is a
different exercise from the "Bicep Curl" row, which is tagged dumbbell —
adding a barbell row rather than relabeling the dumbbell one keeps both
reachable, the same reasoning 0137 already applied to Tricep Pushdown and
Kettlebell Swing.

The files themselves live in the FRONTEND repo's `public/exercise-demos/`
— static assets served by whichever host serves the app (Vercel/Cloudflare
Pages), not by this API. `demo_url` stores a root-relative path
(`/exercise-demos/<file>.mp4`) rather than a full URL for the same reason
`_upload_dict` never freezes a full URL into a post: it resolves against
whatever origin is actually serving the page, so it survives a host
migration for free, and it is short enough that `max_length=300` was never
a real constraint.
"""
from django.db import migrations

NEW_EXERCISES = [
    ("Tricep Kickback", "arms", "dumbbell", "/exercise-demos/dumbbell-tricep-kickback.mp4"),
    ("Dumbbell Tricep Extension", "arms", "dumbbell", "/exercise-demos/dumbbell-tricep-extension.mp4"),
    ("Barbell Tricep Extension", "arms", "barbell", "/exercise-demos/barbell-tricep-extension.mp4"),
    ("Barbell Curl", "arms", "barbell", "/exercise-demos/barbell-curl.mp4"),
]

# name -> demo_url, for a row 0137 or the original seed already created.
EXISTING_DEMOS = {
    "EZ Bar Skullcrusher": "/exercise-demos/ez-bar-skullcrusher.mp4",
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
        ("economy", "0137_bodiez_new_equipment_exercises"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
