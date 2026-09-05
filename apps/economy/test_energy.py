"""Passive Energy — the rate the app has always stated, now actually paid.

`energy_rate_per_hour` shipped with reach and nothing ever credited it. The
profile published an hourly rate, the wallet never moved, and a StatZ member
with real reach sat at 0 ⚡ forever.
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import (
    ENERGY_CATCHUP_HOURS,
    TIER_FREE,
    TIER_PREMIUM,
    TIER_STATZ,
    Transaction,
    energy_rate_per_hour,
    membership_for,
    settle_energy,
    wallet_for,
)

User = get_user_model()
PW = "hunter2hunter2"

# The energy day turns at 04:20 America/New_York, so a test that says "three
# hours ago" would mean something different depending on the hour the suite
# happens to run at — inside the day before lunch, across the boundary at
# dawn. So `now` is pinned, for every test in this file, to 04:00 EDT: 23h40m
# after the boundary, which is the widest in-day window there is. Anything
# further back than that crosses the reset, which is exactly what the
# crossing tests want.
PINNED_NOW = datetime(2026, 6, 15, 8, 0, tzinfo=dt_timezone.utc)   # 04:00 EDT


def seen(user, hours_ago=0):
    """Mark a member as having been here — what `/api/auth/stats/` does."""
    from apps.economy.models import membership_for
    m = membership_for(user)
    m.last_seen = timezone.now() - timedelta(hours=hours_ago)
    m.save(update_fields=["last_seen"])
    return m


class PinnedClock:
    """Freeze `timezone.now()` for the duration of a test."""

    def setUp(self):
        super().setUp()
        real = timezone.now
        timezone.now = lambda: PINNED_NOW
        self.addCleanup(setattr, timezone, "now", real)



class SettleEnergyTests(PinnedClock, TestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user("k", "k@e.com", PW)
        # Passive Energy only accrues for somebody who has BEEN HERE, and
        # `last_seen` is stamped by the stats call these tests don't make.
        # `test_energy_daily` is where the absent case is pinned; here the
        # member is present, so the tests are about the arithmetic.
        seen(self.user)

    def rate_of(self, n):
        """Pin the hourly rate, so these tests are about the accrual and not
        about how reach happens to be sourced today."""
        import apps.economy.models as m
        orig = m.energy_rate_per_hour
        m.energy_rate_per_hour = lambda user: n
        self.addCleanup(setattr, m, "energy_rate_per_hour", orig)

    def clock_back(self, user, hours):
        w = wallet_for(user)
        w.energy_accrued_at = timezone.now() - timedelta(hours=hours, minutes=1)
        w.save(update_fields=["energy_accrued_at"])

    def test_the_first_touch_starts_the_clock_it_does_not_backpay(self):
        self.rate_of(10)
        w = settle_energy(self.user)
        self.assertEqual(w.energy, 0)
        self.assertIsNotNone(w.energy_accrued_at)

    def test_whole_hours_are_paid_at_the_rate(self):
        self.rate_of(7)
        settle_energy(self.user)
        self.clock_back(self.user, 3)
        self.assertEqual(settle_energy(self.user).energy, 21)

    def test_a_partial_hour_pays_nothing_yet_and_is_not_lost(self):
        # Someone refreshing every ten minutes must earn what a once-a-day
        # visitor earns. Rounding the remainder away on every load would mean
        # the more you use the app, the less you accrue.
        self.rate_of(6)
        settle_energy(self.user)
        w = wallet_for(self.user)
        w.energy_accrued_at = timezone.now() - timedelta(minutes=50)
        w.save(update_fields=["energy_accrued_at"])
        self.assertEqual(settle_energy(self.user).energy, 0)

        w.refresh_from_db()
        w.energy_accrued_at -= timedelta(minutes=15)     # now 65 minutes owed
        w.save(update_fields=["energy_accrued_at"])
        self.assertEqual(settle_energy(self.user).energy, 6)

    def test_settling_twice_in_a_row_does_not_pay_twice(self):
        self.rate_of(5)
        settle_energy(self.user)
        self.clock_back(self.user, 2)
        self.assertEqual(settle_energy(self.user).energy, 10)
        self.assertEqual(settle_energy(self.user).energy, 10)

    def test_being_away_a_week_pays_a_day_not_a_week(self):
        # Energy regenerates like mana. It is not a savings account.
        self.rate_of(4)
        settle_energy(self.user)
        self.clock_back(self.user, 24 * 7)
        self.assertEqual(settle_energy(self.user).energy, 4 * ENERGY_CATCHUP_HOURS)

    def test_the_clock_still_advances_past_the_cap(self):
        self.rate_of(4)
        settle_energy(self.user)
        self.clock_back(self.user, 24 * 7)
        settle_energy(self.user)
        before = wallet_for(self.user).energy
        self.assertEqual(settle_energy(self.user).energy, before)   # nothing left owed

    def test_no_reach_accrues_nothing(self):
        self.rate_of(0)
        settle_energy(self.user)
        self.clock_back(self.user, 10)
        self.assertEqual(settle_energy(self.user).energy, 0)

    def test_the_accrual_is_written_to_logz(self):
        # A balance that changed while you were away, with no line saying why,
        # reads as a bug.
        self.rate_of(3)
        settle_energy(self.user)
        self.clock_back(self.user, 2)
        settle_energy(self.user)
        row = Transaction.objects.filter(user=self.user, resource=Transaction.RES_ENERGY).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.amount, 6)
        self.assertIn("Passive Energy", row.note)

    def test_it_does_not_disturb_energy_earned_other_ways(self):
        """100 ⚡ earned by rating, with a daily cap of 48, stays 100.

        The passive top-up is a ceiling on what the platform HANDS OUT, not a
        ceiling on what somebody worked for — so above the cap it grants
        nothing and takes nothing. It used to add on top with no ceiling at
        all, which is the unbounded accrual the cap exists to end."""
        self.rate_of(2)
        settle_energy(self.user)
        w = wallet_for(self.user)
        w.energy = 100
        w.save(update_fields=["energy"])
        self.clock_back(self.user, 1)
        self.assertEqual(settle_energy(self.user).energy, 100)


class EnergyRateByTierTests(PinnedClock, TestCase):
    """Free = reach/10, Premium = reach/5, StatZ = reach/1."""

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user("r", "r@e.com", PW)
        import apps.economy.models as m
        orig = m.reach_median
        m.reach_median = lambda user: 100
        self.addCleanup(setattr, m, "reach_median", orig)

    def as_tier(self, tier):
        mem = membership_for(self.user)
        mem.tier = tier
        mem.save(update_fields=["tier", "updated_at"])

    def test_the_ladder_is_what_the_profile_advertises(self):
        self.as_tier(TIER_FREE)
        self.assertEqual(energy_rate_per_hour(self.user), 10)
        self.as_tier(TIER_PREMIUM)
        self.assertEqual(energy_rate_per_hour(self.user), 20)
        self.as_tier(TIER_STATZ)
        self.assertEqual(energy_rate_per_hour(self.user), 100)


class EnergyReachesTheClientTests(PinnedClock, TestCase):
    """Settling in the model is worthless if no endpoint calls it."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.create_user("c", "c@e.com", PW)
        self.client.force_authenticate(self.user)
        seen(self.user)
        import apps.economy.models as m
        orig = m.energy_rate_per_hour
        m.energy_rate_per_hour = lambda user: 9
        self.addCleanup(setattr, m, "energy_rate_per_hour", orig)

    def owed(self, hours):
        w = wallet_for(self.user)
        w.energy_accrued_at = timezone.now() - timedelta(hours=hours, minutes=1)
        w.save(update_fields=["energy_accrued_at"])

    def test_me_pays_it(self):
        self.client.get("/api/auth/me/")          # starts the clock
        self.owed(2)
        self.assertEqual(self.client.get("/api/auth/me/").data["energy"], 18)

    def test_the_wallet_screen_pays_it(self):
        self.client.get("/api/economy/wallet/")
        self.owed(3)
        resp = self.client.get("/api/economy/wallet/")
        self.assertEqual(resp.data["wallet"]["energy"], 27)

    def test_the_two_surfaces_agree(self):
        self.client.get("/api/auth/me/")
        self.owed(5)
        wallet = self.client.get("/api/economy/wallet/").data["wallet"]["energy"]
        me = self.client.get("/api/auth/me/").data["energy"]
        self.assertEqual(wallet, me)
