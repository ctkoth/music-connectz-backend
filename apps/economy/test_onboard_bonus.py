from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import Transaction, profile_for
from apps.economy.test_earn import earn_onboarding


class OnboardBonusTests(TestCase):
    def setUp(self):
        self.u = get_user_model().objects.create_user("fresh", password="pw-long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def test_claiming_without_doing_anything_is_refused_and_says_what_is_left(self):
        r = self.c.post("/api/auth/onboard/complete/")
        self.assertEqual(r.status_code, 409)
        self.assertIn("a scored take", r.data["detail"]); self.assertIn("3 ratings (0 so far)", r.data["detail"])
        self.assertFalse(profile_for(self.u).onboarded)
        self.assertFalse(Transaction.objects.filter(user=self.u, note__startswith="onboarding").exists())

    def test_doing_the_three_things_pays_once(self):
        earn_onboarding(self.u)
        self.assertTrue(self.c.get("/api/auth/onboard/complete/").data["progress"]["score"])
        r = self.c.post("/api/auth/onboard/complete/")
        self.assertEqual(r.status_code, 200); self.assertTrue(r.data["granted"])
        self.assertFalse(self.c.post("/api/auth/onboard/complete/").data["granted"])
