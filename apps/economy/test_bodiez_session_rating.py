"""Session rating out of 10, and the opt-in BodieZ leaderboard."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .bodiez import LB_MIN_SESSIONS, session_coach_rating
from .models import BodieZExercise, BodieZSession, BodieZSet


def _session(user, ex, kg, days_ago):
    s = BodieZSession.objects.create(user=user, ended_at=timezone.now())
    BodieZSession.objects.filter(pk=s.pk).update(started_at=timezone.now() - timedelta(days=days_ago))
    s.refresh_from_db()
    BodieZSet.objects.create(session=s, exercise=ex, set_number=1, reps=5, weight_kg=kg)
    return s


class SessionRatingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="r1", password="pw")
        self.ex = BodieZExercise.objects.create(name="T Bench", muscle_group="chest", equipment="barbell")

    def test_first_session_is_unrated_not_zero(self):
        s = _session(self.user, self.ex, 50, 5)
        self.assertIsNone(session_coach_rating(s)["rating"])

    def test_up_held_down(self):
        _session(self.user, self.ex, 100, 10)
        self.assertEqual(session_coach_rating(_session(self.user, self.ex, 110, 5))["rating"], 10)
        self.assertEqual(session_coach_rating(_session(self.user, self.ex, 100, 4))["rating"], 6)
        self.assertEqual(session_coach_rating(_session(self.user, self.ex, 70, 3))["rating"], 3)

    def test_summary_carries_rating_and_caveat(self):
        _session(self.user, self.ex, 100, 10)
        s = _session(self.user, self.ex, 110, 1)
        c = APIClient(); c.force_authenticate(self.user)
        r = c.get(f"/api/economy/bodiez/sessions/{s.id}/summary/").data["coach_rating"]
        self.assertEqual(r["rating"], 10)
        self.assertTrue(r["caveat"])


class LeaderboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="l1", password="pw")
        self.ex = BodieZExercise.objects.create(name="T Row", muscle_group="back", equipment="barbell")
        self.c = APIClient(); self.c.force_authenticate(self.user)
        _session(self.user, self.ex, 50, 20)
        for i in range(LB_MIN_SESSIONS):
            _session(self.user, self.ex, 60 + 10 * i, 10 - i)

    def test_off_by_default_and_hidden(self):
        d = self.c.get("/api/economy/bodiez/leaderboard/").data
        self.assertFalse(d["opted_in"])
        self.assertEqual(d["leaders"], [])

    def test_opt_in_shows_then_leave_hides(self):
        d = self.c.post("/api/economy/bodiez/leaderboard/", {"opt_in": True}, format="json").data
        self.assertTrue(d["opted_in"])
        self.assertEqual([r["username"] for r in d["leaders"]], ["l1"])
        d = self.c.post("/api/economy/bodiez/leaderboard/", {"opt_in": False}, format="json").data
        self.assertEqual(d["leaders"], [])

    def test_junk_refused(self):
        r = self.c.post("/api/economy/bodiez/leaderboard/", {"opt_in": "yes"}, format="json")
        self.assertEqual(r.status_code, 400)
