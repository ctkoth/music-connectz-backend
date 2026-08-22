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

    def test_the_coach_never_advertises_more_than_a_member_can_upload(self):
        """The invariant this test has always been about, now that the two
        ceilings can cross.

        A StatZ member refused at 14MB reads that as the plan they paid for
        being ignored — so the app says whose limit it is. That sentence was
        safe to hardcode while the coach's cap was under EVERY tier's upload
        limit. It isn't any more: the coach takes 200MB and Free uploads 100MB.
        Advertising 200 to a Free member, with copy insisting it isn't their
        tier, would be a size the app cannot honour and a denial of the very
        limit doing the refusing.

        So the ceiling is per-member, and never above what they can upload.
        """
        from apps.economy.catalog import limits_for
        from apps.economy.vocalcoach import MAX_MB

        for tier in (TIER_FREE, TIER_PREMIUM, TIER_STATZ):
            u = User.objects.create_user(username=f"singer-{tier}",
                                         password="hunter2hunter2")
            m = membership_for(u); m.tier = tier; m.save()
            c = APIClient(); c.force_authenticate(u)
            d = c.get("/api/singz/coach/").data
            upload_mb = limits_for(tier)["upload_mb"]

            self.assertLessEqual(d["max_mb"], upload_mb,
                                 f"{tier}: the coach is offering more than this "
                                 f"member can upload")
            self.assertEqual(d["max_mb"], min(MAX_MB, upload_mb))
            # And the copy agrees with the number about whose limit it is.
            if d["max_mb_is_tier_limit"]:
                self.assertIn("Your tier", d["max_mb_why"])
                self.assertNotIn("isn't your tier's", d["max_mb_why"])
            else:
                self.assertIn("isn't your tier's upload limit", d["max_mb_why"])

    def test_a_free_member_is_bound_by_their_tier_and_told_so(self):
        u = User.objects.create_user(username="freebie", password="hunter2hunter2")
        m = membership_for(u); m.tier = TIER_FREE; m.save()
        c = APIClient(); c.force_authenticate(u)
        d = c.get("/api/singz/coach/").data
        self.assertTrue(d["max_mb_is_tier_limit"])
        # ...and what a tier up would buy is on the same screen.
        self.assertGreater(d["coach_max_mb"], d["max_mb"])

    def test_a_statz_member_gets_the_coachs_own_ceiling(self):
        from apps.economy.vocalcoach import MAX_MB
        u = User.objects.create_user(username="statzy", password="hunter2hunter2")
        m = membership_for(u); m.tier = TIER_STATZ; m.save()
        c = APIClient(); c.force_authenticate(u)
        d = c.get("/api/singz/coach/").data
        self.assertEqual(d["max_mb"], MAX_MB)
        self.assertFalse(d["max_mb_is_tier_limit"])
