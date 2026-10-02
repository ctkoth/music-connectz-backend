"""The StatZ sample: once per member, a real end time, and only the features
that can switch off again."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy import statz_trial
from apps.economy.models import StatzTrial, membership_for

URL = "/api/economy/statz-trial/"


class StatzTrialTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("t", "t@e.com", "pw-Long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.user)

    def test_offered_then_started_then_counting_down(self):
        s = self.c.get(URL).json()
        self.assertTrue(s["available"]); self.assertFalse(s["active"])
        self.assertFalse(statz_trial.has_statz(self.user))
        s = self.c.post(URL).json()
        self.assertTrue(s["active"]); self.assertFalse(s["available"])
        self.assertGreater(s["seconds_left"], 59 * 60)
        self.assertTrue(statz_trial.has_statz(self.user))

    def test_once_ever(self):
        self.c.post(URL)
        self.assertEqual(self.c.post(URL).status_code, 409)

    def test_it_really_ends(self):
        self.c.post(URL)
        StatzTrial.objects.filter(user=self.user).update(ends_at=timezone.now() - timedelta(seconds=1))
        s = self.c.get(URL).json()
        self.assertFalse(s["active"]); self.assertTrue(s["used"]); self.assertEqual(s["seconds_left"], 0)
        self.assertFalse(statz_trial.has_statz(self.user))
        self.assertEqual(self.c.get("/api/economy/instrumentalz/moods/?q=dark").status_code, 403)

    def test_it_unlocks_mood_search_while_running(self):
        self.c.post(URL)
        self.assertEqual(self.c.get("/api/economy/instrumentalz/moods/?q=dark").status_code, 200)

    def test_it_never_changes_the_real_tier(self):
        before = membership_for(self.user).tier
        self.c.post(URL)
        self.assertEqual(membership_for(self.user).tier, before)
        self.assertEqual(statz_trial.feature_tier(self.user), "statz")

    def test_statz_members_are_not_offered_one(self):
        m = membership_for(self.user); m.tier = "statz"; m.save()
        s = self.c.get(URL).json()
        self.assertFalse(s["available"]); self.assertTrue(s["is_statz"])
        self.assertEqual(self.c.post(URL).status_code, 400)
