"""Registered item kinds: a 'score:<token>' must exist, its owner is notified, and
the owner can't like or rate their own take."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import ScoreShare

User = get_user_model()


class ScoreItemTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("singer", "s@e.com", "pw-Long-enough-1")
        self.fan = User.objects.create_user("fan", "f@e.com", "pw-Long-enough-1")
        self.share = ScoreShare.objects.create(token="tok123", app_key="singz", score=7, user=self.owner)
        self.c = APIClient(); self.c.force_authenticate(self.fan)
        self.o = APIClient(); self.o.force_authenticate(self.owner)

    def test_an_invented_token_is_refused_so_nothing_is_paid_for_it(self):
        for action, body in (("react", {"value": 1}), ("rate", {"score": 8}), ("comment", {"body": "hi"})):
            r = self.c.post(f"/api/economy/social/{action}/", {"item": "score:nope", **body}, format="json")
            self.assertEqual(r.status_code, 404, action)

    def test_a_real_take_can_be_liked_and_commented_and_the_owner_hears(self):
        from apps.economy.models import Notification
        r = self.c.post("/api/economy/social/react/", {"item": "score:tok123", "value": 1}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["up"], 1)
        n = Notification.objects.filter(user=self.owner).first()
        self.assertIsNotNone(n)
        self.assertIn("your take", n.text if hasattr(n, "text") else str(n.__dict__))

    def test_the_owner_cannot_like_or_rate_their_own_but_can_comment(self):
        self.assertEqual(self.o.post("/api/economy/social/react/", {"item": "score:tok123", "value": 1}, format="json").status_code, 403)
        self.assertEqual(self.o.post("/api/economy/social/rate/", {"item": "score:tok123", "score": 9}, format="json").status_code, 403)
        self.assertEqual(self.o.post("/api/economy/social/comment/", {"item": "score:tok123", "body": "thanks all"}, format="json").status_code, 200)
