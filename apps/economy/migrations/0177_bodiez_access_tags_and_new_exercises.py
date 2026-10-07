"""Tag every library exercise with where it can be done and which limbs it
needs, add the seated/lying movements the library was missing, and wire the
seven demo clips that were already uploaded but pointed at by nothing.

Why the library needed new rows and not just tags: 56 exercises, and by
this migration's own tagging only a handful can be done by somebody who
cannot stand. A filter over that would answer "here are four things" — an
honest filter over a library with a hole in it. The Glutes group had NO
exercise at all. So the additions below are the seated/lying set a
wheelchair user, or anybody with a leg or arm out of action, would
otherwise never be offered. None of them has a demo clip yet — the audit
that goes with this migration lists them as needed.

Tags are by NAME (like 0145) because the choice depends on the specific
movement, not on its muscle group or equipment. Judgement calls, stated so
they can be reversed by somebody who disagrees:

- A seated variation counts when it is a normal, widely-taught way to do the
  movement (seated barbell curl, seated overhead press). It does not count
  when it would be a different exercise (a squat is not a seated exercise).
- `needs_legs` means legs move the load or hold the body up. Feet planted on
  the floor for a bench press is not "needing legs".
- Anything hung from, supported on, or performed on the floor is NOT listed
  as seated or lying, even though a member might get there with help.
"""
from django.db import migrations

# name -> (positions, needs_arms, needs_legs)
TAGS = {
    # abs
    "Cable Crunch": ("kneeling", True, True),
    "Cable Woodchopper": ("standing,seated", True, False),
    "Hanging Leg Raise": ("standing", True, True),
    "Plank": ("floor", True, True),
    "Russian Twist": ("seated", True, False),
    # back
    "Barbell Row": ("standing", True, True),
    "Cable Row": ("seated", True, False),
    "Deadlift": ("standing", True, True),
    "Dumbbell Deadlift": ("standing", True, True),
    "Dumbbell Row": ("standing", True, True),
    "Kettlebell Row": ("standing", True, True),
    "Lat Pulldown": ("seated", True, False),
    "Lat Pulldown (Cable)": ("seated", True, False),
    "Pull-Up": ("standing", True, False),
    # biceps
    "Barbell Curl": ("standing,seated", True, False),
    "Bicep Curl": ("standing,seated", True, False),
    "EZ Bar Curl": ("standing,seated", True, False),
    # cardio
    "Rowing Machine": ("seated", True, True),
    "Running": ("standing", False, True),
    # chest
    "Bench Press": ("lying", True, False),
    "Cable Fly": ("standing,seated", True, False),
    "Decline Barbell Bench Press": ("lying", True, False),
    "Decline Dumbbell Press": ("lying", True, False),
    "Dumbbell Bench Press": ("lying", True, False),
    "Dumbbell Fly": ("lying", True, False),
    "Incline Barbell Bench Press": ("seated", True, False),
    "Incline Dumbbell Press": ("seated", True, False),
    "Machine Bench Press": ("seated", True, False),
    "Push-Up": ("floor", True, True),
    # forearms
    "Reverse Barbell Curl": ("standing,seated", True, False),
    "Zottman Curl": ("standing,seated", True, False),
    # full body
    "Burpee": ("standing", True, True),
    "Clean and Press": ("standing", True, True),
    "Kettlebell Clean and Press": ("standing", True, True),
    "Kettlebell Swing": ("standing", True, True),
    "Turkish Get-Up": ("floor", True, True),
    # lower legs
    "Calf Raise": ("standing", False, True),
    # shoulders
    "Cable Face Pull": ("standing,seated", True, False),
    "Dumbbell Front Raise": ("standing,seated", True, False),
    "Dumbbell Shoulder Press": ("standing,seated", True, False),
    "EZ Bar Upright Row": ("standing,seated", True, False),
    "Face Pull": ("standing,seated", True, False),
    "Lateral Raise": ("standing,seated", True, False),
    "Overhead Press": ("standing,seated", True, False),
    # triceps
    "Barbell Tricep Extension": ("seated,lying", True, False),
    "Dip": ("standing", True, False),
    "Dumbbell Tricep Extension": ("standing,seated", True, False),
    "EZ Bar Skullcrusher": ("lying", True, False),
    "Tricep Kickback": ("standing", True, True),
    "Tricep Pushdown": ("standing,seated", True, False),
    # upper legs
    "Dumbbell Squat": ("standing", True, True),
    "Kettlebell Goblet Squat": ("standing", True, True),
    "Leg Press": ("seated", False, True),
    "Lunge": ("standing", True, True),
    "Romanian Deadlift": ("standing", True, True),
    "Squat": ("standing", True, True),
}

