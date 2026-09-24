"""New equipment needs exercises that use it, or the filter this adds is
three new dropdown entries pointing at an empty room — the exact
"route is not a door" failure this codebase already has a name for
(trialdoorz.py's docstring, about the five instrument coaches nothing
linked to). Ez bar, kettlebell and cable each get at least two real
exercises; the rest fill out bench-angle variants that were missing
outright (a chest day had flat and incline dumbbell work and no barbell
incline or decline at all).

Rep/set PRESCRIPTIONS for these — and every other exercise — are not
stored here. They live in `bodiez.py`'s `GOALS` table, keyed by
muscle-gain/toning/fat-loss, cited to ACSM's resistance-training position
stand and Schoenfeld (2010). An exercise is WHAT you do; a goal decides
HOW MUCH — the same split BodieZRoutine.exercises already draws between
`exercise_id` (what) and `sets`/`reps` (how much), just moved one level up
to "which how-much scheme applies to every exercise in this routine."

Two existing rows were mislabeled and are corrected here rather than left
wrong now that the equipment they actually use exists:
- "Tricep Pushdown" was tagged `machine`; it's done on a cable stack.
- "Kettlebell Swing" was tagged `dumbbell`, because `kettlebell` didn't
  exist as a choice yet.
Both are UPDATEs by name, not deletes — a routine or session already
pointing at either exercise_id keeps working; only its equipment tag
changes, so a member filtering by "what I own" sees it where it belongs.
"""
from django.db import migrations

NEW_EXERCISES = [
    # EZ bar — the curved bar that takes wrist strain off arm and (some)
    # back work; without it "ez_bar" was a filter option with nothing to
    # show.
    ("EZ Bar Curl", "arms", "ez_bar"),
    ("EZ Bar Skullcrusher", "arms", "ez_bar"),
    ("EZ Bar Upright Row", "shoulders", "ez_bar"),

    # Kettlebell — beyond the one full-body swing already in the library.
    ("Kettlebell Goblet Squat", "legs", "kettlebell"),
    ("Kettlebell Clean and Press", "full_body", "kettlebell"),
    ("Kettlebell Row", "back", "kettlebell"),
    ("Turkish Get-Up", "full_body", "kettlebell"),

    # Cable / pulley — a real muscle-group each, not just relabeling what
    # existed. Face Pull already existed tagged "band"; band and cable both
    # do the movement, so it keeps its band tag and this adds the cable
    # equivalent as its own row rather than silently reassigning a row a
    # routine may already reference.
    ("Cable Row", "back", "cable"),
    ("Lat Pulldown (Cable)", "back", "cable"),
    ("Cable Fly", "chest", "cable"),
    ("Cable Face Pull", "shoulders", "cable"),
    ("Cable Woodchopper", "core", "cable"),

    # Bench-angle variants — a real gap, not new equipment. Flat barbell
    # press and incline/flat dumbbell press already existed; incline and
    # decline barbell, and incline dumbbell's decline counterpart, did not.
    ("Incline Barbell Bench Press", "chest", "barbell"),
    ("Decline Barbell Bench Press", "chest", "barbell"),
    ("Incline Dumbbell Press", "chest", "dumbbell"),
    ("Decline Dumbbell Press", "chest", "dumbbell"),
]

RELABEL = [
    ("Tricep Pushdown", "cable"),
    ("Kettlebell Swing", "kettlebell"),
]


def seed(apps, schema_editor):
    BodieZExercise = apps.get_model("economy", "BodieZExercise")
    for name, muscle_group, equipment in NEW_EXERCISES:
        BodieZExercise.objects.get_or_create(
            name=name, defaults={"muscle_group": muscle_group, "equipment": equipment})
    for name, equipment in RELABEL:
        BodieZExercise.objects.filter(name=name).update(equipment=equipment)


def unseed(apps, schema_editor):
    BodieZExercise = apps.get_model("economy", "BodieZExercise")
    BodieZExercise.objects.filter(name__in=[n for n, _, _ in NEW_EXERCISES]).delete()
    # The relabel is left in place on reverse — putting "Tricep Pushdown"
    # back on "machine" would misdescribe a real row for no reason once the
    # equipment value itself still exists (this migration doesn't remove
    # ez_bar/kettlebell/cable; the schema migration ahead of it does, and
    # that one's own reverse handles the column).


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0136_bodiez_equipment_expansion"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
