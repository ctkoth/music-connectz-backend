"""Open SubstanceZ to members by default WITHOUT opening anybody's existing
declaration.

`visibility.DEFAULTS["substances"]` moves from private to member. A profile's
`visibility` column holds only the fields a member changed, so an unset field
follows the default — for every row, retroactively. Flipping the default alone
would therefore make every substance declaration already on the platform
readable by every member (with its frequency) on the day this deploys, for
people who made it under a control that said Private.

So every profile that has ALREADY declared a substance, and has made no choice
about who sees it, is pinned to private here — an explicit override, the same
thing a member who chose private has. They are unaffected until they open it
themselves. Everybody who declares from now on gets the new default, and a
member who never declared has nothing to expose either way.

One-way on purpose: a reverse would have to guess which pins this wrote and
which a member chose, and un-pinning someone's private declaration is the one
direction that cannot be undone.
"""
from django.db import migrations


def _declared(value):
    """Anything the member put there: a dict of stances, or the older bare list."""
    return isinstance(value, (dict, list)) and bool(value)


def forwards(apps, schema_editor):
    Profile = apps.get_model("economy", "Profile")
    for p in Profile.objects.exclude(substances={}).iterator():
        if not _declared(p.substances):
            continue
        vis = p.visibility if isinstance(p.visibility, dict) else {}
        if "substances" in vis:
            continue  # they already chose; that choice stands
        p.visibility = {**vis, "substances": ["private"]}
        p.save(update_fields=["visibility"])


class Migration(migrations.Migration):
    dependencies = [("economy", "0187_bodiez_custom_exercises")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
