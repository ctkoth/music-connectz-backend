"""Recompute the whole Partnership table from the events behind it.

`Partnership` is a tally kept by `release_deal` and `settle_battle`, which
means it can be wrong in exactly two ways: a row written before the tally
existed (everything up to migration 0118), and an increment that was swallowed
because something else in that request blew up. Neither is recoverable from
the row itself, and both are recoverable from the events.

So this is the equivalent of `reconcile_uploads`: the deliberate sweep that
makes the incremental path's mistakes temporary. Dry by default — it prints
what it would change and touches nothing without `--write`.

It REPLACES rather than adds to what is there, because a tally you can only
increase is one a double-fire corrupts permanently.
"""
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.economy.models import Battle, BattleEntry, CollabDeal, Partnership

User = get_user_model()


class Command(BaseCommand):
    help = "Recompute Partnership tallies from released deals and settled battles."

    def add_arguments(self, parser):
        parser.add_argument("--write", action="store_true",
                            help="Actually write. Without it, nothing changes.")

    def handle(self, *args, **opts):
        write = opts["write"]
        tally = defaultdict(lambda: {"collabs": 0, "battles": 0})

        # --- collabs: released, and it held something ----------------------
        #
        # `held_*` is zeroed at release, so the durable evidence that a deal
        # was worth anything is what the participants agreed to pay, frozen
        # into the row at the same moment. An empty deal auto-releases on its
        # own and is not work anybody did.
        ids_by_name = dict(User.objects.values_list("username", "id"))
        deals = CollabDeal.objects.filter(status=CollabDeal.STATUS_RELEASED)
        for initiator, parts in deals.values_list("initiator__username", "participants"):
            parts = parts or []
            moved = any(int(p.get("pays_cents") or 0) > 0
                        or int(p.get("stake_paid") or 0) > 0
                        for p in parts if isinstance(p, dict))
            if not moved:
                continue
            names = {p.get("username") for p in parts
                     if isinstance(p, dict) and p.get("username")}
            if initiator:
                names.add(initiator)
            self._add(tally, [ids_by_name.get(n) for n in names], "collabs")

        # --- battles: settled, with a winner -------------------------------
        entrants = defaultdict(list)
        for bid, uid in BattleEntry.objects.filter(
                battle__status=Battle.STATUS_SETTLED,
                battle__winner__isnull=False).values_list("battle_id", "user_id"):
            entrants[bid].append(uid)
        for uids in entrants.values():
            self._add(tally, uids, "battles")

        existing = {(r.a_id, r.b_id): r for r in Partnership.objects.all()}
        added = changed = cleared = 0
        for pair, counts in tally.items():
            row = existing.get(pair)
            if row is None:
                added += 1
            elif (row.collabs, row.battles) != (counts["collabs"], counts["battles"]):
                changed += 1
        for pair in existing:
            if pair not in tally:
                cleared += 1

        self.stdout.write(f"{len(tally)} partnerships from the events; "
                          f"{added} to add, {changed} to correct, {cleared} to delete.")
        if not write:
            self.stdout.write("Dry run. Re-run with --write to apply.")
            return

        with transaction.atomic():
            Partnership.objects.all().delete()
            Partnership.objects.bulk_create([
                Partnership(a_id=a, b_id=b, collabs=c["collabs"], battles=c["battles"])
                for (a, b), c in tally.items()
            ])
        self.stdout.write(self.style.SUCCESS(f"Wrote {len(tally)} partnerships."))

    @staticmethod
    def _add(tally, user_ids, field):
        ids = sorted({int(i) for i in user_ids if i})
        for n, first in enumerate(ids):
            for second in ids[n + 1:]:
                tally[(first, second)][field] += 1
