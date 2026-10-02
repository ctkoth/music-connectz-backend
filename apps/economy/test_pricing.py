from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import catalog, models

User = get_user_model()


class PricingLadderTests(TestCase):
    """The rules the ladder rests on, and Corey's published numbers."""

    def test_annual_beats_twelve_months_at_every_tier(self):
        self.assertLess(catalog.PREMIUM_YEAR_CENTS, catalog.PREMIUM_MONTH_CENTS * 12)
        self.assertLess(catalog.STATZ_YEAR_CENTS, catalog.STATZ_MONTH_CENTS * 12)

    def test_statz_costs_more_than_premium_at_every_interval(self):
        self.assertGreater(catalog.STATZ_MONTH_CENTS, catalog.PREMIUM_MONTH_CENTS)
        self.assertGreater(catalog.STATZ_YEAR_CENTS, catalog.PREMIUM_YEAR_CENTS)

    def test_founding_statz_never_undercuts_premium(self):
        # The half-price founding seat must still cost more than the tier below
        # it, or the first 50 members pay less for more.
        self.assertGreater(catalog.FOUNDING_MONTH_CENTS, catalog.PREMIUM_MONTH_CENTS)
        self.assertGreater(catalog.FOUNDING_YEAR_CENTS, catalog.PREMIUM_YEAR_CENTS)
        self.assertGreater(catalog.FOUNDING_PRICE_CENTS, catalog.PREMIUM_YEAR_CENTS)

    def test_founding_really_is_half(self):
        self.assertEqual(catalog.FOUNDING_MONTH_CENTS * 2, catalog.STATZ_MONTH_CENTS)
        self.assertEqual(catalog.FOUNDING_YEAR_CENTS * 2, catalog.STATZ_YEAR_CENTS)
        self.assertEqual(catalog.FOUNDING_PRICE_CENTS * 2, catalog.LIFETIME_PRICE_CENTS)
        self.assertEqual(set(catalog.FOUNDING_PLANS), {"lifetime", "year", "month"})

    def test_the_published_numbers(self):
        self.assertEqual(catalog.PREMIUM_MONTH_CENTS, 700)     # $7/mo
        self.assertEqual(catalog.PREMIUM_YEAR_CENTS, 6000)     # $60/yr
        self.assertEqual(catalog.STATZ_MONTH_CENTS, 1500)      # $15/mo
        self.assertEqual(catalog.STATZ_YEAR_CENTS, 15000)      # $150/yr
        self.assertEqual(catalog.LIFETIME_PRICE_CENTS, 30000)  # $300 once

    def test_the_tiers_endpoint_quotes_both_intervals(self):
        tiers = {t["key"]: t for t in APIClient().get("/api/economy/tiers/").json()["tiers"]}
        self.assertEqual((tiers["premium"]["month_cents"], tiers["premium"]["year_cents"]), (700, 6000))
        self.assertEqual((tiers["statz"]["month_cents"], tiers["statz"]["year_cents"]), (1500, 15000))
        self.assertEqual(tiers["statz"]["char_limit"], 5000)


class OwnerTierSwitchTests(TestCase):
    """Only the owner may set a tier by hand, and the choice sticks."""

    def test_a_member_cannot_make_themselves_statz(self):
        u = User.objects.create_user("m", "m@e.com", "pw-Long-enough-1")
        c = APIClient(); c.force_authenticate(u)
        r = c.post("/api/economy/membership/", {"tier": "statz"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(models.membership_for(u).tier, "free")

    def test_the_owner_defaults_to_statz_and_a_chosen_tier_survives(self):
        from django.test import override_settings
        with override_settings(OWNER_USERNAMES=["K-Oth"], OWNER_EMAILS=[]):
            u = User.objects.create_user("K-Oth", "k@e.com", "pw-Long-enough-1")
            c = APIClient(); c.force_authenticate(u)
            d = c.get("/api/economy/membership/").json()
            self.assertEqual(d["tier"], "statz")
            self.assertIn("free", d["switchable"])
            self.assertEqual(c.post("/api/economy/membership/", {"tier": "free"}, format="json").status_code, 200)
            # Every membership read runs ensure_owner; a pinned Free stays Free.
            self.assertEqual(c.get("/api/economy/membership/").json()["tier"], "free")
            self.assertEqual(c.get("/api/economy/limits/").json()["char_limit"], 400)


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
        # Free is 3, not 1: at 1 it was the same allowance the anonymous trial
        # door hands a stranger, so an account bought nothing on the axis
        # people arrive for.
        self.assertEqual(models.PROMPT_ALLOWANCE["free"], 3)
        self.assertEqual(models.PROMPT_ALLOWANCE["premium"], 5)
        self.assertEqual(models.PROMPT_ALLOWANCE["statz"], 10)

    def test_the_margin_math_above_describes_a_ladder_that_exists(self):
        """`_monthly_cost_cents` reasons at the standard model's floor rate —
        which was fiction while the allowance covered whatever the run cost.

        A StatZ member picking Fable got ten free runs a day at 15c, so the
        real figure was $45/mo against $15/mo of revenue and every margin test
        in this class was passing on a number nothing enforced.
        """
        self.assertGreaterEqual(models.DAILY_PROMPT_MAX_CENTS,
                                catalog.ai_cost("standard"))
        dearest = max(m["cost_cents"] for m in catalog.AI_MODELS.values())
        self.assertGreater(dearest, models.DAILY_PROMPT_MAX_CENTS)
        self.assertFalse(models.daily_prompt_covers(dearest))


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
