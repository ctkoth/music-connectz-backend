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
    AI_MODELS,
    AI_MODEL_ORDER,
    AI_RUN_BUDGET_CENTS,
    CACHE_READ_MULTIPLIER,
    ai_run_budget,
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