# (name, muscle_group, equipment, positions, needs_arms, needs_legs, demo_url)
NEW = [
    ("Seated Leg Extension", "upper_legs", "machine", "seated", False, True, ""),
    ("Seated Leg Curl", "upper_legs", "machine", "seated", False, True, ""),
    ("Lying Leg Curl", "upper_legs", "machine", "lying", False, True, ""),
    ("Seated Calf Raise", "lower_legs", "machine", "seated", False, True, ""),
    ("Glute Bridge", "glutes", "bodyweight", "lying", False, True, ""),
    ("Seated Hip Abduction", "glutes", "machine", "seated", False, True, ""),
    ("Crunch", "abs", "bodyweight", "lying", False, False, ""),
    ("Seated Ab Crunch", "abs", "machine", "seated", True, False, ""),
    ("Pec Deck", "chest", "machine", "seated", True, False, ""),
    ("Seated Band Chest Press", "chest", "band", "seated", True, False, ""),
    ("Seated Machine Shoulder Press", "shoulders", "machine", "seated", True, False, ""),
    ("Chest-Supported Dumbbell Row", "back", "dumbbell", "lying", True, False, ""),
    ("Seated Band Row", "back", "band", "seated", True, False, ""),
    ("Seated Hammer Curl", "biceps", "dumbbell", "seated", True, False, ""),
    ("Seated Arm Crank", "cardio", "machine", "seated", True, False, ""),
    # Not seated or lying, but its clip was uploaded with no row to belong to.
    ("Dumbbell Romanian Deadlift", "upper_legs", "dumbbell", "standing", True, True,
     "/exercise-demos/Dumbbell%20Romanian%20Deadlift.mp4"),
]

# Clips already in ctkoth/mcz-media with no demo_url pointing at them. The
# filenames carry spaces and parentheses (they were uploaded as exported), so
# the stored path is percent-encoded rather than renamed here — renaming a
# file in another repo is not this migration's call.
WIRE = {
    "Push-Up": "/exercise-demos/Push-Up.mp4",
    "Dip": "/exercise-demos/dip.mp4",
    "EZ Bar Upright Row": "/exercise-demos/EZ%20Bar%20Upright%20Row.mp4",
    "Kettlebell Row": "/exercise-demos/Kettlebell%20Row.mp4",
    "Overhead Press": "/exercise-demos/Overhead%20Press%20(barbell).mp4",
    "Lat Pulldown": "/exercise-demos/Pulldown%20(machine).mp4",
}


def forwards(apps, schema_editor):
    Ex = apps.get_model("economy", "BodieZExercise")
    for name, (positions, arms, legs) in TAGS.items():
        Ex.objects.filter(name=name).update(positions=positions, needs_arms=arms, needs_legs=legs)
    for name, muscle, equip, positions, arms, legs, url in NEW:
        Ex.objects.get_or_create(name=name, defaults=dict(
            muscle_group=muscle, equipment=equip, positions=positions,
            needs_arms=arms, needs_legs=legs, demo_url=url))
    for name, url in WIRE.items():
        # Only fill a blank — a clip somebody already pointed at stays theirs.
        Ex.objects.filter(name=name, demo_url="").update(demo_url=url)


def backwards(apps, schema_editor):
    Ex = apps.get_model("economy", "BodieZExercise")
    Ex.objects.filter(name__in=[n[0] for n in NEW]).delete()
    Ex.objects.filter(demo_url__in=list(WIRE.values())).update(demo_url="")


class Migration(migrations.Migration):
    dependencies = [("economy", "0176_bodiez_access")]
    operations = [migrations.RunPython(forwards, backwards)]
