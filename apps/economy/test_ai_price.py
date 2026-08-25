"""The price of an AI action, quoted before the member commits to paying it.

Every AI surface in this app charged server-side and reported `cost_cents` in
the RESPONSE. That is a bill, not a price — CLAUDE.md names it as the standing
violation of the cost/gain paradigm, and the vocal coach's GET was the one
place that got it right. These tests hold the other four to the same shape.

What they check is not "there is a number" — it is that the number is the one
the POST will actually charge, and that the two ways a quote can lie are both
closed: promising a free daily prompt to an action that can't use one, and
promising a failed run costs nothing where it does.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.ai_price import ALLOWANCE_LADDER, ai_price
from apps.economy.catalog import ai_cost, ai_model_for
from apps.economy.models import (
    PROMPT_ALLOWANCE,
    TIER_FREE,
    TIER_PREMIUM,
    TIER_STATZ,
    award_promptz,
    membership_for,
    profile_for,
    wallet_for,
)

User = get_user_model()
PW = "hunter2hunter2"

# Every AI route that charges, and whether the day's free prompts reach it.
# `daily` mirrors the `count_daily` its POST passes when it bills.
ROUTES = (
    ("/api/economy/ai/occ/", True),
    ("/api/economy/translate/", False),
    ("/api/economy/gemini/image/", False),
    ("/api/economy/gemini/video/", False),
)


def as_tier(user, tier):
    m = membership_for(user)
    m.tier = tier
    m.save(update_fields=["tier", "updated_at"])
    return user


class EveryAiRouteQuotesItself(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("quoted", "q@e.com", PW)
        self.client.force_authenticate(self.user)

    def test_get_answers_with_a_price_not_a_405(self):
        for path, _ in ROUTES:
            with self.subTest(path=path):
                r = self.client.get(path)
                self.assertEqual(r.status_code, 200)
                self.assertIsInstance(r.data.get("cost_cents"), int)

    def test_the_quote_carries_what_a_member_needs_to_decide(self):
        # A price alone doesn't answer "can I do this now" — the balance it
        # comes out of and whether today's allowance covers it are the rest of
        # the decision, and they are what the button has to render.
        for path, _ in ROUTES:
            with self.subTest(path=path):
                d = self.client.get(path).data
                for key in ("allowed", "configured", "cost_cents", "free_today",
                            "daily_covers", "daily_remaining", "daily_allowance",
                            "tier", "promptz", "money_cents", "charged_on_failure",
                            "allowance_ladder", "open_in"):
                    self.assertIn(key, d)

    def test_a_quote_is_never_anonymous_about_the_engine(self):
        # "It costs 8 🏷️" without saying what runs is how the cheapest voice
        # ended up on the priciest model without anyone noticing.
        for path, _ in ROUTES:
            with self.subTest(path=path):
                self.assertTrue(self.client.get(path).data.get("model"))

    def test_signed_out_gets_no_quote(self):
        anon = APIClient()
        for path, _ in ROUTES:
            with self.subTest(path=path):
                self.assertIn(anon.get(path).status_code, (401, 403))


class TheFreePromptIsOnlyPromisedWhereItApplies(TestCase):
    """Two ways to lie about a price, both closed.

    Image and video bill with `count_daily=False` — the models they run are
    nowhere near what the allowance is priced for. Quoting "free today" there
    would be a price the member never gets. OCC chat does spend the allowance,
    so quoting a charge there would be the same lie pointing the other way.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("allowance", "a@e.com", PW)
        self.client.force_authenticate(self.user)

    def test_each_route_says_whether_the_allowance_reaches_it(self):
        for path, daily in ROUTES:
            with self.subTest(path=path):
                self.assertIs(self.client.get(path).data["daily_covers"], daily)

    def test_a_fresh_member_with_prompts_left_is_only_free_where_it_counts(self):
        # Nothing spent today, so the allowance is intact on every route. Only
        # the route that can actually spend it may say "free".
        for path, daily in ROUTES:
            with self.subTest(path=path):
                d = self.client.get(path).data
                self.assertGreater(d["daily_remaining"], 0)
                self.assertIs(d["free_today"], daily)

    def test_a_broke_member_can_still_run_occ_on_the_allowance(self):
        # Zero balance, but a free prompt left: the one place "allowed" must
        # not follow the wallet.
        w = wallet_for(self.user)
        w.promptz, w.money_cents = 0, 0
        w.save(update_fields=["promptz", "money_cents", "updated_at"])
        with mock.patch("apps.economy.occ.anthropic_configured", return_value=True):
            self.assertTrue(self.client.get("/api/economy/ai/occ/").data["allowed"])

    def test_a_broke_member_is_told_no_on_the_routes_the_allowance_misses(self):
        w = wallet_for(self.user)
        w.promptz, w.money_cents = 0, 0
        w.save(update_fields=["promptz", "money_cents", "updated_at"])
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}):
            for path in ("/api/economy/gemini/image/", "/api/economy/gemini/video/"):
                with self.subTest(path=path):
                    d = self.client.get(path).data
                    self.assertGreater(d["daily_remaining"], 0)   # they have prompts…
                    self.assertFalse(d["allowed"])                # …that don't apply here

    def test_prepaid_promptz_buy_back_the_routes_the_allowance_misses(self):
        w = wallet_for(self.user)
        w.promptz, w.money_cents = 0, 0
        w.save(update_fields=["promptz", "money_cents", "updated_at"])
        award_promptz(self.user, ai_cost("standard") + 5)
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "k"}):
            self.assertTrue(self.client.get("/api/economy/gemini/image/").data["allowed"])


