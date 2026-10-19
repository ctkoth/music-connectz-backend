"""Per-set one-arm / one-leg marker, and the one-leg answer for the access filter.

Why the marker: members do two-arm and two-leg exercises one-sided, and a
one-arm set at 40 is not a 40 set. Without it a one-arm row beside a two-arm
row reads as a collapse (or a record), and the coach rates a lift that did
not move. Sets keep `one_sided=""` unless somebody says otherwise, so nothing
already logged changes.

One-leg tags, by name, judgement calls stated: only movements that are a
normal single-leg version (leg machines worked one side at a time, single-leg
bridge, side-lying raise, clamshell, tibialis raise, step-up where the working
leg is the good one). Two-footed or balance-dependent movements (squat, lunge,
deadlift, standing calf raise, bike) stay False.
"""
from django.db import migrations, models

ONE_LEG = [
    "Seated Leg Extension", "Seated Leg Curl", "Lying Leg Curl", "Leg Press",
    "Single-Leg Press", "Seated Calf Raise", "Seated Hip Abduction",
    "Seated Hip Adduction", "Single-Leg Glute Bridge", "Side-Lying Leg Raise",
    "Clamshell", "Seated Tibialis Raise", "Bodyweight Step-Up",
]


def tag(apps, schema_editor):
    Ex = apps.get_model("economy", "BodieZExercise")
    Ex.objects.filter(name__in=ONE_LEG, needs_legs=True).update(one_leg_ok=True)


class Migration(migrations.Migration):
    dependencies = [("economy", "0185_bodiez_one_arm")]
    operations = [
        migrations.AddField("bodiezexercise", "one_leg_ok", models.BooleanField(default=False)),
        migrations.AddField("bodiezaccess", "one_leg_only", models.BooleanField(default=False)),
        migrations.AddField("bodiezset", "one_sided", models.CharField(blank=True, default="", max_length=3)),
        migrations.RunPython(tag, migrations.RunPython.noop),
    ]
