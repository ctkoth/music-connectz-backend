from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import breathz as B
from apps.economy.models import TakeScore
from apps.skillz.models import TrainingEvent, TrainingProfile

URL = "/api/economy/breathz/"


class BreathZTests(TestCase):
    def setUp(self):
        self.u = get_user_model().objects.create_user("breather", "b@e.com", "pw-Long-enough-1")
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def test_it_is_free_says_what_it_cannot_do_and_every_pattern_says_what_and_why(self):
        d = self.c.get(URL).json()
        self.assertTrue(d["free"])
        self.assertIn("never", d["caveat"])
        self.assertIn("can't measure", d["caveat"])
        for p in d["patterns"]:
            self.assertTrue(p["what"] and p["why"] and p["steps"] and p["min_seconds"] > 0, p["key"])
        self.assertIn("rapz", [x for p in d["patterns"] if p["key"] == "bar_breath" for x in p["for"]])

    def test_a_finished_session_pays_xp_and_a_streak_and_a_short_one_pays_nothing(self):
        short = self.c.post(URL, {"pattern": "box", "seconds": 10}, format="json").json()
        self.assertFalse(short["counted"])
        self.assertEqual(TrainingEvent.objects.count(), 0)
        ok = self.c.post(URL, {"pattern": "box", "seconds": 96}, format="json").json()
        self.assertTrue(ok["counted"])
        self.assertEqual(ok["xp_awarded"], B.BY_KEY["box"]["xp"])
        self.assertEqual(TrainingProfile.objects.get(user=self.u, app_key="breathz").current_streak, 1)

    def test_xp_is_for_turning_up_a_few_times_not_a_hundred(self):
        for _ in range(B.COUNTED_PER_DAY):
            self.assertTrue(self.c.post(URL, {"pattern": "box", "seconds": 90}, format="json").json()["counted"])
        extra = self.c.post(URL, {"pattern": "box", "seconds": 90}, format="json").json()
        self.assertFalse(extra["counted"])
        self.assertEqual(extra["xp_awarded"], 0)
        self.assertEqual(self.c.get(URL).json()["counted_today"], B.COUNTED_PER_DAY)

    def test_an_unknown_pattern_is_refused(self):
        self.assertEqual(self.c.post(URL, {"pattern": "turbo", "seconds": 999}, format="json").status_code, 400)

    def test_it_never_touches_a_rating_and_reads_back_the_coachs_breath_score(self):
        for v in (4, 4, 5, 6, 6, 7):
            TakeScore.objects.create(user=self.u, app_key="rapz", scores={"breath": v}, overall=6)
        before = list(TakeScore.objects.values_list("scores", flat=True))
        self.c.post(URL, {"pattern": "box", "seconds": 96}, format="json")
        self.assertEqual(before, list(TakeScore.objects.values_list("scores", flat=True)))   # no score moved
        b = self.c.get(URL).json()["breath"]
        self.assertEqual(b["takes"], 6)
        self.assertIsNotNone(b["average"])

    def test_a_weak_breath_leads_here_from_the_coach(self):
        from apps.economy import takescorez as T
        for _ in range(3):
            TakeScore.objects.create(user=self.u, app_key="rapz", scores={"breath": 3}, overall=5, weakest="breath")
        board = self.c.get("/api/rapz/progress/").data["coaching"]
        door = [h for p in board["problems"] if p["key"] == "breath" for h in p["help"] if h["key"] == "breathz"][0]
        self.assertIsNone(door["cost"])
        self.assertEqual(door["tab"], "breathz")
        row = self.c.get("/api/rapz/progress/").data["takes"][0]
        self.assertIn("breathz", [e["key"] for e in row["exports"]])
