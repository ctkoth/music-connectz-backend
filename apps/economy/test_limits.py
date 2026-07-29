from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.catalog import chars_unlimited, limits_for
from apps.economy.models import (TIER_FREE, TIER_PREMIUM, TIER_STATZ,
                                 Message, membership_for)

User = get_user_model()


class CharLimitTests(TestCase):
    def test_free_and_premium_keep_their_caps(self):
        self.assertEqual(limits_for(TIER_FREE)["char_limit"], 400)
        self.assertEqual(limits_for(TIER_PREMIUM)["char_limit"], 1500)
        self.assertFalse(chars_unlimited(TIER_FREE))
        self.assertFalse(chars_unlimited(TIER_PREMIUM))

    def test_statz_is_unlimited(self):
        self.assertTrue(chars_unlimited(TIER_STATZ))


class MessageCapTests(TestCase):
    """The cap is enforced on send, so this is where unlimited has to hold."""

    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", "pw12345678")
        self.peer = User.objects.create_user("peer", "peer@e.com", "pw12345678")
        self.client.force_authenticate(self.me)

    def _tier(self, tier):
        m = membership_for(self.me)
        m.tier = tier
        m.save(update_fields=["tier", "updated_at"])

    def test_free_still_refused_past_400(self):
        self._tier(TIER_FREE)
        resp = self.client.post("/api/economy/messages/",
                                {"to": "peer", "body": "x" * 401}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("400-character limit", resp.data["detail"])

    def test_statz_sends_far_past_the_old_5000_cap(self):
        self._tier(TIER_STATZ)
        body = "x" * 50_000
        resp = self.client.post("/api/economy/messages/",
                                {"to": "peer", "body": body}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        # and it is stored whole, not silently truncated
        self.assertEqual(len(Message.objects.get(sender=self.me).body), 50_000)

    def test_limits_endpoint_flags_unlimited_for_the_client(self):
        self._tier(TIER_STATZ)
        data = self.client.get("/api/economy/limits/").data
        self.assertTrue(data["char_limit_unlimited"])
        self._tier(TIER_PREMIUM)
        data = self.client.get("/api/economy/limits/").data
        self.assertFalse(data["char_limit_unlimited"])
        self.assertEqual(data["char_limit"], 1500)
