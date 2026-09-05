"""Energy is a daily refill now, not a balance that piles up.

The constant said it all along — "it regenerates like mana, it is not a savings
account" — and the code did the opposite: passive Energy accrued every hour
forever with no ceiling. A member who left a tab open for a month came back to
thousands, and nothing on the platform costs enough to spend that on. An
unbounded resource stops being a resource.

Three rules, and the third is the one that protects members rather than the
economy: the cap never TAKES anything. Energy earned by rating, QuestZ, shares
or OnboardZ sits above the ceiling untouched.
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.economy.models import (ENERGY_ACTIVE_WINDOW_HOURS, ENERGY_DAILY_HOURS,
                                 ENERGY_FLOOR_PER_HOUR, TIER_FREE, TIER_STATZ,
                                 award_energy, energy_daily_cap,
                                 energy_rate_per_hour, membership_for,
                                 settle_energy, wallet_for)

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


class PinnedClock:
    """Freeze `timezone.now()` for the duration of a test."""

    def setUp(self):
        super().setUp()
        real = timezone.now
        timezone.now = lambda: PINNED_NOW
        self.addCleanup(setattr, timezone, "now", real)



def seen(user, hours_ago=0):
    m = membership_for(user)
    m.last_seen = timezone.now() - timedelta(hours=hours_ago)
    m.save(update_fields=["last_seen"])
    return m


def clock_back(user, hours):
    w = wallet_for(user)
    w.energy_accrued_at = timezone.now() - timedelta(hours=hours)
    w.save(update_fields=["energy_accrued_at"])
    return w


class TheCapTests(PinnedClock, TestCase):
    def setUp(self):
        self.user = User.objects.create_user("e", "e@e.com", PW)
        seen(self.user)

    def test_the_cap_is_a_day_of_the_member_s_own_rate(self):
        # Tiered without a second table to keep in sync — it is the rate, times
        # a day, so a tier change moves both together.
        self.assertEqual(energy_daily_cap(self.user),
                         energy_rate_per_hour(self.user) * ENERGY_DAILY_HOURS)

    def test_a_higher_tier_has_a_higher_ceiling(self):
        free = energy_daily_cap(self.user)
        m = membership_for(self.user); m.tier = TIER_STATZ; m.save(update_fields=["tier"])
        self.assertGreater(energy_daily_cap(self.user), free)

    def test_passive_energy_stops_at_the_ceiling(self):
        # A month away used to pay a month. Now a day of not spending is a full
        # tank, never a bigger one.
        clock_back(self.user, 24 * 30)
        settle_energy(self.user)
        self.assertLessEqual(wallet_for(self.user).energy, energy_daily_cap(self.user))

    def test_it_still_tops_up_from_empty(self):
        clock_back(self.user, 10)
        settle_energy(self.user)
        self.assertGreater(wallet_for(self.user).energy, 0)

    def test_a_full_tank_gains_nothing_more(self):
        w = wallet_for(self.user)
        w.energy = energy_daily_cap(self.user)
        w.save(update_fields=["energy"])
        clock_back(self.user, 12)
        settle_energy(self.user)
        self.assertEqual(wallet_for(self.user).energy, energy_daily_cap(self.user))

    def test_spending_makes_room_and_it_refills(self):
        w = wallet_for(self.user)
        w.energy = energy_daily_cap(self.user)
        w.save(update_fields=["energy"])
        w.energy -= 20
        w.save(update_fields=["energy"])
        clock_back(self.user, 24)
        settle_energy(self.user)
        self.assertEqual(wallet_for(self.user).energy, energy_daily_cap(self.user))


class ItNeverTakesTests(PinnedClock, TestCase):
    """The cap is a ceiling on what the platform HANDS OUT, not on what a
    member worked for."""

    def setUp(self):
        self.user = User.objects.create_user("w", "w@e.com", PW)
        seen(self.user)

    def test_earned_energy_above_the_cap_survives(self):
        cap = energy_daily_cap(self.user)
        award_energy(self.user, cap + 500, "QuestZ: earned the hard way")
        clock_back(self.user, 48)
        settle_energy(self.user)
        # Every point of it. Wiping this would be a retroactive shrink of the
        # one resource members are told to go and earn.
        self.assertEqual(wallet_for(self.user).energy, cap + 500)

    def test_settling_never_returns_less_than_it_started_with(self):
        for start in (0, 5, 50, 5000):
            w = wallet_for(self.user)
            w.energy = start
            w.save(update_fields=["energy"])
            clock_back(self.user, 6)
            settle_energy(self.user)
            self.assertGreaterEqual(wallet_for(self.user).energy, start)


class ActiveOnlyTests(PinnedClock, TestCase):
    def setUp(self):
        self.user = User.objects.create_user("a", "a@e.com", PW)

    def test_an_absent_member_accrues_nothing(self):
        # Passive income paid to somebody who left rewards absence, and pays
        # the accounts most likely to be abandoned.
        seen(self.user, hours_ago=ENERGY_ACTIVE_WINDOW_HOURS + 24)
        clock_back(self.user, 24)
        settle_energy(self.user)
        self.assertEqual(wallet_for(self.user).energy, 0)

    def test_the_clock_still_moves_while_they_are_away(self):
        # Otherwise the hours bank silently and pay out the moment they return,
        # which is the behaviour this replaces.
        seen(self.user, hours_ago=ENERGY_ACTIVE_WINDOW_HOURS + 24)
        clock_back(self.user, 100)
        settle_energy(self.user)
        w = wallet_for(self.user)
        self.assertLess((timezone.now() - w.energy_accrued_at).total_seconds(), 3700)

    def test_coming_back_starts_it_again(self):
        seen(self.user, hours_ago=ENERGY_ACTIVE_WINDOW_HOURS + 24)
        clock_back(self.user, 24)
        settle_energy(self.user)
        self.assertEqual(wallet_for(self.user).energy, 0)

        seen(self.user, hours_ago=0)          # they open the app
        clock_back(self.user, 10)
        settle_energy(self.user)
        self.assertGreater(wallet_for(self.user).energy, 0)

    def test_a_member_who_has_never_been_seen_accrues_nothing(self):
        m = membership_for(self.user)
        m.last_seen = None
        m.save(update_fields=["last_seen"])
        clock_back(self.user, 24)
        settle_energy(self.user)
        self.assertEqual(wallet_for(self.user).energy, 0)


class TrialClaimOnSignInTests(PinnedClock, TestCase):
    """`claim_trial_take` had one caller: REGISTER. So a stranger who made an
    account kept their take and a member who signed in lost it — backwards on
    the path most likely to happen, because the people most likely to follow a
    shared /try link are the ones who already have an account."""

    def setUp(self):
        from rest_framework.test import APIClient
        self.user = User.objects.create_user("c", "c@e.com", PW)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def make_take(self, token="tok123"):
        from apps.economy.models import TrialTake
        return TrialTake.objects.create(token=token, app_key="singz",
                                        result={"score": 7})

    def test_signing_in_claims_the_take(self):
        take = self.make_take()
        r = self.client.post("/api/economy/trial/claim/", {"token": "tok123"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.data["claimed"])
        take.refresh_from_db()
        self.assertEqual(take.claimed_by_id, self.user.id)

    def test_it_says_where_to_take_it(self):
        self.make_take()
        r = self.client.post("/api/economy/trial/claim/", {"token": "tok123"}, format="json")
        self.assertEqual(r.data["open_in"], "singz:coach")

    def test_an_already_claimed_token_is_a_quiet_no(self):
        # The client fires this on every sign-in with a pending token and most
        # are already claimed. A red error on a routine no-op teaches people to
        # ignore errors.
        self.make_take()
        self.client.post("/api/economy/trial/claim/", {"token": "tok123"}, format="json")
        r = self.client.post("/api/economy/trial/claim/", {"token": "tok123"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["claimed"])

    def test_a_junk_token_never_errors(self):
        r = self.client.post("/api/economy/trial/claim/", {"token": "nope"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["claimed"])

    def test_it_needs_a_signed_in_member(self):
        from rest_framework.test import APIClient
        self.assertEqual(APIClient().post("/api/economy/trial/claim/",
                                          {"token": "tok123"}, format="json").status_code, 401)


class ResetsAt420EasternTests(TestCase):
    """The day turns at 04:20 America/New_York, for everybody, everywhere.

    A rolling 24-hour window gives every member a different reset, so "when
    does my ⚡ come back" has a different answer for each of them and no screen
    can print it. One wall-clock moment is a fact the app can state.
    """

    def at(self, iso):
        from django.utils import timezone as tz
        real = tz.now
        when = datetime.fromisoformat(iso)
        tz.now = lambda: when
        self.addCleanup(setattr, tz, "now", real)
        return when

    def test_the_boundary_is_0420_new_york_not_utc_midnight(self):
        from zoneinfo import ZoneInfo
        from apps.economy.models import energy_day_start
        ny = ZoneInfo("America/New_York")
        start = energy_day_start(datetime(2026, 6, 15, 18, 0, tzinfo=dt_timezone.utc))
        self.assertEqual(start.astimezone(ny).hour, 4)
        self.assertEqual(start.astimezone(ny).minute, 20)

    def test_just_before_0420_the_day_still_belongs_to_yesterday(self):
        from zoneinfo import ZoneInfo
        from apps.economy.models import energy_day_start
        ny = ZoneInfo("America/New_York")
        # 04:19 EDT on the 15th → the current energy day began on the 14th.
        just_before = datetime(2026, 6, 15, 8, 19, tzinfo=dt_timezone.utc)
        self.assertEqual(energy_day_start(just_before).astimezone(ny).day, 14)
        # One minute later, it is the 15th's day.
        just_after = datetime(2026, 6, 15, 8, 21, tzinfo=dt_timezone.utc)
        self.assertEqual(energy_day_start(just_after).astimezone(ny).day, 15)

    def test_it_stays_at_0420_local_through_a_daylight_saving_change(self):
        """A fixed -05:00 offset would make this 03:20 or 05:20 half the year.

        Which half depends on the season, so the bug would ship in spring and
        be reported in November by somebody who could not describe it."""
        from zoneinfo import ZoneInfo
        from apps.economy.models import energy_day_start, energy_next_reset
        ny = ZoneInfo("America/New_York")
        for when in (datetime(2026, 1, 15, 18, 0, tzinfo=dt_timezone.utc),    # EST
                     datetime(2026, 7, 15, 18, 0, tzinfo=dt_timezone.utc),    # EDT
                     datetime(2026, 3, 8, 18, 0, tzinfo=dt_timezone.utc)):    # the switch
            for moment in (energy_day_start(when), energy_next_reset(when)):
                local = moment.astimezone(ny)
                self.assertEqual((local.hour, local.minute), (4, 20), when)

    def test_the_next_reset_is_always_ahead_of_now(self):
        from apps.economy.models import energy_next_reset
        for when in (datetime(2026, 6, 15, 8, 19, tzinfo=dt_timezone.utc),
                     datetime(2026, 6, 15, 8, 21, tzinfo=dt_timezone.utc),
                     datetime(2026, 6, 15, 23, 59, tzinfo=dt_timezone.utc)):
            self.assertGreater(energy_next_reset(when), when)

    def test_crossing_the_reset_fills_the_tank_it_does_not_drip(self):
        """"Your ⚡ comes back at 4:20 Eastern" has to be true at 4:21.

        A member who spent everything yesterday and opens the app just after
        the boundary gets the day's ceiling, not one hour of it."""
        u = User.objects.create_user("dawn", "dawn@e.com", PW)
        rate = energy_rate_per_hour(u)
        cap = energy_daily_cap(u)
        self.at("2026-06-15T08:21:00+00:00")            # 04:21 EDT — just after
        seen(u)
        w = wallet_for(u)
        w.energy = 0
        w.energy_accrued_at = datetime(2026, 6, 15, 6, 0, tzinfo=dt_timezone.utc)  # 02:00 EDT
        w.save(update_fields=["energy", "energy_accrued_at"])
        self.assertEqual(settle_energy(u).energy, cap)
        self.assertGreater(cap, rate, "a reset that pays one hour is not a reset")

    def test_inside_a_day_it_is_still_the_hourly_rate(self):
        u = User.objects.create_user("noon", "noon@e.com", PW)
        rate = energy_rate_per_hour(u)
        self.at("2026-06-15T16:00:00+00:00")            # 12:00 EDT
        seen(u)
        w = wallet_for(u)
        w.energy = 0
        w.energy_accrued_at = datetime(2026, 6, 15, 13, 0, tzinfo=dt_timezone.utc)  # 3h earlier
        w.save(update_fields=["energy", "energy_accrued_at"])
        self.assertEqual(settle_energy(u).energy, min(rate * 3, energy_daily_cap(u)))

    def test_a_week_away_is_one_day_back_not_a_weeks_catch_up(self):
        u = User.objects.create_user("gone", "gone@e.com", PW)
        self.at("2026-06-15T16:00:00+00:00")
        seen(u)
        w = wallet_for(u)
        w.energy = 0
        w.energy_accrued_at = datetime(2026, 6, 8, 16, 0, tzinfo=dt_timezone.utc)
        w.save(update_fields=["energy", "energy_accrued_at"])
        self.assertEqual(settle_energy(u).energy, energy_daily_cap(u))

    def test_the_reset_still_never_takes_earned_energy(self):
        u = User.objects.create_user("rich", "rich@e.com", PW)
        self.at("2026-06-15T08:21:00+00:00")
        seen(u)
        over = energy_daily_cap(u) * 5
        w = wallet_for(u)
        w.energy = over
        w.energy_accrued_at = datetime(2026, 6, 14, 20, 0, tzinfo=dt_timezone.utc)
        w.save(update_fields=["energy", "energy_accrued_at"])
        self.assertEqual(settle_energy(u).energy, over)

    def test_an_absent_member_is_not_paid_by_the_reset_either(self):
        """The reset is generous; it is not a reason to pay people who left."""
        u = User.objects.create_user("gone2", "gone2@e.com", PW)
        self.at("2026-06-15T08:21:00+00:00")
        m = membership_for(u)
        m.last_seen = datetime(2026, 5, 1, tzinfo=dt_timezone.utc)
        m.save(update_fields=["last_seen"])
        w = wallet_for(u)
        w.energy = 0
        w.energy_accrued_at = datetime(2026, 6, 14, 20, 0, tzinfo=dt_timezone.utc)
        w.save(update_fields=["energy", "energy_accrued_at"])
        self.assertEqual(settle_energy(u).energy, 0)
