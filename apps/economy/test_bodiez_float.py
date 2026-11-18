"""A live BodieZ session stays on screen over other apps — the number is the tier's, and it is stated first."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy import bodiez_float
from apps.economy.catalog import limits_for
from apps.economy.ladders import ladders
from apps.economy.models import BodieZSession, Membership

U = get_user_model()


def member(name, tier="free"):
    u = U.objects.create_user(name, password="pw12345!x")
    m, _ = Membership.objects.get_or_create(user=u)
    m.tier = tier
    m.save()
    return u


def client(u):
    c = APIClient()
    c.force_authenticate(u)
    return c


class FloatNumbersTests(TestCase):
    def test_the_ladder_is_coreys_numbers(self):
        self.assertEqual([limits_for(t)["bodiez_float"] for t in ("free", "premium", "statz")], [3, 6, None])

    def test_it_is_on_the_ladder_list(self):
        row = next(r for r in ladders() if r["key"] == "bodiez_float")
        self.assertEqual(row["values"], {"free": "3", "premium": "6", "statz": "Unlimited"})


class FloatSessionTests(TestCase):
    def setUp(self):
        self.u = member("lifter")
        self.c = client(self.u)

    def open_session(self, user=None):
        return BodieZSession.objects.create(user=user or self.u)

    def test_the_price_is_served_before_anything_is_pressed(self):
        s = self.open_session()
        st = self.c.get("/api/economy/bodiez/float/").data
        self.assertEqual((st["limit"], st["used"], st["left"]), (3, 0, 3))
        self.assertTrue(st["can"])
        self.assertFalse(st["already"])
        self.assertEqual(st["next_limit"], 6)
        self.assertEqual(st["ladder"], {"free": 3, "premium": 6, "statz": None})
        self.assertIn("Free", st["cost"])
        self.assertEqual(st["session"], {"id": s.id, "floated": False})
        s.refresh_from_db()
        self.assertIsNone(s.floated_at)                         # reading the price costs nothing and writes nothing
        self.assertEqual(self.c.get("/api/economy/bodiez/float/").data["used"], 0)

    def test_the_state_follows_the_session_once_it_is_kept(self):
        s = self.open_session()
        self.c.post(f"/api/economy/bodiez/sessions/{s.id}/float/")
        self.assertEqual(self.c.get("/api/economy/bodiez/float/").data["session"], {"id": s.id, "floated": True})

    def test_no_open_session_means_no_session_in_the_state(self):
        self.assertIsNone(self.c.get("/api/economy/bodiez/float/").data["session"])

    def test_pressing_it_counts_once_per_session(self):
        s = self.open_session()
        r = self.c.post(f"/api/economy/bodiez/sessions/{s.id}/float/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["float"]["used"], 1)
        self.assertTrue(r.data["float"]["already"])
        r2 = self.c.post(f"/api/economy/bodiez/sessions/{s.id}/float/")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data["float"]["used"], 1)             # off and on again is not charged twice
        self.assertEqual(r2.data["floated_at"], r.data["floated_at"])

    def test_free_stops_at_three_a_day_and_says_so_without_charging(self):
        for _ in range(3):
            s = self.open_session()
            self.assertEqual(self.c.post(f"/api/economy/bodiez/sessions/{s.id}/float/").status_code, 200)
            BodieZSession.objects.filter(id=s.id).update(ended_at=timezone.now())
        s4 = self.open_session()
        r = self.c.post(f"/api/economy/bodiez/sessions/{s4.id}/float/")
        self.assertEqual(r.status_code, 403)
        self.assertIn("3 of 3", r.data["detail"])
        self.assertIn("Nothing was charged", r.data["detail"])
        self.assertIn("untouched", r.data["detail"])
        self.assertEqual(r.data["float"]["next_limit"], 6)
        s4.refresh_from_db()
        self.assertIsNone(s4.floated_at)                          # a refusal writes nothing
        self.assertEqual(self.c.get("/api/economy/bodiez/float/").data["used"], 3)

    def test_the_window_is_rolling_not_a_calendar_day(self):
        for _ in range(3):
            BodieZSession.objects.create(user=self.u, ended_at=timezone.now(),
                                         floated_at=timezone.now() - timedelta(hours=25))
        self.assertEqual(bodiez_float.used_since(self.u), 0)
        s = self.open_session()
        self.assertEqual(self.c.post(f"/api/economy/bodiez/sessions/{s.id}/float/").status_code, 200)

    def test_a_session_already_on_screen_is_not_refused_at_the_limit(self):
        s = self.open_session()
        self.c.post(f"/api/economy/bodiez/sessions/{s.id}/float/")
        for _ in range(2):
            BodieZSession.objects.create(user=self.u, ended_at=timezone.now(), floated_at=timezone.now())
        self.assertEqual(self.c.get("/api/economy/bodiez/float/").data["left"], 0)
        self.assertEqual(self.c.post(f"/api/economy/bodiez/sessions/{s.id}/float/").status_code, 200)

    def test_premium_gets_six_and_statz_has_no_ceiling(self):
        p = member("prem", "premium")
        self.assertEqual(client(p).get("/api/economy/bodiez/float/").data["limit"], 6)
        z = member("zed", "statz")
        for _ in range(10):
            BodieZSession.objects.create(user=z, ended_at=timezone.now(), floated_at=timezone.now())
        s = self.open_session(z)
        st = client(z).get("/api/economy/bodiez/float/").data
        self.assertTrue(st["unlimited"])
        self.assertIsNone(st["left"])
        self.assertIs(st["next_limit"], False)
        self.assertEqual(client(z).post(f"/api/economy/bodiez/sessions/{s.id}/float/").status_code, 200)

    def test_only_a_live_session_of_your_own(self):
        done = BodieZSession.objects.create(user=self.u, ended_at=timezone.now())
        self.assertEqual(self.c.post(f"/api/economy/bodiez/sessions/{done.id}/float/").status_code, 409)
        typed = BodieZSession.objects.create(user=self.u, backfilled=True)
        self.assertEqual(self.c.post(f"/api/economy/bodiez/sessions/{typed.id}/float/").status_code, 409)
        other = member("other")
        theirs = self.open_session(other)
        self.assertEqual(self.c.post(f"/api/economy/bodiez/sessions/{theirs.id}/float/").status_code, 404)

    def test_the_session_dict_carries_it_so_a_reload_knows(self):
        s = self.open_session()
        self.assertIsNone(self.c.get("/api/economy/bodiez/sessions/").data["sessions"][0]["floated_at"])
        self.c.post(f"/api/economy/bodiez/sessions/{s.id}/float/")
        self.assertIsNotNone(self.c.get("/api/economy/bodiez/sessions/").data["sessions"][0]["floated_at"])

    def test_it_spends_nothing(self):
        import inspect
        src = inspect.getsource(bodiez_float)
        for name in ("spend_spinaz", "charge_ai_usage", "_bill", "charge_skill_energy"):
            self.assertNotIn(name, src)
