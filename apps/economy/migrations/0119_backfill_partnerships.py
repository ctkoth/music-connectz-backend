"""Seed the Partnership tally from the deals and battles that already settled.

Without this, shipping the tally would silently demote every member who had
already earned PartnerZ — the tab would go empty on deploy and stay empty
until they happened to finish something new. A derived list becoming a stored
one has to carry the past with it or it is a regression wearing a feature's
name.

The rules here are the same three the live hooks apply, deliberately duplicated
rather than imported: a migration that calls today's code stops describing what
it did the first time somebody edits that code.
"""
from collections import defaultdict

from django.conf import settings
from django.db import migrations


def backfill(apps, schema_editor):
    CollabDeal = apps.get_model("economy", "CollabDeal")
    BattleEntry = apps.get_model("economy", "BattleEntry")
    Partnership = apps.get_model("economy", "Partnership")
    User = apps.get_model(settings.AUTH_USER_MODEL)

    tally = defaultdict(lambda: [0, 0])   # (a, b) -> [collabs, battles]

    def add(user_ids, slot):
        ids = sorted({int(i) for i in user_ids if i})
        for n, first in enumerate(ids):
            for second in ids[n + 1:]:
                tally[(first, second)][slot] += 1

    ids_by_name = dict(User.objects.values_list("username", "id"))

    for initiator, parts in (CollabDeal.objects.filter(status="released")
                             .values_list("initiator__username", "participants")):
        parts = [p for p in (parts or []) if isinstance(p, dict)]
        if not any(int(p.get("pays_cents") or 0) > 0
                   or int(p.get("stake_paid") or 0) > 0 for p in parts):
            continue          # an empty deal auto-released itself; nobody worked
        names = {p.get("username") for p in parts if p.get("username")}
        if initiator:
            names.add(initiator)
        add([ids_by_name.get(n) for n in names], 0)

    entrants = defaultdict(list)
    for bid, uid in BattleEntry.objects.filter(
            battle__status="settled", battle__winner__isnull=False
    ).values_list("battle_id", "user_id"):
        entrants[bid].append(uid)
    for uids in entrants.values():
        add(uids, 1)

    Partnership.objects.bulk_create([
        Partnership(a_id=a, b_id=b, collabs=c, battles=w)
        for (a, b), (c, w) in tally.items()
    ], batch_size=500)


def unbackfill(apps, schema_editor):
    apps.get_model("economy", "Partnership").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("economy", "0118_partnership")]
    operations = [migrations.RunPython(backfill, unbackfill)]
