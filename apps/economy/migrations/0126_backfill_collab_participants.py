"""Seed CollabParticipant from the participants JSON already on every deal.

Without this, shipping the table would empty the deal list for everybody who
is a participant rather than an initiator — the exact failure the table exists
to fix, caused by the fix. Migration 0119 did the same job for `Partnership`
and its note says why: a lookup built from live events starts empty, and an
empty lookup is indistinguishable from "you are in no deals".
"""
from django.db import migrations


def seed(apps, schema_editor):
    CollabDeal = apps.get_model("economy", "CollabDeal")
    CollabParticipant = apps.get_model("economy", "CollabParticipant")
    User = apps.get_model("auth", "User")

    ids = dict(User.objects.values_list("username", "id"))
    rows, seen = [], set()
    for deal_id, participants in CollabDeal.objects.values_list("id", "participants"):
        for p in (participants or []):
            if not isinstance(p, dict):
                continue
            uid = ids.get(str(p.get("username") or "").strip())
            # A name with no account is skipped, not guessed at. The JSON is
            # still the record of what the deal says; this is only the index.
            if uid and (deal_id, uid) not in seen:
                seen.add((deal_id, uid))
                rows.append(CollabParticipant(deal_id=deal_id, user_id=uid))
    CollabParticipant.objects.bulk_create(rows, batch_size=500, ignore_conflicts=True)


def unseed(apps, schema_editor):
    apps.get_model("economy", "CollabParticipant").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("economy", "0125_collab_participant")]
    operations = [migrations.RunPython(seed, unseed)]
