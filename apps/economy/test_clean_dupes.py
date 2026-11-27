from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import CleanDupeRun, Membership, membership_for

U = get_user_model()
URL = "/api/economy/cleanconnectz/dupes/"


def client(tier):
    u = U.objects.create_user(f"d_{tier}_{U.objects.count()}", password="pw12345!x")
    membership_for(u); Membership.objects.filter(user=u).update(tier=tier)
    c = APIClient(); c.force_authenticate(u)
    return c, u


class CleanDupesTests(TestCase):
    def test_every_plan_may_scan_the_tier_only_sets_how_often(self):
        got = {t: client(t)[0].get(URL).data for t in ("free", "premium", "statz")}
        self.assertEqual([got[t]["limit"] for t in ("free", "premium", "statz")], [3, 6, 12])
        self.assertTrue(all(g["can"] for g in got.values()))                 # nobody is shut out
        self.assertEqual(got["free"]["next_limit"], 6)
        self.assertIs(got["statz"]["next_limit"], False)

    def test_free_gets_three_a_day_then_a_sentence_and_nothing_is_written(self):
        c, u = client("free")
        for i in range(3):
            self.assertEqual(c.post(URL).status_code, 201)
        r = c.post(URL)
        self.assertEqual(r.status_code, 403)
        self.assertIn("3 of 3", r.data["detail"]); self.assertIn("Nothing was charged", r.data["detail"])
        self.assertEqual(CleanDupeRun.objects.filter(user=u).count(), 3)
        self.assertEqual(c.get(URL).data["left"], 0)

    def test_premium_gets_six_and_statz_gets_twelve(self):
        c, _ = client("premium")
        self.assertEqual([c.post(URL).status_code for _ in range(7)], [201] * 6 + [403])
        s, _ = client("statz")
        self.assertEqual([s.post(URL).status_code for _ in range(13)], [201] * 12 + [403])
        g = s.get(URL).data
        self.assertEqual((g["limit"], g["unlimited"]), (12, False))

    def test_the_window_is_rolling_a_day_old_scan_stops_counting(self):
        c, u = client("free")
        for _ in range(3):
            c.post(URL)
        CleanDupeRun.objects.filter(user=u).update(at=timezone.now() - timedelta(hours=25))
        self.assertEqual(c.get(URL).data["used"], 0)
        self.assertEqual(c.post(URL).status_code, 201)

    def test_counts_are_the_members_own_and_login_is_required(self):
        a, _ = client("free"); b, _ = client("free")
        a.post(URL)
        self.assertEqual(b.get(URL).data["used"], 0)
        self.assertEqual(APIClient().get(URL).status_code, 401)


class UpgradeNudgeTests(TestCase):
    def test_the_nudge_appears_only_when_one_is_left_or_none_and_never_on_the_top_plan(self):
        c, _ = client("free")
        self.assertFalse(c.get(URL).data["near"])                       # 3 left: plenty
        c.post(URL)
        self.assertFalse(c.get(URL).data["near"])                       # 2 left
        c.post(URL)
        d = c.get(URL).data
        self.assertTrue(d["near"]); self.assertEqual(d["upgrade"], {"tab": "membershipz", "target": "membershipz-plans"})
        c.post(URL)
        self.assertTrue(c.get(URL).data["near"])                        # none left
        s, _ = client("statz")
        for _ in range(8):
            s.post(URL)
        d = s.get(URL).data
        self.assertFalse(d["near"]); self.assertIsNone(d["upgrade"])    # unlimited: nothing to sell
        p, _ = client("premium")
        for _ in range(5):
            p.post(URL)
        self.assertTrue(p.get(URL).data["near"])                        # premium nudges toward StatZ at 5 of 6
