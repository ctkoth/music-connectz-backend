from django.db import migrations, models


def carry_over_single_switch(apps, schema_editor):
    """A member who had the single switch on keeps every coach on — the same thing it meant."""
    Profile = apps.get_model("economy", "Profile")
    all_coaches = ["singz", "rapz", "guitarz", "bassz", "keyz", "drumz", "violinz"]
    Profile.objects.filter(coach_counts_for_skillz=True).update(coach_factors=all_coaches)


class Migration(migrations.Migration):

    dependencies = [
        ("economy", "0235_challengez_filters"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="coach_factors",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(carry_over_single_switch, migrations.RunPython.noop),
    ]