class TheQuoteMatchesTheCharge(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("matched", "m@e.com", PW)
        self.client.force_authenticate(self.user)

    def test_occ_quotes_the_engine_the_tier_actually_resolves_to(self):
        # A lapsed subscription is quoted the engine it falls BACK to, not the
        # one picked a month ago — `post` resolves the same way, so a quote
        # that skipped this would under-price the message it is standing in
        # front of.
        p = profile_for(self.user)
        p.ai_model = "fable"
        p.save(update_fields=["ai_model"])
        for tier in (TIER_FREE, TIER_PREMIUM, TIER_STATZ):
            with self.subTest(tier=tier):
                as_tier(self.user, tier)
                key, spec = ai_model_for("fable", tier)
                d = self.client.get("/api/economy/ai/occ/").data
                self.assertEqual(d["engine"], key)
                self.assertEqual(d["cost_cents"], spec["cost_cents"])

    def test_the_flat_routes_quote_the_standard_minimum(self):
        for path in ("/api/economy/translate/", "/api/economy/gemini/image/",
                     "/api/economy/gemini/video/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).data["cost_cents"], ai_cost("standard"))

    def test_an_unconfigured_backend_is_never_allowed_at_any_price(self):
        award_promptz(self.user, 10_000)
        with mock.patch.dict("os.environ", {}, clear=True):
            for path in ("/api/economy/gemini/image/", "/api/economy/gemini/video/",
                         "/api/economy/translate/", "/api/economy/ai/occ/"):
                with self.subTest(path=path):
                    d = self.client.get(path).data
                    self.assertFalse(d["configured"])
                    self.assertFalse(d["allowed"])


class WhatAFailedRunCosts(TestCase):
    """"Usually not charged" is not an answer a member can act on."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("failed", "f@e.com", PW)
        self.client.force_authenticate(self.user)

    def test_the_routes_that_bill_on_a_result_say_a_failure_is_free(self):
        for path in ("/api/economy/ai/occ/", "/api/economy/translate/",
                     "/api/economy/gemini/image/"):
            with self.subTest(path=path):
                d = self.client.get(path).data
                self.assertFalse(d["charged_on_failure"])
                self.assertEqual(d["charged_when"], "result")

    def test_veo_admits_it_charges_at_the_start(self):
        # GeminiVideoView bills the moment the operation is accepted, and
        # GeminiVideoStatusView has nothing to refund when the generation
        # later fails. The quote says so instead of implying otherwise.
        d = self.client.get("/api/economy/gemini/video/").data
        self.assertTrue(d["charged_on_failure"])
        self.assertEqual(d["charged_when"], "start")


class TheLadderIsTheUpgradePath(TestCase):
    def test_it_climbs(self):
        dailies = [row["daily"] for row in ALLOWANCE_LADDER]
        self.assertEqual(dailies, sorted(dailies))
        self.assertEqual([row["tier"] for row in ALLOWANCE_LADDER],
                         [TIER_FREE, TIER_PREMIUM, TIER_STATZ])

    def test_it_matches_the_allowance_it_advertises(self):
        for row in ALLOWANCE_LADDER:
            self.assertEqual(row["daily"], PROMPT_ALLOWANCE[row["tier"]])


class TheHelperItself(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("helper", "h@e.com", PW)

    def test_a_caller_can_override_open_in(self):
        # OCC sends a member to ModelZ to change engine, not to MembershipZ.
        self.assertEqual(ai_price(self.user, open_in="modelz")["open_in"], "modelz")
        self.assertEqual(ai_price(self.user)["open_in"], "membershipz")

    def test_a_free_action_is_allowed_with_nothing_in_the_wallet(self):
        w = wallet_for(self.user)
        w.promptz, w.money_cents = 0, 0
        w.save(update_fields=["promptz", "money_cents", "updated_at"])
        d = ai_price(self.user, cost_cents=0)
        self.assertEqual(d["cost_cents"], 0)
        self.assertTrue(d["allowed"])
        # Nothing is being spent, so no free prompt is being spent either.
        self.assertFalse(d["free_today"])
