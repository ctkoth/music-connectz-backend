"""Per-field visibility, and `name_public` folded into it.

`name_public` shipped one deploy earlier as the boolean version of this
question for one field. Keeping both would be two mechanisms answering "may
this person see this", which is the two-writers failure with somebody's legal
name behind it — so the data moves and the column goes in the same migration.

Forwards and backwards both carry the data, because a rollback that silently
re-hid every name somebody had chosen to publish is a rollback that loses a
member's decision.
"""
from django.db import migrations, models


def fold_name_public(apps, schema_editor):
    Profile = apps.get_model("economy", "Profile")
    for pk, on in Profile.objects.filter(name_public=True).values_list("pk", "name_public"):
        Profile.objects.filter(pk=pk).update(
            visibility={"first_name": "public", "last_name": "public"})


def unfold_name_public(apps, schema_editor):
    Profile = apps.get_model("economy", "Profile")
    for pk, vis in Profile.objects.exclude(visibility={}).values_list("pk", "visibility"):
        shown = isinstance(vis, dict) and vis.get("first_name") == "public"
        Profile.objects.filter(pk=pk).update(name_public=shown)


class Migration(migrations.Migration):

    dependencies = [("economy", "0120_profile_name_public")]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="visibility",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(fold_name_public, unfold_name_public),
        migrations.RemoveField(model_name="profile", name="name_public"),
    ]
