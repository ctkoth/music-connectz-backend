from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import catalog, models

User = get_user_model()


class PricingLadderTests(TestCase):
    """The two rules the ladder rests on. These are arithmetic, not taste — if
    either breaks, a tier stops making sense to buy."""

    def test_annual_is_four_months_free_at_every_tier(self):
        # One discount to explain, and the bigger commitment never gets the
        # smaller reward.
        self.assertEqual(catalog.PREMIUM_YEAR_CENTS, catalog.PREMIUM_MONTH_CENTS * 8)
        self.assertEqual(catalog.STATZ_YEAR_CENTS, catalog.STATZ_MONTH_CENTS * 8)

    def test_statz_is_a_real_step_above_premium(self):
        # StatZ buys unlimited characters, the whole AI layer, CallZ and SpecZ.
        # If it costs barely more than Premium, Premium is the tier nobody picks.
        self.assertGreaterEqual(
            catalog.STATZ_MONTH_CENTS, catalog.PREMIUM_MONTH_CENTS * 2,
            "StatZ must be at least 2x Premium or the middle tier is dead weight.")

    def test_founding_statz_never_undercuts_premium(self):
        # The half-price founding seat must still cost more than the tier below
        # it, or the first 50 members pay less for more.
        self.assertGreater(catalog.FOUNDING_MONTH_CENTS, catalog.PREMIUM_MONTH_CENTS)
        self.assertGreater(catalog.FOUNDING_YEAR_CENTS, catalog.PREMIUM_YEAR_CENTS)

    def test_founding_really_is_half(self):
        self.assertEqual(catalog.FOUNDING_MONTH_CENTS * 2, catalog.STATZ_MONTH_CENTS)
        self.assertEqual(catalog.FOUNDING_YEAR_CENTS * 2, catalog.STATZ_YEAR_CENTS)
        self.assertEqual(catalog.FOUNDING_PRICE_CENTS * 2, catalog.LIFETIME_PRICE_CENTS)

    def test_the_published_numbers(self):
        self.assertEqual(catalog.PREMIUM_MONTH_CENTS, 600)     # $6/mo
        self.assertEqual(catalog.PREMIUM_YEAR_CENTS, 4800)     # $48/yr
        self.assertEqual(catalog.STATZ_MONTH_CENTS, 1500)      # $15/mo
        self.assertEqual(catalog.STATZ_YEAR_CENTS, 12000)      # $120/yr
        self.assertEqual(catalog.LIFETIME_PRICE_CENTS, 30000)  # $300 once


class PromptAllowanceMarginTests(TestCase):
    """A tier's free prompts must not cost more than the tier charges.

    At 20/day StatZ was $18/mo of model cost against $15/mo of revenue — it
    lost money on every member who actually used what they paid for.
    """

    def _monthly_cost_cents(self, tier):
        # 30 days at the standard model's floor rate.
        return models.PROMPT_ALLOWANCE[tier] * 30 * catalog.ai_cost("standard")

    def test_statz_allowance_pays_for_itself(self):
        cost = self._monthly_cost_cents("statz")
        self.assertLess(cost, catalog.STATZ_MONTH_CENTS,
                        f"StatZ gives away ${cost / 100:.2f}/mo of AI on a "
                        f"${catalog.STATZ_MONTH_CENTS / 100:.2f}/mo plan.")

    def test_premium_allowance_pays_for_itself(self):
        cost = self._monthly_cost_cents("premium")
        self.assertLess(cost, catalog.PREMIUM_MONTH_CENTS,
                        f"Premium gives away ${cost / 100:.2f}/mo of AI on a "
                        f"${catalog.PREMIUM_MONTH_CENTS / 100:.2f}/mo plan.")

    def test_statz_still_gets_meaningfully_more_than_premium(self):
        # Trimming the allowance must not flatten the tier it belongs to.
        self.assertGreaterEqual(models.PROMPT_ALLOWANCE["statz"],
                                models.PROMPT_ALLOWANCE["premium"] * 2)

    def test_the_published_allowances(self):
        self.assertEqual(models.PROMPT_ALLOWANCE["free"], 1)
        self.assertEqual(models.PROMPT_ALLOWANCE["premium"], 5)
        self.assertEqual(models.PROMPT_ALLOWANCE["statz"], 10)


class StatZCheckoutTests(TestCase):
    """StatZ has to be buyable after the 50 founding seats are gone."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_user("k", "k@e.com", "pw12345678"))

    def test_every_statz_plan_is_sellable(self):
        # month / year / lifetime all exist and carry a Stripe mode + amount.
        for plan in ("month", "year", "lifetime"):
            cfg = catalog.STATZ_PLANS[plan]
            self.assertIn(cfg["mode"], ("subscription", "payment"))
            self.assertGreater(cfg["cents"], 0)

    def test_subscription_plans_are_recurring_and_lifetime_is_not(self):
        self.assertEqual(catalog.STATZ_PLANS["month"]["interval"], "month")
        self.assertEqual(catalog.STATZ_PLANS["year"]["interval"], "year")
        self.assertIsNone(catalog.STATZ_PLANS["lifetime"]["interval"])

    def test_unknown_plan_is_refused_by_name(self):
        resp = self.client.post("/api/economy/statz/checkout/", {"plan": "forever"})
        # 400 names the valid plans; 503 only if Stripe isn't configured, which
        # is checked first — either way it must not 404 or 500.
        self.assertIn(resp.status_code, (400, 503), resp.content)

    def test_the_route_exists(self):
        # The bug this guards: FoundingCheckoutView 409s once sold out, and
        # before this route there was nothing else selling StatZ at all.
        resp = self.client.post("/api/economy/statz/checkout/", {"plan": "month"})
        self.assertNotEqual(resp.status_code, 404, "StatZ must be buyable at full price.")
