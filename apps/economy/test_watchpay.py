"""Reading and watching, priced — and the flaw in the first version of it.

Corey's proposal was 10% of the creator's skill rate per hour to read, OR 10%
to buy it outright. The second number is the problem: if buying costs the same
as one hour of renting, nobody ever rents and the hourly path is dead the day
it ships. So renting is priced by TIME and owning is priced by the WORK'S
LENGTH, and the first test below is the one that keeps them apart.

Everything else here is the app's existing rules applied to a new surface:
a price is stated before the thing that spends it, both sides of the money are
on screen, a ladder with no ceiling is whatever the dearest person typed, and
nobody is charged for a work whose creator never asked for money.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import DirectZWork, profile_for, wallet_for
from apps.economy.watchpay import (ASSUMED_MINUTES, FREE_MINUTES,
                                   KEEP_MULTIPLIER, MAX_READ_CENTS_PER_HOUR,
                                   READER_SHARE, billable_seconds,
                                   buy_cents_for, cost_for_seconds,
                                   creator_take, credit_toward_buy,
                                   hourly_cents_for, quote)

User = get_user_model()
PW = "pw12345678"


def priced(name, rate_cents_per_hour):
    """A creator with one dated, priced skill."""
    u = User.objects.create_user(name, f"{name}@e.com", PW)
    p = profile_for(u)
    p.personas = [{"key": "producer", "name": "Producer",
                   "skills": [{"name": "Mixing", "rate_cents": rate_cents_per_hour}]}]
    p.save()
    return u


class TheRateTests(TestCase):
    def test_an_hour_of_reading_is_a_tenth_of_an_hour_of_their_labour(self):
        u = priced("mixer", 6000)                       # $60/hr skill
        self.assertEqual(hourly_cents_for(u), int(6000 * READER_SHARE))

    def test_a_rate_can_never_round_away_to_nothing(self):
        u = priced("cheap", 3)                          # 3c/hr skill → 0.3c
        self.assertEqual(hourly_cents_for(u), 1)

    def test_the_ceiling_holds_however_big_the_creator_types(self):
        """A ladder with no ceiling is whatever the dearest person typed."""
        u = priced("moon", 10_000_000)
        self.assertEqual(hourly_cents_for(u), MAX_READ_CENTS_PER_HOUR)

    def test_an_unpriced_creator_is_free_not_defaulted(self):
        """Somebody who has not asked for money is not asking for money.

        Inventing a rate on their behalf would put a paywall on their work
        that they never chose."""
        u = User.objects.create_user("quiet", "q@e.com", PW)
        self.assertEqual(hourly_cents_for(u), 0)
        self.assertFalse(quote(u, kind="reelz")["priced"])

    def test_the_cheapest_skill_prices_it_so_padding_one_moves_nothing(self):
        u = priced("many", 1000)
        p = profile_for(u)
        p.personas[0]["skills"].append({"name": "Mastering", "rate_cents": 90_000})
        p.save()
        self.assertEqual(hourly_cents_for(u), 100)      # still 10% of the cheapest


class TheMeterTests(TestCase):
    def test_ten_minutes_costs_ten_minutes_not_a_started_hour(self):
        self.assertEqual(cost_for_seconds(600, 600), 100)     # $6/hr for 10 min

    def test_rounding_up_can_cost_at_most_one_cent(self):
        self.assertEqual(cost_for_seconds(100, 1), 1)

    def test_a_free_rate_meters_nothing(self):
        self.assertEqual(cost_for_seconds(0, 99999), 0)

    def test_the_free_opening_comes_off_the_top_and_is_never_charged_later(self):
        """A free window billed after the fact is not free."""
        self.assertEqual(billable_seconds(FREE_MINUTES * 60), 0)
        self.assertEqual(billable_seconds(FREE_MINUTES * 60 + 90), 90)
        self.assertEqual(billable_seconds(10), 0)


class BuyingVersusRentingTests(TestCase):
    """The correction to the proposal, pinned.

    At a flat 10% for both, buying costs exactly one hour of renting and the
    hourly path is dead on arrival. These are the tests that stop it coming
    back."""

    def test_buying_costs_more_than_an_hour_of_renting(self):
        u = priced("film", 6000)
        hourly = hourly_cents_for(u)
        self.assertGreater(buy_cents_for(u, duration_sec=90 * 60), hourly,
                           "if buying is one hour of renting, nobody ever rents")

    def test_a_longer_work_costs_more_to_own_than_a_short_one(self):
        u = priced("both", 6000)
        short = buy_cents_for(u, duration_sec=40)              # a ReelZ
        long = buy_cents_for(u, duration_sec=110 * 60)         # a MovieZ
        self.assertGreater(long, short)

    def test_owning_is_a_full_run_times_the_keep_multiplier(self):
        u = priced("run", 6000)
        hourly = hourly_cents_for(u)
        run = cost_for_seconds(hourly, 60 * 60)
        self.assertEqual(buy_cents_for(u, duration_sec=60 * 60),
                         int(run * KEEP_MULTIPLIER))

    def test_a_work_with_no_declared_length_still_has_a_floor(self):
        u = priced("nolen", 6000)
        self.assertEqual(buy_cents_for(u, duration_sec=0),
                         buy_cents_for(u, duration_sec=ASSUMED_MINUTES * 60))

    def test_an_unpriced_creator_has_nothing_to_sell(self):
        u = User.objects.create_user("free", "f@e.com", PW)
        self.assertEqual(buy_cents_for(u, duration_sec=9999), 0)

    def test_what_you_spent_renting_comes_off_the_purchase(self):
        self.assertEqual(credit_toward_buy(300, 1000), 300)

    def test_the_credit_never_exceeds_the_price(self):
        # Renting for a week must not leave the platform owing somebody money.
        self.assertEqual(credit_toward_buy(999999, 1000), 1000)


class BothSidesOfTheMoneyTests(TestCase):
    def test_the_creator_take_and_the_platform_cut_both_come_back(self):
        take, cut = creator_take(1000, "free")
        self.assertEqual(take + cut, 1000)
        self.assertGreater(cut, 0)

    def test_a_higher_tier_keeps_more_of_it(self):
        free_take, _ = creator_take(1000, "free")
        statz_take, _ = creator_take(1000, "statz")
        self.assertGreater(statz_take, free_take)


class TheQuoteTests(TestCase):
    """The whole point: everything a reader needs BEFORE they open it."""

    def test_it_states_the_price_the_free_window_and_both_takes(self):
        u = priced("q", 6000)
        q = quote(u, kind="moviez", duration_sec=90 * 60, balance_cents=5000)
        for key in ("hourly_cents", "free_minutes", "buy_cents", "buy_now_cents",
                    "creator_hourly_cents", "platform_hourly_cents",
                    "creator_buy_cents", "platform_buy_cents", "why"):
            self.assertIn(key, q)
        self.assertTrue(q["why"], "a price with no stated reason can only be accepted")

    def test_it_says_how_long_the_balance_actually_lasts(self):
        u = priced("q2", 6000)                            # 600c/hr to read
        q = quote(u, kind="reelz", balance_cents=300)     # half an hour
        self.assertEqual(q["minutes_affordable"], 30)

    def test_a_free_work_says_why_it_is_free_rather_than_showing_a_zero(self):
        u = User.objects.create_user("q3", "q3@e.com", PW)
        q = quote(u, kind="reelz")
        self.assertFalse(q["priced"])
        self.assertIn("hasn't priced", q["why"])

    def test_the_credit_shows_up_in_what_is_left_to_pay(self):
        u = priced("q4", 6000)
        q = quote(u, kind="moviez", duration_sec=60 * 60, spent_cents=200)
        self.assertEqual(q["buy_now_cents"], q["buy_cents"] - 200)


class TheEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("reader", "r@e.com", PW)
        self.client.force_authenticate(self.me)
        self.author = priced("author", 6000)
        self.work = DirectZWork.objects.create(
            owner=self.author, fmt="moviez", title="A film", duration_sec=90 * 60)

    def test_a_quote_moves_no_money_and_starts_nothing(self):
        before = wallet_for(self.me).money
        r = self.client.get("/api/economy/watchprice/",
                            {"target": f"directz:{self.work.id}"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(wallet_for(self.me).money, before,
                         "learning a price must never be a way of paying one")

    def test_it_publishes_the_rate_the_purchase_and_the_reason(self):
        r = self.client.get("/api/economy/watchprice/",
                            {"target": f"directz:{self.work.id}"})
        self.assertGreater(r.data["hourly_cents"], 0)
        self.assertGreater(r.data["buy_cents"], r.data["hourly_cents"])
        self.assertEqual(r.data["free_minutes"], FREE_MINUTES)
        self.assertTrue(r.data["why"])
        self.assertEqual(r.data["open_in"], "directz")

    def test_your_own_work_is_never_billed_to_you(self):
        c = APIClient(); c.force_authenticate(self.author)
        r = c.get("/api/economy/watchprice/", {"target": f"directz:{self.work.id}"})
        self.assertTrue(r.data["mine"])
        self.assertFalse(r.data["priced"])

    def test_an_unpriced_kind_is_refused_and_names_what_is_priced(self):
        """A surface must not be able to start charging by being put in a URL."""
        r = self.client.get("/api/economy/watchprice/", {"target": "mangaz:1"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("priced_kinds", r.data)

    def test_a_missing_work_is_a_404_not_a_price_for_nothing(self):
        r = self.client.get("/api/economy/watchprice/", {"target": "directz:999999"})
        self.assertEqual(r.status_code, 404)
