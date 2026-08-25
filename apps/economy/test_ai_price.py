"""The price of an AI action, stated before the action.

`CLAUDE.md`'s first rule, applied to the surfaces that were breaking it: image
generation, video generation and transcreation all charged server-side and
reported `cost_cents` in the response, which is a bill, not a price.

The test that matters most here is not "does GET return a number". It is
`test_free_today_is_false_where_the_allowance_does_not_apply`: the coach's price
shape says "Free today" because the coach spends a daily prompt
(`count_daily=True`), and these three do not. A quote that inherits the coach's
answer without that distinction promises a free run and then charges for it —
worse than saying nothing, because the member checked first.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.ai_price import ai_price
from apps.economy.catalog import ai_cost
from apps.economy.models import (
    TIER_STATZ,
    charge_ai_usage,
    daily_prompt_state,
    membership_for,
    wallet_for,
)

User = get_user_model()
PW = "hunter2hunter2"

IMAGE = "/api/economy/gemini/image/"
VIDEO = "/api/economy/gemini/video/"
TRANSLATE = "/api/economy/translate/"


class Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("pricer", "p@e.com", PW)
        membership_for(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def fund(self, money_cents=0, promptz=0):
        w = wallet_for(self.user)
        w.money_cents = money_cents
        w.promptz = promptz
        w.save(update_fields=["money_cents", "promptz", "updated_at"])
        return w


class PriceIsStatedBeforeTheAction(Base):
    """Every one of these used to answer only after the charge."""

    def test_all_three_quote_a_price_on_get(self):
        self.fund(money_cents=5000)
        for url in (IMAGE, VIDEO, TRANSLATE):
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.data["cost_cents"], ai_cost("standard"))
                self.assertIn("pays_from", r.data)
                self.assertIn("charged_on_failure", r.data)

    def test_a_quote_needs_no_body(self):
        """The POST requires a prompt. Asking the price must not require one —
        a price you have to compose the request to learn is still a bill."""
        self.fund(money_cents=5000)
        for url in (IMAGE, VIDEO, TRANSLATE):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_quoting_charges_nothing(self):
        self.fund(money_cents=5000, promptz=100)
        for url in (IMAGE, VIDEO, TRANSLATE):
            self.client.get(url)
        w = wallet_for(self.user)
        self.assertEqual(w.money_cents, 5000)
        self.assertEqual(w.promptz, 100)
        self.assertEqual(daily_prompt_state(self.user)[2], 1)

    def test_a_quote_needs_an_account(self):
        anon = APIClient()
        for url in (IMAGE, VIDEO, TRANSLATE):
            with self.subTest(url=url):
                self.assertIn(anon.get(url).status_code, (401, 403))


class TheAllowanceOnlyCoversWhatItCovers(Base):
    """The one that would have shipped a lie."""

    def test_free_today_is_false_where_the_allowance_does_not_apply(self):
        # A fresh member has their whole daily allowance untouched...
        self.fund(money_cents=5000)
        allowance, _used, left = daily_prompt_state(self.user)
        self.assertGreater(left, 0)
        # ...and none of it covers these three, because none of them charge
        # with count_daily=True.
        for url in (IMAGE, VIDEO, TRANSLATE):
            with self.subTest(url=url):
                d = self.client.get(url).data
                self.assertFalse(d["free_today"])
                self.assertFalse(d["uses_daily_allowance"])
                self.assertNotEqual(d["pays_from"], "free_today")

    def test_the_remaining_allowance_is_still_reported(self):
        """"You have prompts left, they don't cover this" is the answer. Hiding
        the count lets the member assume the opposite."""
        self.fund(money_cents=5000)
        d = self.client.get(IMAGE).data
        self.assertEqual(d["daily_remaining"], daily_prompt_state(self.user)[2])
        self.assertEqual(d["daily_allowance"], daily_prompt_state(self.user)[0])

    def test_no_allowance_ladder_where_the_allowance_buys_nothing(self):
        """A tier up buys more free prompts. On an action free prompts don't
        cover, printing the ladder is an upsell for a benefit that won't apply."""
        self.fund(money_cents=5000)
        for url in (IMAGE, VIDEO, TRANSLATE):
            with self.subTest(url=url):
                self.assertNotIn("allowance_ladder", self.client.get(url).data)

    def test_the_ladder_is_there_when_the_allowance_is_what_pays(self):
        d = ai_price(self.user, configured=True, uses_allowance=True,
                     charged_on_failure=False)
        self.assertTrue(d["free_today"])
        self.assertEqual(d["pays_from"], "free_today")
        self.assertTrue(d["allowance_ladder"])

    def test_the_quote_matches_what_the_charge_actually_does(self):
        """The quote and the charge read the same rule from opposite ends: a
        run billed without count_daily must not have been quoted as free."""
        self.fund(money_cents=5000)
        quoted_free = self.client.get(IMAGE).data["free_today"]
        before = daily_prompt_state(self.user)[2]
        charge_ai_usage(self.user, ai_cost("standard"), note="Image ConnectZ (Gemini)")
        spent_a_free_prompt = daily_prompt_state(self.user)[2] < before
        self.assertEqual(quoted_free, spent_a_free_prompt)
        self.assertFalse(spent_a_free_prompt)


