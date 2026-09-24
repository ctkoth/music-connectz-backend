"""Swap the library's 8 muscle groups for Jefit's 11, plus one Jefit doesn't
have.

Corey asked for Jefit's own breakdown: Abs, Back, Biceps, Cardio, Chest,
Forearms, Glutes, Shoulders, Triceps, Upper Legs, Lower Legs. "Arms" and
"Legs" were too coarse for the exact thing this whole feature exists for — a
member filtering to train biceps and triceps on separate days needs the
library to KNOW they're separate, not fold both into one "Arms" bucket that
rides on both days regardless (see the SplitBuilder docstring this migration
also corrects).

Full Body is the one group in this library that ISN'T in Jefit's eleven, and
it stays: Burpee, Clean and Press, Kettlebell Clean and Press, Kettlebell
Swing and Turkish Get-Up genuinely aren't one-muscle movements, and forcing
each into a single dominant muscle (Clean and Press -> Shoulders, say) would
describe less than the exercise actually does. Corey's call, kept rather than
matching Jefit exactly at the cost of losing that fact. Every OTHER row is
reclassified onto Jefit's own eleven, never left on a value the choices tuple
no longer declares — an exercise whose muscle_group isn't in MUSCLE_CHOICES
would 500 the second anything calls full_clean() on it, and would silently
vanish from every muscle_group=<x> filter in the meantime.

REASSIGN maps by NAME rather than by the old value, because "arms" splits
three ways depending on which specific exercise it was — a blanket
old-value-to-new-value swap can't do that; a per-row lookup can.
"""
from django.db import migrations, models

REASSIGN = {
    # arms -> biceps / triceps / forearms, one at a time, never as a group
    "Barbell Curl": "biceps",
    "Bicep Curl": "biceps",
    "EZ Bar Curl": "biceps",
    "Barbell Tricep Extension": "triceps",
    "Dumbbell Tricep Extension": "triceps",
    "EZ Bar Skullcrusher": "triceps",
    "Tricep Kickback": "triceps",
    "Tricep Pushdown": "triceps",
    "Dip": "triceps",
    # Reverse Barbell Curl and Zottman Curl both load the forearm on the
    # lowering phase, which is the whole reason either exists as a distinct
    # exercise from a plain curl — that's the muscle worth filing them under.
    "Reverse Barbell Curl": "forearms",
    "Zottman Curl": "forearms",
    # legs -> upper_legs / lower_legs
    "Calf Raise": "lower_legs",
    "Dumbbell Squat": "upper_legs",
    "Kettlebell Goblet Squat": "upper_legs",
    "Leg Press": "upper_legs",
    "Lunge": "upper_legs",
    "Romanian Deadlift": "upper_legs",
    "Squat": "upper_legs",
    # core -> abs (Jefit's name for the same thing)
    "Cable Crunch": "abs",
    "Cable Woodchopper": "abs",
    "Hanging Leg Raise": "abs",
    "Plank": "abs",
    "Russian Twist": "abs",
    # chest, back, shoulders, cardio, full_body: unchanged, not listed here.
}


def reassign(apps, schema_editor):
    BodieZExercise = apps.get_model("economy", "BodieZExercise")
    for name, muscle_group in REASSIGN.items():
        BodieZExercise.objects.filter(name=name).update(muscle_group=muscle_group)


def unreassign(apps, schema_editor):
    BodieZExercise = apps.get_model("economy", "BodieZExercise")
    arms = ["Barbell Curl", "Bicep Curl", "EZ Bar Curl", "Barbell Tricep Extension",
            "Dumbbell Tricep Extension", "EZ Bar Skullcrusher", "Tricep Kickback",
            "Tricep Pushdown", "Dip", "Reverse Barbell Curl", "Zottman Curl"]
    legs = ["Calf Raise", "Dumbbell Squat", "Kettlebell Goblet Squat", "Leg Press",
            "Lunge", "Romanian Deadlift", "Squat"]
    core = ["Cable Crunch", "Cable Woodchopper", "Hanging Leg Raise", "Plank", "Russian Twist"]
    BodieZExercise.objects.filter(name__in=arms).update(muscle_group="arms")
    BodieZExercise.objects.filter(name__in=legs).update(muscle_group="legs")
    BodieZExercise.objects.filter(name__in=core).update(muscle_group="core")


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0144_bodiez_cable_demo_videos"),
    ]

    operations = [
        migrations.AlterField(
            model_name="bodiezexercise",
            name="muscle_group",
            field=models.CharField(
                choices=[
                    ("abs", "Abs"),
                    ("back", "Back"),
                    ("biceps", "Biceps"),
                    ("cardio", "Cardio"),
                    ("chest", "Chest"),
                    ("forearms", "Forearms"),
                    ("glutes", "Glutes"),
                    ("shoulders", "Shoulders"),
                    ("triceps", "Triceps"),
                    ("upper_legs", "Upper Legs"),
                    ("lower_legs", "Lower Legs"),
                    ("full_body", "Full Body"),
                ],
                max_length=12,
            ),
        ),
        migrations.RunPython(reassign, unreassign),
    ]
