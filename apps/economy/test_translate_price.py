"""TranslateZ's price has to be knowable before the batch is sent.

`TranslateView` charged the model minimum server-side and reported `cost_cents`
only in the response — the "AI actions generally" violation named in CLAUDE.md.
A cost you discover by paying it is a bill, not a price. GET answers what THIS
member pays for THIS batch right now.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.catalog import ai_cost
from apps.economy.models import (
    PROMPT_ALLOWANCE,
    TIER_FREE,
    TIER_STATZ,
    award_promptz,
    membership_for,
    wallet_for,
)
from apps.economy.translate import FREE_TARGETS, MAX_TEXTS

User = get_user_model()
URL = "/api/economy/translate/"


class TranslatePriceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("t", "t@e.com", "pw12345678")
        self.client.force_authenticate(self.user)

    def get(self):
        with patch("apps.economy.translate._configured", return_value=True):
            return self.client.get(URL)

    def test_the_price_is_readable_before_sending_anything(self):
        resp = self.get()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["cost_cents"], ai_cost("standard"))
        self.assertTrue(resp.data["configured"])

    def test_one_charge_covers_the_whole_batch_and_says_so(self):
        # 60 labels cost what 1 does. Not knowing that is the difference between
        # translating a screen and translating it a string at a time.
        resp = self.get()
        self.assertTrue(resp.data["per_batch"])
        self.assertEqual(resp.data["max_texts"], MAX_TEXTS)

    def test_it_says_a_failed_batch_is_not_charged(self):
        # Stated, not just implemented — charge_ai_usage runs only after a
        # usable array parses, so a 503 costs nothing.
        self.assertFalse(self.get().data["charged_on_failure"])

    def test_it_does_not_claim_the_daily_free_prompts_cover_this(self):
        # The POST calls charge_ai_usage without count_daily, so the allowance
        # is never touched. A screen reading "free today" off a coach-shaped
        # payload would be lying, so the flags are flat no with the reason.
        m = membership_for(self.user)
        m.tier = TIER_STATZ
        m.save(update_fields=["tier", "updated_at"])
        resp = self.get()
        self.assertFalse(resp.data["free_today"])
        self.assertFalse(resp.data["uses_daily_prompt"])
        self.assertEqual(resp.data["pays_with"], ["promptz", "money"])
        # And it does not quote an allowance it cannot spend.
        self.assertNotIn("daily_remaining", resp.data)
        self.assertGreater(PROMPT_ALLOWANCE[TIER_STATZ], 0)  # the allowance exists; it just isn't this

    def test_the_balance_that_would_pay_is_on_the_price(self):
        award_promptz(self.user, 250)
        w = wallet_for(self.user)
        w.money_cents = 700
        w.save(update_fields=["money_cents", "updated_at"])
        resp = self.get()
        self.assertEqual(resp.data["promptz"], 250)
        self.assertEqual(resp.data["money_cents"], 700)

    def test_a_broke_member_is_told_before_pressing_it_not_after(self):
        # This was a 402 discovered at the end of a batch.
        w = wallet_for(self.user)
        w.promptz = 0
        w.money_cents = 0
        w.save(update_fields=["promptz", "money_cents", "updated_at"])
        resp = self.get()
        self.assertFalse(resp.data["allowed"])
        # ...and somewhere to go about it, rather than a dead end.
        self.assertEqual(resp.data["open_in"], "membershipz")

    def test_a_free_member_is_not_gated_out(self):
        m = membership_for(self.user)
        m.tier = TIER_FREE
        m.save(update_fields=["tier", "updated_at"])
        award_promptz(self.user, 500)
        resp = self.get()
        self.assertFalse(resp.data["gated"])
        self.assertIsNone(resp.data["required_tier"])
        self.assertTrue(resp.data["allowed"])

    def test_an_unconfigured_backend_is_visible_up_front(self):
        # The 503 used to arrive after the member committed to the batch.
        with patch("apps.economy.translate._configured", return_value=False):
            resp = self.client.get(URL)
        self.assertFalse(resp.data["configured"])
        self.assertFalse(resp.data["allowed"])

    def test_the_free_target_it_advertises_is_the_one_the_post_honours(self):
        # GET says English is free; POST must actually charge nothing for it,
        # or the price is advertising something the endpoint doesn't do.
        self.assertIn("en", self.get().data["free_targets"])
        for lang in FREE_TARGETS:
            resp = self.client.post(URL, {"texts": ["hello"], "target_lang": lang}, format="json")
            self.assertEqual(resp.status_code, 200, resp.content)
            self.assertEqual(resp.data["cost_cents"], 0)

    def test_the_price_needs_an_account(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(URL).status_code, 401)
