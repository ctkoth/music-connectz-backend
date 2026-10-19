"""The everyday lifts the library was missing, found by auditing it against Jefit.

The library had 90 exercises and a member logging a normal gym week kept
reaching for one that was not there: the only upright row was the EZ-bar one,
so a barbell, dumbbell or cable upright row had to be made up as a custom
exercise, and so did a chin-up, a hammer curl, a hip thrust, a shrug, a
front squat. These are not obscure — each is in Jefit's own default library
under the same name or the obvious one, and each is a lift people actually
programme.

Deliberately NOT a copy of Jefit's 1,300. No barbell Romanian deadlift
either: 0178 made the library's one RDL the dumbbell lift (Corey's call), and
a second row would undo it — Stiff-Leg Deadlift is the barbell hinge here. Variants that differ only by grip
width or which bench angle (see BodieZExercise's docstring) stay out, and so
does anything whose equipment this library cannot name (sleds, battle ropes,
TRX) — a row tagged with the wrong equipment is the failure the equipment
filter exists to prevent.

Tags follow the rules 0177 and 0184 state: `needs_arms` / `needs_legs` mean
the limb moves the load or holds the body up, `one_*_ok` means a normal way
to do it with one, and where unsure the tag is the cautious one — a mistaken
"needs it" hides a lift, a mistaken "doesn't" offers one somebody cannot do.

Rows are matched by name and skipped when present, so re-running is harmless.
None has a demo clip yet.
"""
from django.db import migrations

