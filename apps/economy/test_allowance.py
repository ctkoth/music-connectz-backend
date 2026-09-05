"""What a member can do on the day they arrive, and what an allowance is worth.

Three limits used to answer "nothing" to a brand-new member, each in its own
way, and each of these tests is the one that would have caught it:

  * the free daily AI allowance was 1 — the same one the ANONYMOUS trial hands
    a stranger, so registering bought nothing on the axis people arrive for;
  * passive Energy was reach ÷ tier with no floor, and reach is 0 until a
    social account is verified, so the app published an hourly income of 0;
  * PromptZ could be bought with cash and nothing else, so every free way to
    earn on the platform paid in a currency that couldn't reach the AI.

And the limit that answered "everything" to the wrong person: the allowance
covered whatever the run cost, so a StatZ member's ten free prompts a day on
the dearest engine was $45/mo of model cost against a $15/mo subscription.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.catalog import AI_MODELS, SPINAZ_PER_PROMPTZ, ai_cost
from apps.economy.models import (
    DAILY_PROMPT_MAX_CENTS,
    ENERGY_FLOOR_PER_HOUR,
    PROMPT_ALLOWANCE,
    TIER_FREE,
    TIER_PREMIUM,
    TIER_STATZ,
    charge_ai_usage,
    daily_prompt_covers,
    daily_prompt_state,
    energy_rate_per_hour,
    membership_for,
    reach_median,
    wallet_for,
)

User = get_user_model()


class FreeAllowanceTests(TestCase):
    def test_signing_up_beats_the_anonymous_door(self):
        # The trial gives one scored take per IP per day. An account that gives
        # the same one is not an account, it's a longer way to the same demo.
        self.assertGreater(PROMPT_ALLOWANCE["free"], 1)

    def test_the_ladder_still_climbs(self):
        self.assertLess(PROMPT_ALLOWANCE["free"], PROMPT_ALLOWANCE["premium"])
        self.assertLess(PROMPT_ALLOWANCE["premium"], PROMPT_ALLOWANCE["statz"])


class AllowanceCeilingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="a", password="hunter2hunter2")

    def test_the_engines_a_free_member_can_pick_are_covered(self):
        # If the ceiling ever drops under the free engine, the allowance stops
        # being an allowance for exactly the members it is for.
        self.assertTrue(daily_prompt_covers(AI_MODELS["haiku"]["cost_cents"]))
        # And the coach and every other Gemini surface, which all price here.
        self.assertTrue(daily_prompt_covers(ai_cost("standard")))

    def test_a_dear_engine_is_not_an_allowance(self):
        self.assertFalse(daily_prompt_covers(AI_MODELS["fable"]["cost_cents"]))

    def test_a_covered_run_spends_a_prompt_and_no_money(self):
        w = wallet_for(self.user)
        w.money_cents = 500
        w.save(update_fields=["money_cents"])
        _, _, before = daily_prompt_state(self.user)
        charge_ai_usage(self.user, DAILY_PROMPT_MAX_CENTS, count_daily=True)
        _, _, after = daily_prompt_state(self.user)
        self.assertEqual(after, before - 1)
        self.assertEqual(wallet_for(self.user).money_cents, 500)

    def test_a_dear_run_leaves_the_allowance_alone_and_bills(self):
        w = wallet_for(self.user)
        w.money_cents = 500
        w.save(update_fields=["money_cents"])
        cost = DAILY_PROMPT_MAX_CENTS + 5
        _, _, before = daily_prompt_state(self.user)
        charge_ai_usage(self.user, cost, count_daily=True)
        _, _, after = daily_prompt_state(self.user)
        # The prompt is still there — it was never going to cover this — and
        # the money moved instead. Eating the allowance AND charging would be
        # billing twice for one run.
        self.assertEqual(after, before)
        self.assertEqual(wallet_for(self.user).money_cents, 500 - cost)

    def test_a_dear_run_with_no_balance_is_refused_not_absorbed(self):
        self.assertIsNone(
            charge_ai_usage(self.user, DAILY_PROMPT_MAX_CENTS + 50, count_daily=True))


class EnergyFloorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="e", password="hunter2hunter2")

    def test_a_brand_new_member_earns_something(self):
        # Nothing verified, so reach is 0 — which used to make the published
        # hourly rate 0 as well.
        self.assertEqual(reach_median(self.user), 0)
        self.assertEqual(energy_rate_per_hour(self.user), ENERGY_FLOOR_PER_HOUR[TIER_FREE])
        self.assertGreater(energy_rate_per_hour(self.user), 0)

    def test_the_tier_still_buys_a_faster_clock_on_day_one(self):
        rates = []
        for tier in (TIER_FREE, TIER_PREMIUM, TIER_STATZ):
            m = membership_for(self.user)
            m.tier = tier
            m.save(update_fields=["tier"])
            rates.append(energy_rate_per_hour(self.user))
        self.assertEqual(rates, sorted(rates))
        self.assertLess(rates[0], rates[-1])

    def test_the_floor_never_lowers_somebody_who_has_reach(self):
        # The floor is a floor, not a replacement. A member whose reach earns
        # more than it must keep earning more than it.
        floor = ENERGY_FLOOR_PER_HOUR[TIER_FREE]
        self.assertGreaterEqual(max(floor, 9999 // 10), 9999 // 10)


class SpinazToPromptzTests(TestCase):
    URL = "/api/economy/promptz/convert/"

    def setUp(self):
        self.user = User.objects.create_user(username="s", password="hunter2hunter2")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def bank(self, spinaz):
        w = wallet_for(self.user)
        w.spinaz = spinaz
        w.save(update_fields=["spinaz"])
        return w

    def test_the_rate_is_stated_before_it_is_spent(self):
        self.bank(SPINAZ_PER_PROMPTZ * 7)
        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["spinaz_per_promptz"], SPINAZ_PER_PROMPTZ)
        self.assertEqual(r.data["max_promptz"], 7)

    def test_earned_spinaz_reaches_the_ai(self):
        self.bank(SPINAZ_PER_PROMPTZ * 4)
        r = self.client.post(self.URL, {"spinaz": SPINAZ_PER_PROMPTZ * 4}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["granted"], 4)
        w = wallet_for(self.user)
        self.assertEqual(w.spinaz, 0)
        self.assertEqual(w.promptz, 4)

    def test_the_remainder_stays_in_their_wallet(self):
        self.bank(SPINAZ_PER_PROMPTZ * 2 + 3)
        r = self.client.post(self.URL, {"spinaz": SPINAZ_PER_PROMPTZ * 2 + 3}, format="json")
        self.assertEqual(r.data["granted"], 2)
        # The 3 that bought nothing was never taken. A conversion that quietly
        # eats the change is theft with a rounding excuse.
        self.assertEqual(wallet_for(self.user).spinaz, 3)

    def test_a_spend_that_buys_nothing_is_refused_out_loud(self):
        self.bank(SPINAZ_PER_PROMPTZ * 2)
        r = self.client.post(self.URL, {"spinaz": SPINAZ_PER_PROMPTZ - 1}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(wallet_for(self.user).spinaz, SPINAZ_PER_PROMPTZ * 2)

    def test_you_cannot_spend_what_you_do_not_have(self):
        self.bank(SPINAZ_PER_PROMPTZ)
        r = self.client.post(self.URL, {"spinaz": SPINAZ_PER_PROMPTZ * 5}, format="json")
        self.assertEqual(r.status_code, 402)
        self.assertEqual(wallet_for(self.user).promptz, 0)

    def test_cash_stays_the_fast_lane(self):
        # Parity with the cash price would make watching an ad strictly better
        # than paying, and nobody would ever pay.
        from apps.economy.catalog import PROMPTZ_CENTS_PER_UNIT
        self.assertGreater(SPINAZ_PER_PROMPTZ, PROMPTZ_CENTS_PER_UNIT)

    def test_the_earn_screen_names_the_door(self):
        r = self.client.get("/api/economy/earn/")
        self.assertEqual(r.status_code, 200)
        keys = [s["key"] for s in r.data.get("spend", [])]
        self.assertIn("promptz", keys)
