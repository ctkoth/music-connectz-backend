from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.catalog import TIER_LIMITS, over_char_limit
from apps.economy.models import (
    TIER_FREE,
    TIER_PREMIUM,
    TIER_STATZ,
    Profile,
    SocialComment,
    membership_for,
)

User = get_user_model()

PREMIUM_CAP = TIER_LIMITS[TIER_PREMIUM]["char_limit"]   # 1,500
FREE_CAP = TIER_LIMITS[TIER_FREE]["char_limit"]         # 400


def as_tier(user, tier):
    m = membership_for(user)
    m.tier = tier
    m.save(update_fields=["tier", "updated_at"])
    return user


class OverCharLimitTests(TestCase):
    def test_fits_returns_none(self):
        self.assertIsNone(over_char_limit("x" * FREE_CAP, TIER_FREE))

    def test_over_returns_the_cap_it_broke(self):
        self.assertEqual(over_char_limit("x" * (FREE_CAP + 1), TIER_FREE), FREE_CAP)

    def test_statz_is_never_over(self):
        self.assertIsNone(over_char_limit("x" * 500_000, TIER_STATZ))

    def test_empty_and_none_are_fine(self):
        self.assertIsNone(over_char_limit("", TIER_FREE))
        self.assertIsNone(over_char_limit(None, TIER_FREE))


class BioLengthTests(TestCase):
    """Profile.bio was CharField(500) while Premium's limit is 1,500.

    On Postgres that is a DataError on write — an uncaught 500 for any Premium
    member using the room they pay for. SQLite ignores varchar length, which is
    exactly why it never showed up in the test suite.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.client.force_authenticate(self.user)

    def test_premium_can_save_a_full_length_bio(self):
        as_tier(self.user, TIER_PREMIUM)
        bio = "b" * PREMIUM_CAP
        resp = self.client.post("/api/economy/profile/", {"bio": bio}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(Profile.objects.get(user=self.user).bio, bio)

    def test_statz_bio_has_no_ceiling(self):
        as_tier(self.user, TIER_STATZ)
        bio = "b" * 20_000
        resp = self.client.post("/api/economy/profile/", {"bio": bio}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(Profile.objects.get(user=self.user).bio), 20_000)

    def test_free_is_refused_past_its_limit_and_told_the_number(self):
        as_tier(self.user, TIER_FREE)
        resp = self.client.post("/api/economy/profile/", {"bio": "b" * (FREE_CAP + 1)}, format="json")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn(str(FREE_CAP), resp.data["detail"])
        self.assertEqual(resp.data["char_limit"], FREE_CAP)

    def test_a_refused_bio_is_not_written(self):
        as_tier(self.user, TIER_FREE)
        self.client.post("/api/economy/profile/", {"bio": "keep me"}, format="json")
        self.client.post("/api/economy/profile/", {"bio": "b" * (FREE_CAP + 1)}, format="json")
        self.assertEqual(Profile.objects.get(user=self.user).bio, "keep me")

    def test_a_refused_bio_does_not_take_the_rest_of_the_profile_with_it(self):
        # The write is rejected whole — no half-saved profile.
        as_tier(self.user, TIER_FREE)
        self.client.post("/api/economy/profile/", {"display_name": "K-Oth"}, format="json")
        self.client.post(
            "/api/economy/profile/",
            {"display_name": "Changed", "bio": "b" * (FREE_CAP + 1)},
            format="json",
        )
        self.assertEqual(Profile.objects.get(user=self.user).display_name, "K-Oth")

    def test_exactly_at_the_limit_is_allowed(self):
        as_tier(self.user, TIER_FREE)
        resp = self.client.post("/api/economy/profile/", {"bio": "b" * FREE_CAP}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)


class CommentLengthTests(TestCase):
    """SocialComment.body was CharField(500) with a hardcoded [:500] truncation,
    so the tier was ignored in both directions."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.client.force_authenticate(self.user)

    def _comment(self, body):
        return self.client.post(
            "/api/economy/social/comment/", {"item": "post:1", "body": body}, format="json"
        )

    def test_premium_comment_is_not_silently_cut_at_500(self):
        as_tier(self.user, TIER_PREMIUM)
        body = "c" * 1200
        resp = self._comment(body)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(SocialComment.objects.get().body, body)

    def test_statz_comment_has_no_ceiling(self):
        as_tier(self.user, TIER_STATZ)
        resp = self._comment("c" * 12_000)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(SocialComment.objects.get().body), 12_000)

    def test_free_is_refused_past_its_limit_rather_than_truncated(self):
        as_tier(self.user, TIER_FREE)
        resp = self._comment("c" * (FREE_CAP + 1))
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn(str(FREE_CAP), resp.data["detail"])
        self.assertFalse(SocialComment.objects.exists())
