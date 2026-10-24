"""Put every claimed trial take into its owner's coach history.

Claiming a trial take at signup used to record the claim and nothing else: the
take never reached the member's history, so the thing they joined to keep was
never shown to them. New claims write the row now (`_claim_coached_trial`); this
is the past. Dry by default, like `rebuild_partnerships` — it lists what it would
add and writes nothing without `--write`. Safe to run twice.
"""
from django.core.management.base import BaseCommand

from apps.economy.models import backfill_trial_history


class Command(BaseCommand):
    help = "Add claimed trial takes to their owners' coach history (dry unless --write)."

    def add_arguments(self, parser):
        parser.add_argument("--write", action="store_true", help="Actually write.")

    def handle(self, *args, **opts):
        takes = backfill_trial_history(write=opts["write"])
        verb = "added" if opts["write"] else "would add"
        for t in takes:
            self.stdout.write(f"  {t.claimed_by.username}: {t.app_key} take #{t.pk} ({t.created_at:%Y-%m-%d})")
        self.stdout.write(f"{verb} {len(takes)} take(s).")
