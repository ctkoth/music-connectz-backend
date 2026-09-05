"""Rating pays, and /api/economy/earn/ is the one place that says what does."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.economy.models import (
    RATING_REWARD_DAILY_CAP,
    RATING_REWARD_ENERGY,
    AttractivenessRating,
    Face,
    ItemRating,
    Transaction,
    complete_onboarding,
    wallet_for,
)

User = get_user_model()
PW = "hunter2hunter2"


class RatingPaysTests(TestCase):
    """The working notes have said "+1 ⚡ on a rating is the reason people rate"
    from the start, and no rating view ever awarded anything."""

    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("me", "me@e.com", PW)
        self.them = User.objects.create_user("them", "t@e.com", PW)
        self.client.force_authenticate(self.me)

    def rate(self, username="them", score=8, dimension="overall"):
        return self.client.post("/api/economy/profile/rate/", {
            "target_username": username, "dimension": dimension, "score": score,
        }, format="json")

    def test_a_first_rating_pays(self):
        resp = self.rate()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["earned_energy"], RATING_REWARD_ENERGY)
        self.assertEqual(wallet_for(self.me).energy, RATING_REWARD_ENERGY)

    def test_changing_your_mind_is_free_but_not_profitable(self):
        self.rate(score=8)
        resp = self.rate(score=3)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["earned_energy"], 0)
        self.assertEqual(wallet_for(self.me).energy, RATING_REWARD_ENERGY)

    def test_each_distinct_target_pays_once(self):
        self.rate()
        other = User.objects.create_user("other", "o@e.com", PW)
        self.rate(username="other")
        self.assertEqual(wallet_for(self.me).energy, 2 * RATING_REWARD_ENERGY)
        self.assertTrue(other.pk)

    def test_the_daily_cap_stops_it_being_a_faucet(self):
        for i in range(RATING_REWARD_DAILY_CAP + 5):
            target = User.objects.create_user(f"t{i}", f"t{i}@e.com", PW)
            self.rate(username=target.username)
        self.assertEqual(wallet_for(self.me).energy,
                         RATING_REWARD_DAILY_CAP * RATING_REWARD_ENERGY)

    def test_the_attractiveness_surface_pays_too(self):
        resp = self.client.post("/api/economy/attractiveness/rate/", {
            "target_username": "them", "score": 7,
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["earned_energy"], RATING_REWARD_ENERGY)

    def test_rating_a_post_pays(self):
        self.client.post("/api/economy/social/rate/", {
            "item": "post:1", "action": "rate", "score": 9,
        }, format="json")
        self.assertEqual(wallet_for(self.me).energy, RATING_REWARD_ENERGY)
        self.assertTrue(ItemRating.objects.filter(user=self.me).exists())

    def test_it_lands_in_logz_with_the_reason(self):
        self.rate()
        row = Transaction.objects.filter(user=self.me, resource=Transaction.RES_ENERGY).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.amount, RATING_REWARD_ENERGY)
        self.assertIn("@them", row.note)

    def test_the_second_rating_of_the_same_face_pays_nothing(self):
        f = Face.objects.create(owner=self.them)
        first = self.client.post(f"/api/economy/facez/{f.pk}/rate/", {"score": 6}, format="json")
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(first.data["earned_energy"], RATING_REWARD_ENERGY)
        second = self.client.post(f"/api/economy/facez/{f.pk}/rate/", {"score": 9}, format="json")
        self.assertEqual(second.data["earned_energy"], 0)


class EarnListTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", PW)
        self.client.force_authenticate(self.user)

    def ways(self, **over):
        resp = self.client.get("/api/economy/earn/")
        self.assertEqual(resp.status_code, 200, resp.content)
        return {w["key"]: w for w in resp.data["ways"]}

    def test_every_way_states_its_gain_and_where_to_go(self):
        for key, w in self.ways().items():
            self.assertIn(w["resource"], ("spinaz", "energy"), key)
            self.assertTrue(w["tab"], key)
            self.assertTrue(w["label"], key)

    def test_the_numbers_come_from_the_constants_not_from_copy(self):
        ways = self.ways()
        self.assertEqual(ways["rating"]["gain"], RATING_REWARD_ENERGY)
        self.assertEqual(ways["referral"]["gain"], 300)
        self.assertEqual(ways["restricted"]["gain"], 300)

    @override_settings(ADMOB_APP_ID="", ADMOB_REWARDED_UNIT_ID="")
    def test_an_unconfigured_adz_is_marked_unavailable_with_a_reason(self):
        adz = self.ways()["adz"]
        self.assertFalse(adz["available"])
        self.assertIn("switched on", adz["reason"])

    @override_settings(ADMOB_APP_ID="ca-app-pub-x", ADMOB_REWARDED_UNIT_ID="unit-x")
    def test_a_configured_adz_becomes_available(self):
        self.assertTrue(self.ways()["adz"]["available"])

    @override_settings(AYET_API_KEY="key")
    def test_offerz_follows_its_own_config(self):
        self.assertTrue(self.ways()["offerz"]["available"])

    def test_the_available_list_is_never_empty_even_with_every_provider_off(self):
        # This is the whole point: a member staring at 0 🍥 must always have
        # something they can actually go and do.
        with override_settings(ADMOB_APP_ID="", ADMOB_REWARDED_UNIT_ID="",
                               AYET_API_KEY="", OFFERZ_CALLBACK_SECRET=""):
            resp = self.client.get("/api/economy/earn/")
        self.assertGreater(len(resp.data["available"]), 0)
        self.assertIn("rating", {w["key"] for w in resp.data["available"]})

    def test_onboarding_drops_off_once_claimed(self):
        self.assertTrue(self.ways()["onboard"]["available"])
        complete_onboarding(self.user)
        onboard = self.ways()["onboard"]
        self.assertFalse(onboard["available"])
        self.assertIn("claimed", onboard["reason"])

    def test_passive_energy_pays_before_anybody_has_heard_of_you(self):
        """This test used to assert the opposite, and the opposite was the bug.

        Passive Energy was reach ÷ tier with no floor, and reach is 0 until an
        external account is VERIFIED — so the one row on the earn screen that
        pays by the hour rendered greyed out, with "verify a social account" as
        its whole answer, to every member on their first day.
        """
        passive = self.ways()["passive"]
        self.assertTrue(passive["available"])
        self.assertGreater(passive["gain"], 0)
        # Still says what raises it, because the floor is a floor and reach is
        # what makes it move.
        self.assertIn("reach", passive["note"])

    def test_earned_totals_reflect_what_actually_landed(self):
        target = User.objects.create_user("t", "t@e.com", PW)
        self.client.post("/api/economy/profile/rate/",
                         {"target_username": "t", "dimension": "overall", "score": 8},
                         format="json")
        resp = self.client.get("/api/economy/earn/")
        self.assertEqual(resp.data["earned_total"]["energy"], RATING_REWARD_ENERGY)
        self.assertTrue(target.pk)
