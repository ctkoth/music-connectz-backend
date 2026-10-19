"""One-arm answer for the access filter, and which exercises honour it.

Tagged by name, judgement calls stated so they can be reversed:

- Dumbbell and kettlebell movements that are normally done one arm at a time
  (row, curl, press, raise, kickback, one-arm swing, get-up) count, and so do
  the dumbbell squat / lunge / deadlift family, which a one-armed lifter
  carries in the one hand.
- Cable and band movements count when the single-handle version is a normal
  way to do them (fly, row, pushdown, pulldown, band press/row).
- Independent-handle machines count (chest press, pec deck, shoulder press,
  pulldown).
- Barbell, EZ-bar, bodyweight-on-the-arms (push-up, pull-up, dip) and
  two-handed holds (goblet squat, woodchopper, rope face pull) do NOT: they
  need both hands. Anything not listed stays False.
"""
from django.db import migrations, models

ONE_ARM = [
    "Bicep Curl", "Seated Hammer Curl", "Zottman Curl", "Dumbbell Shoulder Press",
    "Lateral Raise", "Dumbbell Front Raise", "Dumbbell Tricep Extension", "Tricep Kickback",
    "Dumbbell Row", "Chest-Supported Dumbbell Row", "Dumbbell Bench Press",
    "Incline Dumbbell Press", "Decline Dumbbell Press", "Dumbbell Fly",
    "Dumbbell Squat", "Lunge", "Dumbbell Romanian Deadlift", "Dumbbell Deadlift",
    "Kettlebell Row", "Kettlebell Clean and Press", "Kettlebell Swing", "Turkish Get-Up",
    "Cable Fly", "Cable Row", "Tricep Pushdown", "Lat Pulldown (Cable)",
    "Machine Bench Press", "Pec Deck", "Seated Machine Shoulder Press", "Lat Pulldown",
    "Seated Band Chest Press", "Seated Band Row",
]


def tag(apps, schema_editor):
    Ex = apps.get_model("economy", "BodieZExercise")
    Ex.objects.filter(name__in=ONE_ARM, needs_arms=True).update(one_arm_ok=True)


class Migration(migrations.Migration):
    dependencies = [("economy", "0184_bodiez_more_accessible_exercises")]
    operations = [
        migrations.AddField("bodiezexercise", "one_arm_ok", models.BooleanField(default=False)),
        migrations.AddField("bodiezaccess", "one_arm_only", models.BooleanField(default=False)),
        migrations.RunPython(tag, migrations.RunPython.noop),
    ]
