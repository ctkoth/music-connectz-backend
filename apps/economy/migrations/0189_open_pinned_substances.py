"""Open the substance declarations that migration 0188 pinned to private.

Corey's call: the members 0188 protected are opened to members like everyone
else. What makes this safe to do unattended is that a pin can be told apart from
a CHOICE, and only pins are opened:

* A pin is `{"substances": ["private"]}` written by 0188 with
  `save(update_fields=["visibility"])`, which does not touch `updated_at`.
* The same value is also what a member gets by choosing Private in VisibilitieZ
  after the default moved — but that write goes through the profile PATCH, which
  always saves `updated_at`. So a profile whose `updated_at` is NOT later than
  the moment 0188 was applied has not been saved by anybody since the pin: its
  ["private"] can only be a pin.
* Anything saved since (a bio edit, a location change, an explicit choice) is
  ambiguous and is LEFT private. Opening it would risk overriding a member's own
  decision, which is the one error that cannot be taken back.

Each opened member is told, in-app, in the same run: their declaration was
private under the label they saw, and it is not any more. Opening is done by
removing the override, so they simply follow the default — and can narrow it
again from VisibilitieZ, which works now (`merge_visibility`).

The rows are updated with `.update()` so `updated_at` is not bumped, which keeps
the cutoff meaningful and the run idempotent: a second run finds no override.

One-way: a reverse could not tell the rows it opened from rows that were never
pinned, and re-hiding people is not something a migration should guess at.
"""
from django.db import migrations

PIN_MIGRATION = "0188_pin_existing_substances_private"

TOLD = ("SubstanceZ is now open to members. What you declared there was private when you "
        "saved it; it is visible to signed-in adults now. Change who sees it any time: "
        "ProfileZ > Who can see what.")


def open_pinned(Profile, Notification, applied_at):
    """Open every provably-untouched pin; return (opened, left_private)."""
    if applied_at is None:
        return 0, 0      # cannot prove anything, so open nothing
    opened = left = 0
    for p in Profile.objects.exclude(visibility={}).iterator():
        vis = p.visibility if isinstance(p.visibility, dict) else {}
        raw = vis.get("substances")
        if raw not in (["private"], "private"):
            continue
        if p.updated_at is not None and p.updated_at > applied_at:
            left += 1    # touched since the pin: could be the member's own choice
            continue
        rest = {k: v for k, v in vis.items() if k != "substances"}
        Profile.objects.filter(pk=p.pk).update(visibility=rest)
        Notification.objects.create(user_id=p.user_id, kind="system", text=TOLD)
        opened += 1
    return opened, left


def forwards(apps, schema_editor):
    from django.db.migrations.recorder import MigrationRecorder
    row = (MigrationRecorder(schema_editor.connection).migration_qs
           .filter(app="economy", name=PIN_MIGRATION).first())
    open_pinned(apps.get_model("economy", "Profile"), apps.get_model("economy", "Notification"),
                row.applied if row else None)


class Migration(migrations.Migration):
    dependencies = [("economy", PIN_MIGRATION)]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
