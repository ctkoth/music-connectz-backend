from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import (SIGNIFICANT_AT, Observation, ObservationConsent,
                                 observing, record_observation)

User = get_user_model()
URL = "/api/economy/observationz/"
CONSENT = "/api/economy/observationz/consent/"


class ConsentTests(TestCase):
    """These tabs record what a member types and where they go. That is
    surveillance unless they asked for it."""

    def setUp(self):
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")

    def test_nothing_is_watched_by_default(self):
        for kind in ("habit", "code", "path", "mistake"):
            self.assertFalse(observing(self.user, kind))

    def test_nothing_is_recorded_without_consent(self):
        record_observation(self.user, "habit", "opens-postz-first")
        self.assertFalse(Observation.objects.exists())

    def test_consent_is_per_kind_not_all_or_nothing(self):
        ObservationConsent.objects.create(user=self.user, kind="habit", enabled=True)
        record_observation(self.user, "habit", "a")
        record_observation(self.user, "code", "b")
        self.assertEqual(Observation.objects.filter(kind="habit").count(), 1)
        self.assertEqual(Observation.objects.filter(kind="code").count(), 0)


class RecordingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        ObservationConsent.objects.create(user=self.user, kind="habit", enabled=True)

    def test_repeats_tally_onto_one_row(self):
        for _ in range(4):
            record_observation(self.user, "habit", "checks-logz-daily", "Checks LogZ daily")
        obs = Observation.objects.get()
        self.assertEqual(obs.count, 4)
        self.assertEqual(obs.label, "Checks LogZ daily")

    def test_a_blank_key_records_nothing(self):
        record_observation(self.user, "habit", "   ")
        self.assertFalse(Observation.objects.exists())

    def test_first_and_last_seen_both_move_correctly(self):
        record_observation(self.user, "habit", "x")
        obs = Observation.objects.get()
        first = obs.first_seen
        record_observation(self.user, "habit", "x")
        obs.refresh_from_db()
        self.assertEqual(obs.first_seen, first)
        self.assertGreaterEqual(obs.last_seen, first)


class SignificanceTests(TestCase):
    """Explainable arithmetic, not a model call. "AI-detected" would sound
    better and mean less."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.client.force_authenticate(self.user)
        ObservationConsent.objects.create(user=self.user, kind="habit", enabled=True)

    def test_twice_is_a_coincidence_not_a_habit(self):
        for _ in range(SIGNIFICANT_AT - 1):
            record_observation(self.user, "habit", "x")
        self.assertFalse(self.client.get(URL).data["observations"][0]["significant"])

    def test_enough_repeats_become_significant(self):
        for _ in range(SIGNIFICANT_AT):
            record_observation(self.user, "habit", "x")
        self.assertTrue(self.client.get(URL).data["observations"][0]["significant"])

    def test_going_cold_lowers_it_without_erasing_it(self):
        for _ in range(9):
            record_observation(self.user, "habit", "x")
        hot = self.client.get(URL).data["observations"][0]["significance"]
        Observation.objects.update(last_seen=timezone.now() - timedelta(days=200))
        cold = self.client.get(URL).data["observations"][0]["significance"]
        self.assertLess(cold, hot)
        self.assertGreater(cold, 0)


class ViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.client.force_authenticate(self.user)
        for kind in ("habit", "code"):
            ObservationConsent.objects.create(user=self.user, kind=kind, enabled=True)

    def test_most_repeated_first_and_asc_flips_it(self):
        record_observation(self.user, "habit", "rare")
        for _ in range(5):
            record_observation(self.user, "habit", "often")
        self.assertEqual(self.client.get(URL).data["observations"][0]["key"], "often")
        self.assertEqual(self.client.get(URL, {"order": "asc"}).data["observations"][0]["key"], "rare")

    def test_one_kind_at_a_time(self):
        record_observation(self.user, "habit", "h")
        record_observation(self.user, "code", "c")
        rows = self.client.get(URL, {"kind": "code"}).data["observations"]
        self.assertEqual([r["key"] for r in rows], ["c"])

    def test_dismissing_stops_it_surfacing_but_keeps_the_tally(self):
        record_observation(self.user, "habit", "x")
        self.client.post(URL, {"kind": "habit", "key": "x", "dismissed": True}, format="json")
        self.assertEqual(self.client.get(URL).data["observations"], [])
        # Kept, so it is not immediately re-learned as if new.
        self.assertTrue(Observation.objects.get(key="x").dismissed)

    def test_forget_actually_deletes(self):
        record_observation(self.user, "habit", "x")
        record_observation(self.user, "code", "c")
        resp = self.client.delete(f"{URL}?kind=habit")
        self.assertEqual(resp.data["forgotten"], 1)
        self.assertFalse(Observation.objects.filter(kind="habit").exists())
        self.assertTrue(Observation.objects.filter(kind="code").exists())

    def test_revoking_consent_forgets_what_it_collected(self):
        record_observation(self.user, "habit", "x")
        resp = self.client.post(CONSENT, {"kind": "habit", "enabled": False}, format="json")
        self.assertEqual(resp.data["forgotten"], 1)
        self.assertFalse(Observation.objects.filter(kind="habit").exists())
        self.assertFalse(observing(self.user, "habit"))

    def test_you_only_see_your_own(self):
        other = User.objects.create_user("o", "o@e.com", "pw12345678")
        ObservationConsent.objects.create(user=other, kind="habit", enabled=True)
        record_observation(other, "habit", "theirs")
        self.assertEqual(self.client.get(URL).data["observations"], [])

    def test_an_unknown_kind_is_refused_by_name(self):
        resp = self.client.post(CONSENT, {"kind": "nope", "enabled": True}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("kind must be one of", resp.data["detail"])

    def test_every_kind_carries_its_emoji_and_blurb(self):
        for k in self.client.get(CONSENT).data["kinds"]:
            self.assertTrue(k["emoji"] and k["label"] and k["blurb"], k)


class CrossPollinationTests(TestCase):
    """Corey's crux: nothing is a dead end. Something created or noticed in one
    app opens in another to edit or analyse."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.client.force_authenticate(self.user)
        ObservationConsent.objects.create(user=self.user, kind="habit", enabled=True)

    def test_an_observation_remembers_where_it_happened(self):
        record_observation(self.user, "habit", "boss-take-nightly",
                           "Records a Boss Take most nights", app_key="singz", target="singz:coach")
        row = self.client.get(URL).data["observations"][0]
        self.assertEqual(row["app_key"], "singz")
        self.assertEqual(row["open_in"], "singz")
        self.assertEqual(row["target"], "singz:coach")

    def test_a_row_with_nowhere_to_go_says_so_rather_than_guessing(self):
        record_observation(self.user, "habit", "unknown-origin")
        self.assertIsNone(self.client.get(URL).data["observations"][0]["open_in"])

    def test_the_origin_is_kept_from_the_first_sighting(self):
        record_observation(self.user, "habit", "x", app_key="rapz")
        record_observation(self.user, "habit", "x")          # later, no context
        self.assertEqual(self.client.get(URL).data["observations"][0]["app_key"], "rapz")
