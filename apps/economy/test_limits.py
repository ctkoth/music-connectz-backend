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


class TierUploadLimitsTests(TestCase):
    """The sizes Corey set, and the invariant that keeps them coherent."""

    def test_the_table(self):
        from apps.economy.catalog import limits_for
        self.assertEqual(limits_for(TIER_FREE)["upload_mb"], 100)
        self.assertEqual(limits_for(TIER_PREMIUM)["upload_mb"], 1024)       # 1GB
        self.assertEqual(limits_for(TIER_STATZ)["upload_mb"], 10240)        # 10GB
        self.assertEqual(limits_for(TIER_FREE)["storage_mb"], 500)
        self.assertEqual(limits_for(TIER_PREMIUM)["storage_mb"], 5120)      # 5GB
        self.assertEqual(limits_for(TIER_STATZ)["storage_mb"], 102400)      # 100GB

    def test_a_vault_always_holds_the_file_it_admits(self):
        # The bug the written table would have shipped: Free was 100MB per
        # file into a 50MB vault, so the upload passes the size check and then
        # fails the quota check — allowed by one rule, refused by the next.
        from apps.economy.catalog import TIER_LIMITS
        for tier, lim in TIER_LIMITS.items():
            self.assertGreaterEqual(
                lim["storage_mb"], lim["upload_mb"],
                f"{tier}: a {lim['upload_mb']}MB file can never fit a "
                f"{lim['storage_mb']}MB vault",
            )

    def test_every_tier_is_bigger_than_the_one_below(self):
        from apps.economy.catalog import limits_for
        for key in ("upload_mb", "storage_mb"):
            free, premium, statz = (limits_for(t)[key]
                                    for t in (TIER_FREE, TIER_PREMIUM, TIER_STATZ))
            self.assertLess(free, premium, key)
            self.assertLess(premium, statz, key)

    def test_the_coach_cap_says_it_is_not_a_tier_limit(self):
        # A StatZ member with 10GB per file who gets refused at 14MB will read
        # that as the plan they paid for being ignored, unless it says what it
        # actually is: the scorer's own request ceiling.
        from apps.economy.vocalcoach import MAX_MB
        from apps.economy.catalog import limits_for
        self.assertLess(MAX_MB, limits_for(TIER_FREE)["upload_mb"])
        u = User.objects.create_user(username="singer", password="hunter2hunter2")
        membership_for(u)
        c = APIClient(); c.force_authenticate(u)
        d = c.get("/api/singz/coach/").data
        self.assertEqual(d["max_mb"], MAX_MB)
        self.assertFalse(d["max_mb_is_tier_limit"])
        self.assertIn("isn't your tier's upload limit", d["max_mb_why"])
