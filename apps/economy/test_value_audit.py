"""Three values the economy audit moved, held so they cannot drift back.

* SoundCloud engagement is self-reported, so it pays 1 ⚡ and no 🍥 — and it PAYS:
  it used to write ledger rows and never touch the wallet.
* Coaching a post costs the same ⚡ on every tier (test_coach_post_energy).
* The CollabZ rating bar is one number; a tier never buys a lower one.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (Post, Transaction, membership_for, post_collab_threshold,
                                 wallet_for)

User = get_user_model()


class SoundCloudEngagementPaysWhatItSaysTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user(username="sc", password="hunter2hunter2")
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def test_a_like_credits_one_energy_and_no_spinaz(self):
        before = wallet_for(self.u)
        e0, s0 = before.energy, before.spinaz
        r = self.c.post("/api/economy/soundcloud/engagement/",
                        {"kind": "like", "track_url": "https://soundcloud.com/a/b", "track_id": "1"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["reward"], {"energy": 1, "spinaz": 0})
        w = wallet_for(self.u)
        self.assertEqual((w.energy - e0, w.spinaz - s0), (1, 0))       # the wallet moved, not only the log
        self.assertFalse(Transaction.objects.filter(user=self.u, resource=Transaction.RES_SPINAZ).exists())


class OneCollabBarTests(TestCase):
    def test_every_tier_needs_the_same_rating(self):
        bars = set()
        for i, t in enumerate(("free", "premium", "statz")):
            u = User.objects.create_user(username=f"a{i}", password="hunter2hunter2")
            m = membership_for(u); m.tier = t; m.save(update_fields=["tier", "updated_at"])
            bars.add(post_collab_threshold(Post(author=u)))
        self.assertEqual(bars, {7.0})
