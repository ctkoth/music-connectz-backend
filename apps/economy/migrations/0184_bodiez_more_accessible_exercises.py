"""More of the library for a member who cannot use their arms.

The audit behind this: of 71 exercises, 10 needed no arms and ONE needed
neither arms nor legs. Every upper-body group (chest, back, shoulders, biceps,
triceps, forearms) had nothing at all, and that cannot honestly be fixed with
more rows — an exercise that trains the arms needs them, and tagging one as
arm-free to pad a count would hand somebody a lift they cannot do. So this adds
what genuinely needs no arms, which is legs, glutes, calves, trunk and cardio.

`needs_arms` means arms move the load or hold the body up (the rule 0177
states), so a machine with handles that only steady you is arm-free — the same
call Leg Press already makes — and a movement whose lever is the legs is
tagged `needs_legs` even when it is filed under abs. Where unsure the tag is
the cautious one: a mistaken "needs it" hides a lift, a mistaken "doesn't"
offers one somebody cannot do.

Rows are matched by name and skipped when present, so re-running is harmless.
None has a demo clip yet; the video audit lists them as owed.
"""
from django.db import migrations

# name, muscle_group, equipment, positions, needs_arms, needs_legs
NEW = [
    ("Hack Squat", "upper_legs", "machine", "standing", False, True),
    ("Single-Leg Press", "upper_legs", "machine", "seated", False, True),
    ("Seated Hip Adduction", "upper_legs", "machine", "seated", False, True),
    ("Bodyweight Box Squat", "upper_legs", "bodyweight", "standing", False, True),
    ("Wall Sit", "upper_legs", "bodyweight", "standing", False, True),
    ("Bodyweight Step-Up", "upper_legs", "bodyweight", "standing", False, True),
    ("Bodyweight Reverse Lunge", "upper_legs", "bodyweight", "standing", False, True),
    ("Single-Leg Glute Bridge", "glutes", "bodyweight", "lying", False, True),
    ("Clamshell", "glutes", "bodyweight", "lying", False, True),
    ("Side-Lying Leg Raise", "glutes", "bodyweight", "lying", False, True),
    ("Seated Tibialis Raise", "lower_legs", "bodyweight", "seated", False, True),
    ("Reverse Crunch", "abs", "bodyweight", "lying", False, True),
    ("Lying Leg Raise", "abs", "bodyweight", "lying", False, True),
    ("Bicycle Crunch", "abs", "bodyweight", "lying", False, True),
    # Trunk only: neither arms nor legs do the work.
    ("Seated Trunk Rotation", "abs", "bodyweight", "seated", False, False),
    ("Lying Pelvic Tilt", "abs", "bodyweight", "lying", False, False),
    ("Abdominal Brace Hold", "abs", "bodyweight", "seated,lying", False, False),
    ("Recumbent Bike", "cardio", "machine", "seated", False, True),
    ("Walking", "cardio", "bodyweight", "standing", False, True),
]


def forwards(apps, schema_editor):
    Ex = apps.get_model("economy", "BodieZExercise")
    for name, group, equip, pos, arms, legs in NEW:
        Ex.objects.get_or_create(name=name, defaults=dict(
            muscle_group=group, equipment=equip, positions=pos, needs_arms=arms, needs_legs=legs))


def backwards(apps, schema_editor):
    # Only rows nobody has logged against: deleting an exercise cascades to
    # every set a member recorded with it.
    Ex = apps.get_model("economy", "BodieZExercise")
    Set = apps.get_model("economy", "BodieZSet")
    used = set(Set.objects.values_list("exercise_id", flat=True))
    Ex.objects.filter(name__in=[n[0] for n in NEW]).exclude(id__in=used).delete()


class Migration(migrations.Migration):
    dependencies = [("economy", "0183_bodiez_session_backfilled")]
    operations = [migrations.RunPython(forwards, backwards)]