# name, muscle_group, equipment, positions, needs_arms, needs_legs, one_arm_ok, one_leg_ok
NEW = [
    # Shoulders
    ("Barbell Upright Row", "shoulders", "barbell", "standing", True, False, False, False),
    ("Dumbbell Upright Row", "shoulders", "dumbbell", "standing,seated", True, False, True, False),
    ("Cable Upright Row", "shoulders", "cable", "standing", True, False, False, False),
    ("Arnold Press", "shoulders", "dumbbell", "standing,seated", True, False, True, False),
    ("Barbell Shrug", "shoulders", "barbell", "standing", True, False, False, False),
    ("Dumbbell Shrug", "shoulders", "dumbbell", "standing,seated", True, False, True, False),
    ("Dumbbell Rear Delt Fly", "shoulders", "dumbbell", "standing,seated", True, False, True, False),
    ("Reverse Pec Deck", "shoulders", "machine", "seated", True, False, True, False),
    ("Cable Lateral Raise", "shoulders", "cable", "standing,seated", True, False, True, False),
    ("Barbell Front Raise", "shoulders", "barbell", "standing,seated", True, False, False, False),
    ("Landmine Press", "shoulders", "barbell", "standing,kneeling", True, False, False, False),
    ("Band Pull-Apart", "shoulders", "band", "standing,seated", True, False, False, False),
    ("Band Lateral Raise", "shoulders", "band", "standing,seated", True, False, True, False),
    ("Pike Push-Up", "shoulders", "bodyweight", "floor", True, True, False, False),
    # Chest
    ("Incline Dumbbell Fly", "chest", "dumbbell", "seated", True, False, True, False),
    ("Cable Crossover", "chest", "cable", "standing", True, False, True, False),
    ("Low-to-High Cable Fly", "chest", "cable", "standing", True, False, True, False),
    ("Dumbbell Pullover", "chest", "dumbbell", "lying", True, False, False, False),
    ("Smith Machine Bench Press", "chest", "machine", "lying", True, False, False, False),
    ("Incline Push-Up", "chest", "bodyweight", "standing", True, True, False, False),
    ("Decline Push-Up", "chest", "bodyweight", "floor", True, True, False, False),
    # Back
    ("Chin-Up", "back", "bodyweight", "standing", True, False, False, False),
    ("T-Bar Row", "back", "barbell", "standing", True, True, False, False),
    ("Pendlay Row", "back", "barbell", "standing", True, True, False, False),
    ("Seated Machine Row", "back", "machine", "seated", True, False, True, False),
    ("Straight-Arm Pulldown", "back", "cable", "standing", True, False, True, False),
    ("Inverted Row", "back", "bodyweight", "lying", True, True, False, False),
    # Arms only cross the chest here, but no upper-body row is tagged arm-free
    # (0184's rule) — the cautious tag hides it rather than over-offering it.
    ("Back Extension", "back", "bodyweight", "lying", True, True, False, False),
    ("Good Morning", "back", "barbell", "standing", True, True, False, False),
    ("Rack Pull", "back", "barbell", "standing", True, True, False, False),
    ("Superman", "back", "bodyweight", "lying", True, True, False, False),
    # Biceps
    ("Hammer Curl", "biceps", "dumbbell", "standing,seated", True, False, True, False),
    ("Preacher Curl", "biceps", "ez_bar", "seated", True, False, False, False),
    ("Dumbbell Preacher Curl", "biceps", "dumbbell", "seated", True, False, True, False),
    ("Concentration Curl", "biceps", "dumbbell", "seated", True, False, True, False),
    ("Incline Dumbbell Curl", "biceps", "dumbbell", "seated", True, False, True, False),
    ("Cable Curl", "biceps", "cable", "standing,seated", True, False, True, False),
    ("Band Curl", "biceps", "band", "standing,seated", True, False, True, False),
    ("Machine Bicep Curl", "biceps", "machine", "seated", True, False, True, False),
    # Triceps
    ("Close-Grip Bench Press", "triceps", "barbell", "lying", True, False, False, False),
    ("Overhead Cable Tricep Extension", "triceps", "cable", "standing,seated", True, False, True, False),
    ("Rope Pushdown", "triceps", "cable", "standing,seated", True, False, False, False),
    ("Dumbbell Skullcrusher", "triceps", "dumbbell", "lying", True, False, True, False),
    ("Bench Dip", "triceps", "bodyweight", "floor", True, True, False, False),
    ("Diamond Push-Up", "triceps", "bodyweight", "floor", True, True, False, False),
    ("Machine Tricep Extension", "triceps", "machine", "seated", True, False, True, False),
    ("Band Tricep Pushdown", "triceps", "band", "standing,seated", True, False, True, False),
    # Forearms
    ("Wrist Curl", "forearms", "dumbbell", "seated", True, False, True, False),
    ("Reverse Wrist Curl", "forearms", "dumbbell", "seated", True, False, True, False),
    ("Barbell Wrist Curl", "forearms", "barbell", "seated", True, False, False, False),
    ("Farmer's Walk", "forearms", "dumbbell", "standing", True, True, True, False),
    ("Dead Hang", "forearms", "bodyweight", "standing", True, False, False, False),
    # Abs
    ("Ab Wheel Rollout", "abs", "bodyweight", "kneeling", True, True, False, False),
    ("Side Plank", "abs", "bodyweight", "floor", True, True, False, False),
    ("Mountain Climber", "abs", "bodyweight", "floor", True, True, False, False),
    ("Sit-Up", "abs", "bodyweight", "lying", False, True, False, False),
    ("Oblique Crunch", "abs", "bodyweight", "lying", False, False, False, False),
    ("Dead Bug", "abs", "bodyweight", "lying", True, True, False, False),
    ("Bird Dog", "abs", "bodyweight", "kneeling", True, True, False, False),
    ("Hollow Body Hold", "abs", "bodyweight", "lying", True, True, False, False),
    ("V-Up", "abs", "bodyweight", "lying", True, True, False, False),
    ("Flutter Kick", "abs", "bodyweight", "lying", False, True, False, False),
    ("Pallof Press", "abs", "cable", "standing,seated,kneeling", True, False, False, False),
    ("Captain's Chair Leg Raise", "abs", "machine", "standing", True, True, False, False),
    # Upper legs
    ("Front Squat", "upper_legs", "barbell", "standing", True, True, False, False),
    ("Goblet Squat", "upper_legs", "dumbbell", "standing", True, True, False, False),
    ("Bulgarian Split Squat", "upper_legs", "dumbbell", "standing", True, True, False, True),
    ("Stiff-Leg Deadlift", "upper_legs", "barbell", "standing", True, True, False, False),
    ("Sumo Deadlift", "upper_legs", "barbell", "standing", True, True, False, False),
    ("Walking Lunge", "upper_legs", "dumbbell", "standing", True, True, True, False),
    ("Dumbbell Step-Up", "upper_legs", "dumbbell", "standing", True, True, True, True),
    ("Smith Machine Squat", "upper_legs", "machine", "standing", True, True, False, False),
    ("Nordic Hamstring Curl", "upper_legs", "bodyweight", "kneeling", False, True, False, False),
    ("Pistol Squat", "upper_legs", "bodyweight", "standing", False, True, False, True),
    ("Jump Squat", "upper_legs", "bodyweight", "standing", False, True, False, False),
    ("Bodyweight Squat", "upper_legs", "bodyweight", "standing", False, True, False, False),
    # Glutes
    ("Barbell Hip Thrust", "glutes", "barbell", "floor", False, True, False, False),
    ("Dumbbell Hip Thrust", "glutes", "dumbbell", "floor", False, True, False, False),
    ("Cable Pull-Through", "glutes", "cable", "standing", True, True, False, False),
    ("Cable Glute Kickback", "glutes", "cable", "standing", False, True, False, True),
    ("Donkey Kick", "glutes", "bodyweight", "kneeling", True, True, False, True),
    ("Fire Hydrant", "glutes", "bodyweight", "kneeling", True, True, False, True),
    ("Banded Lateral Walk", "glutes", "band", "standing", False, True, False, False),
    ("Sumo Squat", "glutes", "dumbbell", "standing", True, True, False, False),
    # Lower legs
    ("Bodyweight Calf Raise", "lower_legs", "bodyweight", "standing", False, True, False, True),
    ("Dumbbell Calf Raise", "lower_legs", "dumbbell", "standing", True, True, True, True),
    ("Leg Press Calf Raise", "lower_legs", "machine", "seated", False, True, False, True),
    # Cardio
    ("Stationary Bike", "cardio", "machine", "seated", False, True, False, False),
    ("Elliptical", "cardio", "machine", "standing", False, True, False, False),
    ("Stair Climber", "cardio", "machine", "standing", False, True, False, False),
    ("Jump Rope", "cardio", "bodyweight", "standing", True, True, False, False),
    ("Jumping Jack", "cardio", "bodyweight", "standing", True, True, False, False),
    # Full body
    ("Barbell Thruster", "full_body", "barbell", "standing", True, True, False, False),
    ("Dumbbell Thruster", "full_body", "dumbbell", "standing", True, True, False, False),
    ("Power Clean", "full_body", "barbell", "standing", True, True, False, False),
    ("Kettlebell Snatch", "full_body", "kettlebell", "standing", True, True, True, False),
]


def forwards(apps, schema_editor):
    Ex = apps.get_model("economy", "BodieZExercise")
    for name, group, equip, pos, arms, legs, one_arm, one_leg in NEW:
        if Ex.objects.filter(name=name, created_by__isnull=True).exists():
            continue
        Ex.objects.create(name=name, muscle_group=group, equipment=equip, positions=pos,
                          needs_arms=arms, needs_legs=legs, one_arm_ok=one_arm, one_leg_ok=one_leg)


def backwards(apps, schema_editor):
    # Only rows nobody has logged against: deleting an exercise cascades to
    # every set a member recorded with it.
    Ex = apps.get_model("economy", "BodieZExercise")
    Set = apps.get_model("economy", "BodieZSet")
    used = set(Set.objects.values_list("exercise_id", flat=True))
    Ex.objects.filter(name__in=[n[0] for n in NEW], created_by__isnull=True).exclude(id__in=used).delete()


class Migration(migrations.Migration):
    dependencies = [("economy", "0189_open_pinned_substances")]
    operations = [migrations.RunPython(forwards, backwards)]
