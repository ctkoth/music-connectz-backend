"""Trials have to actually unlock things, and have to actually end.

Both halves matter. A trial that unlocks nothing is a countdown attached to
nothing; a trial that never ends is a free tier upgrade.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from . import trials
from .models import TIER_FREE, TIER_PREMIUM, TIER_STATZ, membership_for
from .suggest import may_suggest

User = get_user_model()


def member(name, tier=TIER_FREE):
    u = User.objects.create_user(username=name, password="trial-pass-1")
    m = membership_for(u)
    m.tier = tier
    m.save(update_fields=["tier"])
    return u


class EligibilityTests(TestCase):
    def test_free_members_trial_premium(self):
        self.assertEqual(trials.eligible_tier(member("f", TIER_FREE)), TIER_PREMIUM)

    def test_premium_members_trial_statz(self):
        self.assertEqual(trials.eligible_tier(member("p", TIER_PREMIUM)), TIER_STATZ)

    def test_statz_members_have_nothing_left_to_trial(self):
        self.assertIsNone(trials.eligible_tier(member("s", TIER_STATZ)))

    def test_a_free_member_cannot_skip_straight_to_a_statz_trial(self):
        ok, reason = trials.can_start(member("skipper", TIER_FREE), TIER_STATZ)
        self.assertFalse(ok)
        self.assertIn("Premium members", reason)


class LifecycleTests(TestCase):
    def test_starting_a_trial_raises_the_effective_tier(self):
        u = member("upgrader", TIER_FREE)
        self.assertEqual(trials.effective_tier(u), TIER_FREE)
        trial, err = trials.start(u)
        self.assertEqual(err, "")
        self.assertEqual(trials.effective_tier(u), TIER_PREMIUM)
        self.assertEqual(membership_for(u).tier, TIER_FREE, "the PAID tier must not change")

    def test_the_premium_trial_runs_four_hours(self):
        u = member("timed", TIER_FREE)
        trial, _ = trials.start(u)
        self.assertAlmostEqual(trial.seconds_left, 4 * 60 * 60, delta=5)

    def test_the_statz_trial_runs_four_minutes(self):
        u = member("timed_statz", TIER_PREMIUM)
        trial, _ = trials.start(u)
        self.assertAlmostEqual(trial.seconds_left, 4 * 60, delta=5)

    def test_an_expired_trial_stops_unlocking_anything(self):
        """No cleanup job — the row simply stops matching."""
        u = member("expired", TIER_FREE)
        trial, _ = trials.start(u)
        trial.expires_at = timezone.now() - timezone.timedelta(seconds=1)
        trial.save(update_fields=["expires_at"])
        self.assertIsNone(trials.active_trial(u))
        self.assertEqual(trials.effective_tier(u), TIER_FREE)

    def test_only_one_trial_a_day(self):
        u = member("greedy", TIER_FREE)
        trial, _ = trials.start(u)
        trial.expires_at = timezone.now() - timezone.timedelta(seconds=1)
        trial.save(update_fields=["expires_at"])
        again, err = trials.start(u)
        self.assertIsNone(again)
        self.assertIn("tomorrow", err)

    def test_a_trial_never_lowers_a_paid_tier(self):
        """A StatZ member with a stale Premium trial row keeps StatZ."""
        u = member("statz_member", TIER_STATZ)
        trials.Trial.objects.create(
            user=u, tier=TIER_PREMIUM, day=timezone.now().date(),
            expires_at=timezone.now() + timezone.timedelta(hours=1))
        self.assertEqual(trials.effective_tier(u), TIER_STATZ)


class WarningTests(TestCase):
    def test_the_payload_says_when_to_raise_the_banner(self):
        u = member("warned", TIER_PREMIUM)
        trial, _ = trials.start(u)
        body = trials.status(u)
        self.assertEqual(body["active"]["warn_seconds"], 15)
        self.assertFalse(body["active"]["warning"], "4 minutes out is not a warning")

        trial.expires_at = timezone.now() + timezone.timedelta(seconds=10)
        trial.save(update_fields=["expires_at"])
        self.assertTrue(trials.status(u)["active"]["warning"])

    def test_the_premium_trial_warns_fifteen_minutes_out(self):
        u = member("warned2", TIER_FREE)
        trials.start(u)
        self.assertEqual(trials.status(u)["active"]["warn_seconds"], 15 * 60)


class GateIntegrationTests(TestCase):
    """The half that makes a trial real rather than decorative."""

    def test_a_statz_trial_unlocks_suggestionz(self):
        u = member("suggest_trial", TIER_PREMIUM)
        self.assertFalse(may_suggest(u))
        trials.start(u)
        self.assertTrue(may_suggest(u), "the trial advertises SuggestionZ — it "
                                        "has to actually hand it over")

    def test_a_premium_trial_unlocks_gym_locations(self):
        u = member("locations_trial", TIER_FREE)
        client = APIClient()
        client.force_authenticate(u)
        self.assertEqual(client.get(reverse("bodiez-locations")).status_code, 402)
        trials.start(u)
        self.assertEqual(client.get(reverse("bodiez-locations")).status_code, 200)

    def test_the_lock_returns_once_the_trial_expires(self):
        u = member("relock", TIER_FREE)
        client = APIClient()
        client.force_authenticate(u)
        trial, _ = trials.start(u)
        self.assertEqual(client.get(reverse("bodiez-locations")).status_code, 200)
        trial.expires_at = timezone.now() - timezone.timedelta(seconds=1)
        trial.save(update_fields=["expires_at"])
        self.assertEqual(client.get(reverse("bodiez-locations")).status_code, 402)


class ApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_get_reports_what_is_available(self):
        self.client.force_authenticate(member("api_free", TIER_FREE))
        body = self.client.get(reverse("economy-trial")).json()
        self.assertIsNone(body["active"])
        self.assertTrue(body["available"]["can_start"])
        self.assertEqual(body["available"]["tier"], TIER_PREMIUM)

    def test_post_starts_it_and_returns_the_countdown(self):
        self.client.force_authenticate(member("api_start", TIER_FREE))
        r = self.client.post(reverse("economy-trial"), {}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["effective_tier"], TIER_PREMIUM)
        self.assertGreater(r.json()["active"]["seconds_left"], 0)

    def test_a_second_start_the_same_day_is_a_conflict_not_a_crash(self):
        self.client.force_authenticate(member("api_twice", TIER_FREE))
        self.client.post(reverse("economy-trial"), {}, format="json")
        r = self.client.post(reverse("economy-trial"), {}, format="json")
        self.assertEqual(r.status_code, 409)

    def test_the_paywall_offers_the_trial(self):
        """The moment they wanted the feature is the moment to offer it."""
        u = member("paywalled", TIER_FREE)
        self.client.force_authenticate(u)
        body = self.client.get(reverse("bodiez-locations")).json()
        self.assertEqual(body["trial"]["tier"], TIER_PREMIUM)
        self.assertTrue(body["trial"]["can_start"])
        self.assertEqual(body["trial"]["start"], "/api/economy/trial/")

    def test_the_paywall_says_when_the_trial_is_already_spent(self):
        u = member("spent", TIER_FREE)
        self.client.force_authenticate(u)
        trial, _ = trials.start(u)
        trial.expires_at = timezone.now() - timezone.timedelta(seconds=1)
        trial.save(update_fields=["expires_at"])
        body = self.client.get(reverse("bodiez-locations")).json()
        self.assertFalse(body["trial"]["can_start"])
        self.assertIn("tomorrow", body["trial"]["reason"])
