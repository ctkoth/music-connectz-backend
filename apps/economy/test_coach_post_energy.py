"""Coaching a post costs tiered ⚡ on top of the prompt, checked before the model runs."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.catalog import COACH_POST_ENERGY
from apps.economy.models import Post, Wallet, membership_for, wallet_for
from apps.economy.vocalcoach import coach_post_energy

User = get_user_model()


class CoachPostEnergyTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("singer", "s@e.com", "pw-Long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def tier(self, t):
        m = membership_for(self.u); m.tier = t; m.save(update_fields=["tier", "updated_at"])

    def test_the_price_is_tiered_and_published_before_anything_runs(self):
        for t in ("free", "premium", "statz"):
            self.tier(t)
            self.assertEqual(coach_post_energy(self.u), COACH_POST_ENERGY[t])
            self.assertEqual(self.c.get("/api/singz/coach/").json()["post_energy_cost"], COACH_POST_ENERGY[t])
        self.assertLess(COACH_POST_ENERGY["free"], COACH_POST_ENERGY["premium"])
        self.assertLess(COACH_POST_ENERGY["premium"], COACH_POST_ENERGY["statz"])

    def test_without_the_energy_the_post_is_refused_before_the_model_runs(self):
        post = Post.objects.create(author=self.u, title="my verse")
        Wallet.objects.update_or_create(user=self.u, defaults={"energy": 0})
        r = self.c.post("/api/singz/coach/", {"post_id": post.id}, format="json")
        self.assertIn(r.status_code, (402, 400, 404, 410))   # never a scored 200
        if r.status_code == 402:
            self.assertTrue(r.json().get("insufficient"))
        self.assertEqual(wallet_for(self.u).energy, 0)
