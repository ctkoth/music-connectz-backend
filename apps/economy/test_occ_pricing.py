"""What an agent run costs, and the ceiling stated before it starts.

The per-message price (2-15 🏷️) was built for ONE call. An agent run is 20-80
calls with a project in context — real cost measured in dollars, not cents. A
flat per-message price there is a promise the data doesn't support, which is the
same failure as "20 free prompts" and the 25MB coach limit.

So a run is billed on measured tokens, and the member is told a CEILING first.
These tests hold both halves: that the arithmetic is right, and that the ceiling
is a real one.
"""
from types import SimpleNamespace

from django.test import TestCase

from apps.economy.catalog import (
    AGENT_PRICE_MULTIPLIER,
    AI_MODELS,
    AI_MODEL_ORDER,
    AI_RUN_BUDGET_CENTS,
    CACHE_READ_MULTIPLIER,
    PROMPTZ_CENTS_PER_UNIT,
    ai_run_budget,
    ai_run_charge_cents,
    ai_run_cost_cents,
)
from apps.economy.models import TIER_FREE, TIER_PREMIUM, TIER_STATZ


def usage(**kw):
    base = {"input_tokens": 0, "output_tokens": 0,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    base.update(kw)
    return base


class TheRatesAreTheRealOnes(TestCase):
    def test_every_model_carries_both_token_rates(self):
        for key, spec in AI_MODELS.items():
            with self.subTest(model=key):
                self.assertGreater(spec["in_cents_mtok"], 0)
                self.assertGreater(spec["out_cents_mtok"], 0)

    def test_output_always_costs_more_than_input(self):
        # True of every Claude model, and the reason a run's cost is dominated
        # by what it WRITES. If it ever inverts, the pricing above still works
        # but the intuition behind the ceilings stops holding.
        for key, spec in AI_MODELS.items():
            with self.subTest(model=key):
                self.assertGreater(spec["out_cents_mtok"], spec["in_cents_mtok"])

    def test_the_ladder_of_prices_matches_the_ladder_of_models(self):
        # The picker renders cheapest first; if the rates disagree with that
        # order, the "cheap" rung is the expensive one — which is exactly how
        # the cheapest VOICE ended up running the priciest MODEL.
        rates = [AI_MODELS[k]["in_cents_mtok"] for k in AI_MODEL_ORDER]
        self.assertEqual(rates, sorted(rates))


class TheArithmeticIsRight(TestCase):
    def test_a_known_run_prices_correctly(self):
        # Opus 5: $5/MTok in, $25/MTok out. 1M in + 1M out = $30 = 3000 cents.
        cents = ai_run_cost_cents("opus", usage(input_tokens=1_000_000,
                                                output_tokens=1_000_000))
        self.assertEqual(cents, 3000)

    def test_cached_input_is_billed_at_a_tenth(self):
        fresh = ai_run_cost_cents("opus", usage(input_tokens=1_000_000))
        cached = ai_run_cost_cents("opus", usage(cache_read_input_tokens=1_000_000))
        self.assertEqual(cached, int(fresh * CACHE_READ_MULTIPLIER))

    def test_writing_the_cache_costs_more_than_reading_it(self):
        read = ai_run_cost_cents("opus", usage(cache_read_input_tokens=1_000_000))
        write = ai_run_cost_cents("opus", usage(cache_creation_input_tokens=1_000_000))
        self.assertGreater(write, read)

    def test_a_realistic_agent_run_lands_somewhere_sane(self):
        # Most of an agent's input is a cache read — it re-sends the project
        # every turn. Billing that at full rate would overcharge ~10x, which is
        # the whole reason the multiplier exists.
        cents = ai_run_cost_cents("opus", usage(
            input_tokens=20_000, cache_read_input_tokens=400_000,
            cache_creation_input_tokens=30_000, output_tokens=25_000))
        self.assertGreater(cents, 0)
        self.assertLess(cents, 500)   # under $5 for a substantial task

    def test_rounding_happens_once_for_the_run_not_once_per_turn(self):
        # Forty tiny turns rounded up individually would bill 40c for a run
        # that genuinely cost a fraction of one.
        one_turn = usage(input_tokens=100, output_tokens=20)
        whole_run = usage(input_tokens=100 * 40, output_tokens=20 * 40)
        self.assertEqual(ai_run_cost_cents("opus", one_turn), 1)
        self.assertLess(ai_run_cost_cents("opus", whole_run), 40)

    def test_a_run_that_used_nothing_costs_nothing(self):
        # A run that never reached the model isn't billed — the same rule
        # vocalcoach.py bills on.
        self.assertEqual(ai_run_cost_cents("opus", usage()), 0)

    def test_any_real_usage_costs_at_least_one_cent(self):
        # A free tier of tiny runs is a hole somebody drives a loop through.
        self.assertEqual(ai_run_cost_cents("haiku", usage(input_tokens=1)), 1)

    def test_the_expensive_model_costs_more_for_the_same_work(self):
        work = usage(input_tokens=500_000, output_tokens=50_000)
        prices = [ai_run_cost_cents(k, work) for k in AI_MODEL_ORDER]
        self.assertEqual(prices, sorted(prices))
        self.assertLess(prices[0], prices[-1])

    def test_a_usage_object_works_as_well_as_a_dict(self):
        # The loop passes the SDK's usage object; the tests pass dicts. Both
        # have to price the same or the tests are measuring something else.
        as_dict = usage(input_tokens=10_000, output_tokens=1_000)
        as_object = SimpleNamespace(**as_dict)
        self.assertEqual(ai_run_cost_cents("opus", as_dict),
                         ai_run_cost_cents("opus", as_object))

    def test_a_usage_object_missing_the_cache_fields_does_not_crash(self):
        # Not every response carries them.
        bare = SimpleNamespace(input_tokens=1_000, output_tokens=100)
        self.assertGreater(ai_run_cost_cents("opus", bare), 0)

    def test_an_unknown_model_falls_back_rather_than_raising(self):
        # Same rule as ai_model_for: a lapsed or renamed model must not 500.
        self.assertGreater(
            ai_run_cost_cents("no-such-model", usage(input_tokens=1_000_000)), 0)


class ARunPaysForItself(TestCase):
    """The tests that would have caught a 20% loss on every agent run.

    PromptZ sell at a 25% bonus (`PromptzBuyView`: 80c buys 100), so charging a
    run its raw cost collects 80c for every 100c owed to Anthropic. Nothing in
    the code distinguished the money owed from the money taken, so nothing could
    disagree with it.
    """

    def test_a_run_never_charges_less_than_it_cost_to_serve(self):
        work = usage(input_tokens=500_000, cache_read_input_tokens=200_000,
                     output_tokens=40_000)
        for key in AI_MODEL_ORDER:
            with self.subTest(model=key):
                self.assertGreater(ai_run_charge_cents(key, work),
                                   ai_run_cost_cents(key, work))

    def test_the_margin_actually_clears_the_promptz_bonus(self):
        # 1.25 is BREAK-EVEN, not margin: 0.8 x 1.25 = 1.0 recovers the bonus
        # and funds nothing. Anything at or below it is the bug again.
        self.assertGreater(AGENT_PRICE_MULTIPLIER, 1.25)

    def test_the_platform_takes_more_than_it_owes(self):
        # The arithmetic that matters, end to end: a member buys PromptZ at 80c
        # per 100, spends them on a run, and the platform must come out ahead of
        # what Anthropic charged.
        work = usage(input_tokens=1_000_000, output_tokens=100_000)
        cost = ai_run_cost_cents("opus", work)
        promptz_charged = ai_run_charge_cents("opus", work)
        cash_received = promptz_charged * PROMPTZ_CENTS_PER_UNIT
        self.assertGreater(cash_received, cost,
                           "the platform is paying to serve this run")

    def test_a_run_that_cost_nothing_charges_nothing(self):
        self.assertEqual(ai_run_charge_cents("opus", usage()), 0)

    def test_the_charge_is_a_whole_number_of_promptz(self):
        work = usage(input_tokens=12_345, output_tokens=678)
        charge = ai_run_charge_cents("opus", work)
        self.assertIsInstance(charge, int)
        self.assertGreaterEqual(charge, 1)

    def test_an_unknown_model_still_charges_above_cost(self):
        work = usage(input_tokens=1_000_000)
        self.assertGreater(ai_run_charge_cents("no-such-model", work),
                           ai_run_cost_cents("no-such-model", work))


class TheBonusStillWorks(TestCase):
    """The 1.25 moved out of PromptzBuyView into catalog.py. It has to still buy
    what it bought — a refactor that quietly changed a price would be worse than
    the bug it was clearing up after."""

    def test_eighty_cents_still_buys_a_hundred_promptz(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        from apps.economy.models import membership_for, wallet_for

        user = get_user_model().objects.create_user("buyer", "b@e.com", "hunter2hunter2")
        membership_for(user)
        w = wallet_for(user)
        w.money_cents = 1_000
        w.save()
        client = APIClient()
        client.force_authenticate(user)
        resp = client.post("/api/economy/promptz/buy/", {"cents": 80}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["granted"], 100)

    def test_the_named_rate_matches_what_a_promptz_costs(self):
        self.assertAlmostEqual(PROMPTZ_CENTS_PER_UNIT, 0.8)


class TheCeilingIsARealOne(TestCase):
    def test_every_tier_has_a_ceiling(self):
        for tier in (TIER_FREE, TIER_PREMIUM, TIER_STATZ):
            with self.subTest(tier=tier):
                self.assertGreater(ai_run_budget(tier)["max_cents"], 0)

    def test_the_ladder_only_goes_up(self):
        self.assertLess(AI_RUN_BUDGET_CENTS[TIER_FREE],
                        AI_RUN_BUDGET_CENTS[TIER_PREMIUM])
        self.assertLess(AI_RUN_BUDGET_CENTS[TIER_PREMIUM],
                        AI_RUN_BUDGET_CENTS[TIER_STATZ])

    def test_an_unknown_tier_gets_the_free_ceiling_not_an_error(self):
        self.assertEqual(ai_run_budget("no-such-tier")["max_cents"],
                         AI_RUN_BUDGET_CENTS[TIER_FREE])
