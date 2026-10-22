"""Run the trial-history backfill once, on deploy.

Render runs `migrate` and nothing else, so this is how members who claimed a take
before the fix get it into their history without anybody opening a shell. It calls
the same function as `manage.py backfill_trial_history`, which skips any take
already recorded, so it is safe alongside a manual run. Best-effort: a failure is
logged and the deploy goes on — a missing history row must never block a deploy.
Reverse is a no-op; the rows it wrote are ordinary history.
"""
import logging

from django.db import migrations


def forward(apps, schema_editor):
    try:
        from apps.economy.models import backfill_trial_history
        backfill_trial_history(write=True)
    except Exception:                                   # pragma: no cover
        logging.getLogger(__name__).exception("trial history backfill failed")


class Migration(migrations.Migration):
    dependencies = [("economy", "0214_remove_venueattendance_venue_and_more")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
