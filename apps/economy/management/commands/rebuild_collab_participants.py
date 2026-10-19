"""Re-derive CollabParticipant from the participants JSON. Dry by default.

The sync runs from a swallowed `post_save` signal — an index must never be the
reason money fails to move — which means it CAN drift, and a lookup table that
can drift needs a way back. Same shape as `rebuild_partnerships`, and it
**replaces** rather than adds for the same reason: a row set you can only add
to is one a bad write corrupts permanently.

    python manage.py rebuild_collab_participants
    python manage.py rebuild_collab_participants --write
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.economy.models import CollabDeal, CollabParticipant


class Command(BaseCommand):
    help = "Rebuild the CollabParticipant index from each deal's participants JSON."

    def add_arguments(self, parser):
        parser.add_argument("--write", action="store_true",
                            help="Actually apply the changes. Dry run otherwise.")

    def handle(self, *args, **opts):
        ids = dict(get_user_model().objects.values_list("username", "id"))

        want = set()
        unknown = 0
        for deal_id, participants in CollabDeal.objects.values_list("id", "participants"):
            for p in (participants or []):
                if not isinstance(p, dict):
                    continue
                name = str(p.get("username") or "").strip()
                if not name:
                    continue
                uid = ids.get(name)
                if uid is None:
                    # Named on a deal with no account behind the name. The JSON
                    # is still the record of what the deal says; this is only
                    # the index, so it is reported rather than invented.
                    unknown += 1
                    continue
                want.add((deal_id, uid))

        have = set(CollabParticipant.objects.values_list("deal_id", "user_id"))
        missing, extra = want - have, have - want

        self.stdout.write(f"deals            {CollabDeal.objects.count()}")
        self.stdout.write(f"rows wanted      {len(want)}")
        self.stdout.write(f"rows present     {len(have)}")
        self.stdout.write(f"missing          {len(missing)}")
        self.stdout.write(f"extra            {len(extra)}")
        if unknown:
            self.stdout.write(f"named, no account {unknown} (left out of the index)")

        if not opts["write"]:
            self.stdout.write("\nDry run. Nothing changed — pass --write to apply.")
            return

        if extra:
            for deal_id, uid in extra:
                CollabParticipant.objects.filter(deal_id=deal_id, user_id=uid).delete()
        if missing:
            CollabParticipant.objects.bulk_create(
                [CollabParticipant(deal_id=d, user_id=u) for d, u in missing],
                batch_size=500, ignore_conflicts=True)
        self.stdout.write(f"\nWrote: +{len(missing)} -{len(extra)}")
