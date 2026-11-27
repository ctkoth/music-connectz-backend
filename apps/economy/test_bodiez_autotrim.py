"""Auto-trim is counted by tier (Free 3, Premium 6, StatZ 12 lifts a rolling 24h), a lift counts once per
session, a refusal writes nothing and says how to do it by hand, and only a live session of your own is trimmed."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy import bodiez_autotrim as at
from apps.economy.catalog import limits_for
from apps.economy.models import BodieZAutoTrim, BodieZSession, membership_for

User = get_user_model()


class AutoTrimTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("lifter", "l@e.com", "pw12345!")
        self.c = APIClient()
        self.c.force_authenticate(self.me)
        self.sess = BodieZSession.objects.create(user=self.me)

    def tier(self, t):
        m = membership_for(self.me)
        m.tier = t
        m.save()

    def trim(self, ids, sess=None):
        return self.c.post(f"/api/economy/bodiez/sessions/{(sess or self.sess).id}/autotrim/",
                           {"exercise_ids": ids}, format="json")

    def test_the_tier_numbers_are_coreys(self):
        self.assertEqual([limits_for(t)["bodiez_autotrim"] for t in ("free", "premium", "statz")], [3, 6, 12])

    def test_the_number_is_stated_before_anything_is_trimmed(self):
        d = self.c.get("/api/economy/bodiez/autotrim/").json()
        self.assertEqual((d["limit"], d["used"], d["left"], d["next_limit"]), (3, 0, 3, 6))
        self.assertIn("Free", d["cost"])

    def test_free_trims_three_then_refuses_with_the_way_to_do_it_by_hand(self):
        r = self.trim([1, 2, 3, 4]).json()
        self.assertEqual(r["granted"], [1, 2, 3])
        self.assertEqual(r["refused"], [4])
        self.assertIn("Tap its sets", r["detail"])
        self.assertIn("Nothing was charged", r["detail"])
        self.assertEqual(BodieZAutoTrim.objects.count(), 3)          # the refusal wrote nothing

    def test_a_lift_counts_once_a_session(self):
        self.trim([1])
        r = self.trim([1]).json()
        self.assertEqual(r["granted"], [1])
        self.assertEqual(r["autotrim"]["used"], 1)

    def test_premium_six_statz_twelve(self):
        self.tier("premium")
        self.assertEqual(self.trim(list(range(1, 9))).json()["granted"], list(range(1, 7)))
        self.tier("statz")
        # Six were counted on Premium above, so StatZ's twelve leave six for 9..24.
        r = self.trim(list(range(9, 25))).json()
        self.assertEqual(r["granted"], list(range(9, 15)))
        self.assertEqual(r["refused"], list(range(15, 25)))
        self.assertEqual(r["autotrim"]["limit"], 12)

    def test_the_window_rolls(self):
        self.trim([1, 2, 3])
        BodieZAutoTrim.objects.update(created_at=timezone.now() - timedelta(hours=at.WINDOW_HOURS + 1))
        self.assertEqual(self.trim([4]).json()["granted"], [4])

    def test_only_a_live_session_of_your_own(self):
        done = BodieZSession.objects.create(user=self.me, ended_at=timezone.now())
        self.assertEqual(self.trim([1], done).status_code, 409)
        other = BodieZSession.objects.create(user=User.objects.create_user("x", "x@e.com", "pw12345!"))
        self.assertEqual(self.trim([1], other).status_code, 404)
        self.assertIn(APIClient().get("/api/economy/bodiez/autotrim/").status_code, (401, 403))

    def test_junk_ids_are_dropped_not_refused(self):
        r = self.trim(["a", None, -3, 2, 2]).json()
        self.assertEqual(r["granted"], [2])

    def test_it_spends_nothing(self):
        import inspect
        src = inspect.getsource(at)
        for spend in ("charge_ai_usage", "spend_spinaz", "_bill", "charge_skill_energy", "_spend_energy_up_to"):
            self.assertNotIn(spend, src)
