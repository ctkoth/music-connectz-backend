from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import Membership


class PaneZTests(TestCase):
    def setUp(self):
        self.u = get_user_model().objects.create_user("splitter", password="pw-long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def test_free_opens_three_a_day_then_is_told_when(self):
        for _ in range(3):
            self.assertEqual(self.c.post("/api/economy/panez/", {"app": "sentencez"}, format="json").status_code, 200)
        r = self.c.post("/api/economy/panez/", {"app": "sentencez"}, format="json")
        self.assertEqual(r.status_code, 429)
        self.assertIn("frees up in", r.data["detail"]); self.assertIn("Premium opens 6", r.data["detail"])
        self.assertEqual(self.c.get("/api/economy/panez/").data["left"], 0)

    def test_statz_opens_twelve_a_day_then_is_refused(self):
        # StatZ is 12 (Corey, Nov 2026): above Premium's 6, and a limit, not unlimited.
        m = Membership.objects.get_or_create(user=self.u)[0]; m.tier = "statz"; m.save()
        for _ in range(12):
            self.assertEqual(self.c.post("/api/economy/panez/", {}, format="json").status_code, 200)
        self.assertEqual(self.c.get("/api/economy/panez/").data["left"], 0)
        self.assertEqual(self.c.post("/api/economy/panez/", {}, format="json").status_code, 429)
