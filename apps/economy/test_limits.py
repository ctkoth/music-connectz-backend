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


class PublishedNumbersTests(TestCase):
    """Numbers the client had typed for itself, now served.

    Two copies of a limit is the pattern this whole module exists to end, and
    the client's copy is always the one nobody updates when the real one moves
    — so the member is shown a number the server does not honour.
    """

    def setUp(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient
        self.u = get_user_model().objects.create_user("limz", "limz@mcz.test", "pw12345!")
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def test_the_avatar_cap_is_served_and_matches_the_view_that_enforces_it(self):
        from apps.economy.catalog import AVATAR_MAX_MB
        from apps.economy.social import ProfileAvatarView
        d = self.c.get("/api/economy/limits/").data
        self.assertEqual(d["avatar_max_mb"], AVATAR_MAX_MB)
        # The screen checks this before uploading and the view refuses it
        # after. One number, or the two disagree.
        self.assertEqual(ProfileAvatarView.MAX_MB, AVATAR_MAX_MB)

    def test_the_whole_tier_ladder_is_served(self):
        from apps.economy.catalog import TIER_LIMITS
        tiers = self.c.get("/api/economy/limits/").data["tiers"]
        for t in ("free", "premium", "statz"):
            self.assertIn(t, tiers, t)
            self.assertEqual(tiers[t]["upload_mb"], TIER_LIMITS[t]["upload_mb"])
            self.assertEqual(tiers[t]["storage_mb"], TIER_LIMITS[t]["storage_mb"])

    def test_the_price_comes_from_the_same_place_stripe_charges_from(self):
        """A panel quoting a figure Stripe then charges differently is not a
        drift bug, it is a member being shown a price that is not the price.
        "$6/mo" and "$15/mo" were typed into TierUpgradePrompt.jsx."""
        from apps.economy.catalog import PREMIUM_MONTH_CENTS, STATZ_MONTH_CENTS
        tiers = self.c.get("/api/economy/limits/").data["tiers"]
        self.assertEqual(tiers["free"]["month_cents"], 0)
        self.assertEqual(tiers["premium"]["month_cents"], PREMIUM_MONTH_CENTS)
        self.assertEqual(tiers["statz"]["month_cents"], STATZ_MONTH_CENTS)

    def test_owner_god_mode_is_not_advertised(self):
        """Publishing DEBUG would sell a tier nobody can buy, with numbers that
        make every real tier look mean."""
        self.assertNotIn("debug", self.c.get("/api/economy/limits/").data["tiers"])

    def test_the_ladder_only_goes_up(self):
        """A rung that buys less than the one below it is a pricing bug the
        client would render as an upgrade."""
        tiers = self.c.get("/api/economy/limits/").data["tiers"]
        order = ["free", "premium", "statz"]
        for key in ("upload_mb", "storage_mb", "embeds_per_post"):
            vals = [tiers[t][key] for t in order]
            self.assertEqual(vals, sorted(vals), f"{key} does not increase: {vals}")