class WhereTheMoneyComesFrom(Base):
    def test_promptz_first_then_cash(self):
        cost = ai_cost("standard")
        self.fund(money_cents=0, promptz=cost)
        self.assertEqual(self.client.get(IMAGE).data["pays_from"], "promptz")
        self.fund(money_cents=500, promptz=0)
        self.assertEqual(self.client.get(IMAGE).data["pays_from"], "balance")
        self.fund(money_cents=500, promptz=1)
        self.assertEqual(self.client.get(IMAGE).data["pays_from"], "mixed")

    def test_short_is_said_before_the_402_not_by_it(self):
        self.fund(money_cents=0, promptz=0)
        d = self.client.get(IMAGE).data
        self.assertEqual(d["pays_from"], "short")
        self.assertFalse(d["allowed"])

    def test_allowed_needs_the_backend_as_well_as_the_balance(self):
        self.fund(money_cents=5000)
        with patch("apps.economy.gemini._key", return_value=""):
            d = self.client.get(IMAGE).data
        self.assertFalse(d["configured"])
        self.assertFalse(d["allowed"])
        # Unavailable is not free — the price still reads as a price.
        self.assertEqual(d["cost_cents"], ai_cost("standard"))


class WhetherAFailedRunIsCharged(Base):
    """"If an action can fail, say whether a failed attempt is charged." Two of
    these three don't charge and one does; the honest part is the one that does."""

    def test_image_and_translate_are_not_charged_on_failure(self):
        self.fund(money_cents=5000)
        for url in (IMAGE, TRANSLATE):
            with self.subTest(url=url):
                d = self.client.get(url).data
                self.assertFalse(d["charged_on_failure"])
                self.assertTrue(d["charged_on_failure_note"])

    def test_video_says_a_failed_run_is_charged(self):
        """Veo is billed when it accepts the job, and the generation runs long
        after this endpoint returns. `GeminiVideoStatusView` has no refund, so
        answering "no" here to match the image would be false."""
        self.fund(money_cents=5000)
        d = self.client.get(VIDEO).data
        self.assertTrue(d["charged_on_failure"])
        self.assertTrue(d["charged_on_failure_note"])


class TranslateIsPricedPerBatch(Base):
    def test_the_unit_is_the_batch_not_the_string(self):
        self.fund(money_cents=5000)
        d = self.client.get(TRANSLATE).data
        self.assertEqual(d["unit"], "batch")
        self.assertGreater(d["max_texts"], 1)

    def test_english_is_named_as_the_free_no_op(self):
        self.fund(money_cents=5000)
        self.assertIn("en", self.client.get(TRANSLATE).data["free_langs"])


class TheQuoteFollowsTheMember(Base):
    def test_tier_is_reported_so_copy_never_hardcodes_one(self):
        self.fund(money_cents=5000)
        m = membership_for(self.user)
        m.tier = TIER_STATZ
        m.save(update_fields=["tier", "updated_at"])
        self.assertEqual(self.client.get(IMAGE).data["tier"], TIER_STATZ)

    def test_the_quote_points_somewhere(self):
        """Cross-pollination: a member told they're short needs the screen that
        fixes it, not just the bad news."""
        self.fund(money_cents=0, promptz=0)
        self.assertEqual(self.client.get(IMAGE).data["open_in"], "membershipz")
