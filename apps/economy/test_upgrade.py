"""A paywall should be a door, not a wall.

Before this, sixteen of seventeen 402s answered "insufficient balance" — no
price, no tier, no way forward — at the single highest-intent moment in the
product. These tests pin the shape of the answer.
"""
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from . import catalog
from .catalog import STATZ_MONTH_CENTS, STATZ_PLANS, STATZ_YEAR_CENTS
from .models import (TIER_FREE, TIER_PREMIUM, TIER_STATZ, award_spinaz,
                     membership_for, wallet_for)
from .upgrade import payload, plans_for, spinaz_price, tier_rank

User = get_user_model()


def member(name, tier=TIER_FREE, cents=0, spinaz=0):
    u = User.objects.create_user(username=name, password="upgrade-pass-1")
    m = membership_for(u)
    m.tier = tier
    m.save(update_fields=["tier"])
    if cents:
        w = wallet_for(u)
        w.money_cents = cents
        w.save(update_fields=["money_cents"])
    if spinaz:
        award_spinaz(u, spinaz, note="test")
    return u


class TierOrderTests(TestCase):
    def test_the_ladder_is_ordered(self):
        self.assertLess(tier_rank(TIER_FREE), tier_rank(TIER_PREMIUM))
        self.assertLess(tier_rank(TIER_PREMIUM), tier_rank(TIER_STATZ))

    def test_an_unknown_tier_sorts_to_the_bottom_rather_than_crashing(self):
        self.assertEqual(tier_rank("nonsense"), 0)


class PlanTests(TestCase):
    def test_statz_has_plans_at_all(self):
        """StatZ had no purchase path — the whole top tier was unbuyable."""
        self.assertTrue(STATZ_PLANS)
        self.assertEqual(sorted(STATZ_PLANS), ["month", "year"])

    def test_the_yearly_plan_shows_what_it_saves(self):
        year = next(p for p in plans_for(TIER_STATZ) if p["plan"] == "year")
        self.assertEqual(year["saves_cents"], STATZ_MONTH_CENTS * 12 - STATZ_YEAR_CENTS)

    def test_every_plan_carries_a_spinaz_price(self):
        for tier in (TIER_PREMIUM, TIER_STATZ):
            for plan in plans_for(tier):
                self.assertEqual(plan["spinaz"], spinaz_price(plan["cents"]))


class PayloadTests(TestCase):
    def test_a_tier_gate_names_the_tier_the_price_and_the_checkout(self):
        body = payload(member("gated"), feature="Gym locations",
                       required_tier=TIER_PREMIUM)
        self.assertEqual(body["required_tier"], TIER_PREMIUM)
        self.assertTrue(body["plans"])
        self.assertIn("checkout", body)
        self.assertIn("Gym locations", body["headline"])
        self.assertIn("$", body["detail"])

    def test_it_offers_spinaz_as_an_alternative_to_a_card(self):
        body = payload(member("cardless"), feature="StatZ thing",
                       required_tier=TIER_STATZ)
        self.assertIn("SpinAZ", body["detail"])
        self.assertIn("spinaz_checkout", body)

    def test_a_member_who_already_has_the_tier_gets_no_upsell(self):
        body = payload(member("has_it", TIER_STATZ), feature="X",
                       required_tier=TIER_PREMIUM)
        self.assertNotIn("required_tier", body)
        self.assertNotIn("plans", body)

    def test_a_balance_shortfall_reports_exactly_what_is_short(self):
        body = payload(member("poor", cents=40), need_cents=100)
        self.assertEqual(body["need_cents"], 100)
        self.assertEqual(body["short_cents"], 60)

    def test_it_says_when_spinaz_would_cover_the_shortfall(self):
        rich_in_spinaz = member("spinaz_rich", cents=0, spinaz=5000)
        body = payload(rich_in_spinaz, need_cents=100)
        self.assertTrue(body["spinaz_would_cover"])

    def test_it_does_not_promise_spinaz_that_is_not_there(self):
        body = payload(member("spinaz_poor", cents=0, spinaz=1), need_cents=10_000)
        self.assertFalse(body["spinaz_would_cover"])


class SpinazMembershipTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_buying_statz_with_spinaz_grants_the_tier_and_spends_them(self):
        u = member("buyer", spinaz=spinaz_price(STATZ_MONTH_CENTS))
        self.client.force_authenticate(u)
        r = self.client.post(reverse("economy-membership-spinaz"),
                             {"tier": TIER_STATZ, "plan": "month"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(membership_for(u).tier, TIER_STATZ)
        self.assertEqual(wallet_for(u).spinaz, 0)

    def test_it_says_plainly_that_nothing_renews(self):
        u = member("buyer2", spinaz=spinaz_price(STATZ_MONTH_CENTS))
        self.client.force_authenticate(u)
        r = self.client.post(reverse("economy-membership-spinaz"),
                             {"tier": TIER_STATZ, "plan": "month"}, format="json")
        self.assertIn("doesn't auto-renew", r.json()["note"])

    def test_not_enough_spinaz_reports_the_gap_and_takes_nothing(self):
        u = member("broke_buyer", spinaz=10)
        self.client.force_authenticate(u)
        r = self.client.post(reverse("economy-membership-spinaz"),
                             {"tier": TIER_STATZ, "plan": "month"}, format="json")
        self.assertEqual(r.status_code, 402)
        self.assertEqual(r.json()["short_spinaz"],
                         spinaz_price(STATZ_MONTH_CENTS) - 10)
        self.assertEqual(wallet_for(u).spinaz, 10)

    def test_buying_a_tier_below_your_own_is_refused_not_charged(self):
        """Otherwise it silently takes SpinAZ and downgrades them."""
        u = member("already_statz", TIER_STATZ, spinaz=100_000)
        self.client.force_authenticate(u)
        r = self.client.post(reverse("economy-membership-spinaz"),
                             {"tier": TIER_PREMIUM, "plan": "month"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(wallet_for(u).spinaz, 100_000)
        self.assertEqual(membership_for(u).tier, TIER_STATZ)

    def test_the_price_list_marks_what_you_can_afford(self):
        u = member("browser", spinaz=spinaz_price(STATZ_MONTH_CENTS))
        self.client.force_authenticate(u)
        body = self.client.get(reverse("economy-membership-spinaz")).json()
        cheapest = body["options"][0]
        self.assertTrue(cheapest["affordable"])
        self.assertIn("100 SpinAZ = $1", body["rate"])


class GateResponseTests(TestCase):
    def test_the_bodiez_paywall_now_carries_a_price_and_a_checkout(self):
        u = member("free_lifter", TIER_FREE)
        client = APIClient()
        client.force_authenticate(u)
        r = client.get(reverse("bodiez-locations"))
        self.assertEqual(r.status_code, 402)
        body = r.json()
        self.assertEqual(body["required_tier"], TIER_PREMIUM)
        self.assertTrue(body["plans"], "a paywall with no price is a dead end")
        self.assertIn("checkout", body)


class PriceConsistencyTests(SimpleTestCase):
    """The founding discount is computed off a "full" StatZ price. That price
    has to be one the stack actually charges, or the discount is off a number
    nobody pays.

    This is what caught Premium being $6: the founding block says full StatZ is
    $15/mo and $120/yr, and StatZ is +$5/mo and +$40/yr on top of Premium, so
    Premium has to be $10/mo and $80/yr for those to be reachable.
    """

    def test_premium_plus_statz_is_the_full_monthly_the_founding_offer_halves(self):
        full_month = int(catalog.FOUNDING_MONTH_CENTS / (1 - catalog.FOUNDING_DISCOUNT))
        self.assertEqual(
            catalog.PREMIUM_MONTH_CENTS + catalog.STATZ_MONTH_CENTS, full_month)

    def test_premium_plus_statz_is_the_full_yearly_the_founding_offer_halves(self):
        full_year = int(catalog.FOUNDING_YEAR_CENTS / (1 - catalog.FOUNDING_DISCOUNT))
        self.assertEqual(
            catalog.PREMIUM_YEAR_CENTS + catalog.STATZ_YEAR_CENTS, full_year)

    def test_paying_yearly_is_always_cheaper_than_paying_monthly(self):
        for name, month, year in (
            ("premium", catalog.PREMIUM_MONTH_CENTS, catalog.PREMIUM_YEAR_CENTS),
            ("statz", catalog.STATZ_MONTH_CENTS, catalog.STATZ_YEAR_CENTS),
        ):
            with self.subTest(tier=name):
                self.assertLess(year, month * 12,
                                "an annual plan that costs more is a trap")
