"""BodieZ's trial door — same table, same rate limits SingZ/RapZ already use,
new arithmetic instead of a model call. See bodiez_trial.py's docstring.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.economy.models import BodieZExercise, BodieZRoutine, TrialTake, claim_trial_take

TRIAL = "/api/economy/bodiez/trial/"
User = get_user_model()


class BodieZTrialAvailabilityTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_it_opens_logged_out(self):
        r = self.client.get(TRIAL)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["available"])
        self.assertFalse(r.data["already_used"])
        self.assertTrue(r.data["free"])

    def test_it_publishes_the_real_library_not_a_trimmed_one(self):
        r = self.client.get(TRIAL)
        keys = {e["id"] for e in r.data["exercises"]}
        self.assertEqual(keys, set(BodieZExercise.objects.values_list("id", flat=True)))
        self.assertGreater(len(keys), 0)

    def test_it_publishes_a_real_statz_price_not_a_typed_one(self):
        from apps.economy.catalog import tier_ladder
        from apps.economy.models import TIER_STATZ
        r = self.client.get(TRIAL)
        self.assertEqual(r.data["upgrade"]["month_cents"], tier_ladder()[TIER_STATZ]["month_cents"])


class BodieZTrialScoringTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.ex = BodieZExercise.objects.first()
        self.assertIsNotNone(self.ex, "expected the seed migration to have run")

    def _post(self, **body):
        return self.client.post(TRIAL, {"anon_id": "anon-1", **body}, format="multipart")

    def test_a_weighted_set_gets_a_real_epley_estimate(self):
        r = self._post(exercise_id=self.ex.id, reps=8, weight_kg=60)
        self.assertEqual(r.status_code, 201)
        # Epley: 60 * (1 + 8/30) = 76.0
        self.assertAlmostEqual(r.data["estimated_1rm_kg"], 76.0, places=1)
        self.assertIsNotNone(r.data["claim_token"])
        self.assertEqual(r.data["open_in"], "bodiez:scheduler")

    def test_a_bodyweight_set_gets_no_fabricated_number(self):
        r = self._post(exercise_id=self.ex.id, reps=12)
        self.assertEqual(r.status_code, 201)
        self.assertIsNone(r.data["estimated_1rm_kg"])

    def test_it_writes_a_trialtake_row_reusing_the_shared_table(self):
        self._post(exercise_id=self.ex.id, reps=5, weight_kg=40)
        take = TrialTake.objects.get(anon_id="anon-1")
        self.assertEqual(take.app_key, "bodiez")
        self.assertTrue(take.scored)

    def test_bad_exercise_id_refuses_cleanly(self):
        r = self._post(exercise_id=999999, reps=5)
        self.assertEqual(r.status_code, 400)

    def test_zero_reps_refuses(self):
        r = self._post(exercise_id=self.ex.id, reps=0)
        self.assertEqual(r.status_code, 400)

    def test_it_samples_the_real_coach_not_an_invented_verdict(self):
        # One set can't compare two sessions, so this must be Coach's own
        # `not_enough_data` state, read from REC_LABELS, never a fabricated
        # recommendation.
        from apps.economy.bodiez import REC_LABELS
        r = self._post(exercise_id=self.ex.id, reps=8, weight_kg=60)
        self.assertEqual(r.data["coach_sample"]["recommendation"], "not_enough_data")
        self.assertEqual(r.data["coach_sample"]["label"], REC_LABELS["not_enough_data"])

    def test_it_offers_the_statz_upgrade_on_the_result_too(self):
        r = self._post(exercise_id=self.ex.id, reps=8, weight_kg=60)
        self.assertIn("month_cents", r.data["upgrade"])

    def test_the_free_take_is_shared_with_every_other_door(self):
        # One free take total, same as SingZ/RapZ — not one per app.
        self._post(exercise_id=self.ex.id, reps=5, weight_kg=20)
        r2 = self.client.get(TRIAL, {"anon_id": "anon-1"})
        self.assertTrue(r2.data["already_used"])
        r3 = self._post(exercise_id=self.ex.id, reps=5, weight_kg=20)
        self.assertEqual(r3.status_code, 429)
        self.assertTrue(r3.data["already_used"])


class BodieZTrialClaimTests(TestCase):
    """What the trial visitor picked survives signup as a real routine —
    `claim_trial_take` is app_key-generic; `_claim_bodiez_trial` is the
    BodieZ-specific half of it."""

    def setUp(self):
        self.client = APIClient()
        self.ex = BodieZExercise.objects.first()

    def test_registering_with_the_claim_token_creates_a_real_routine(self):
        take = self.client.post(TRIAL, {
            "anon_id": "claim-1", "exercise_id": self.ex.id, "reps": 8, "weight_kg": 60,
        }, format="multipart").data
        user = User.objects.create_user(username="trialclaimer", password="x")
        claimed = claim_trial_take(user, take["claim_token"])
        self.assertIsNotNone(claimed)
        routine = BodieZRoutine.objects.get(user=user)
        self.assertEqual(routine.bucket, "inbox")
        self.assertEqual(routine.exercises[0]["exercise_id"], self.ex.id)
        self.assertEqual(routine.exercises[0]["reps"], 8)
        self.assertEqual(routine.exercises[0]["weight_kg"], 60)

    def test_a_bad_token_creates_no_routine_and_does_not_raise(self):
        user = User.objects.create_user(username="nogo", password="x")
        self.assertIsNone(claim_trial_take(user, "not-a-real-token"))
        self.assertEqual(BodieZRoutine.objects.filter(user=user).count(), 0)

    def test_claiming_a_singz_take_never_creates_a_bodiez_routine(self):
        # `_claim_bodiez_trial` must only fire for app_key == "bodiez" —
        # otherwise a SingZ claim would leave a phantom routine nobody built.
        take = TrialTake.objects.create(
            token="singztok", app_key="singz", result={"score": 7}, scored=True,
        )
        user = User.objects.create_user(username="singzclaimer", password="x")
        claim_trial_take(user, "singztok")
        self.assertEqual(BodieZRoutine.objects.filter(user=user).count(), 0)


@override_settings()
class BodieZFunnelDoorTests(TestCase):
    """bodiez is a real funnel app_key now, not just an unvalidated string."""

    def setUp(self):
        self.client = APIClient()

    def test_bodiez_app_key_is_accepted_by_the_funnel(self):
        r = self.client.post("/api/auth/funnel/", {
            "kind": "try_view", "anon_id": "a1", "meta": {"app_key": "bodiez"},
        }, format="json")
        self.assertEqual(r.status_code, 204)

    def test_an_unknown_app_key_is_still_dropped(self):
        r = self.client.post("/api/auth/funnel/", {
            "kind": "try_view", "anon_id": "a1", "meta": {"app_key": "not-a-door"},
        }, format="json")
        self.assertEqual(r.status_code, 204)
        from apps.economy.models import FunnelEvent
        ev = FunnelEvent.objects.get(anon_id="a1")
        self.assertNotIn("app_key", ev.meta)
