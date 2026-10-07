"""BodieZ accessibility, per-muscle coach ratings, and the demo-video audit."""
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from .bodiez import RATING_CAVEAT
from .models import BodieZAccess, BodieZExercise, BodieZSet
from .test_bodiez import _finished_session

URL = "/api/economy/bodiez/"


class AccessFilterTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="a1", password="pw")
        self.client.force_authenticate(user=self.user)

    def _flags(self):
        r = self.client.get(URL + "exercises/")
        return {e["name"]: e["accessible"] for e in r.data["exercises"]}

    def test_default_member_sees_everything_as_accessible(self):
        self.assertTrue(all(self._flags().values()))

    def test_cannot_walk_keeps_only_seated_or_lying(self):
        self.client.put(URL + "access/", {"seated_or_lying_only": True}, format="json")
        f = self._flags()
        self.assertTrue(f["Bench Press"])            # lying
        self.assertTrue(f["Lat Pulldown"])           # seated
        self.assertTrue(f["Bicep Curl"])             # standing OR seated
        self.assertFalse(f["Squat"])
        self.assertFalse(f["Running"])
        self.assertFalse(f["Plank"])                 # floor is not seated/lying

    def test_unusable_arms_hides_every_arm_exercise(self):
        self.client.put(URL + "access/", {"arms_ok": False}, format="json")
        f = self._flags()
        self.assertTrue(f["Leg Press"])
        self.assertFalse(f["Bench Press"])
        self.assertFalse(f["Bicep Curl"])

    def test_unusable_legs_hides_leg_work_and_all_standing_work(self):
        self.client.put(URL + "access/", {"legs_ok": False}, format="json")
        f = self._flags()
        self.assertFalse(f["Leg Press"])             # needs legs
        self.assertFalse(f["Squat"])
        self.assertFalse(f["Pull-Up"])               # legs unused, but standing-only
        self.assertTrue(f["Bench Press"])
        self.assertTrue(f["Pec Deck"])

    def test_both_limbs_unusable_leaves_only_what_needs_neither(self):
        self.client.put(URL + "access/", {"arms_ok": False, "legs_ok": False}, format="json")
        f = self._flags()
        self.assertFalse(any(f.values()) and False)  # never a crash
        for name, ok in f.items():
            ex = BodieZExercise.objects.get(name=name)
            if ok:
                self.assertFalse(ex.needs_arms or ex.needs_legs, name)

    def test_hidden_exercises_are_still_returned_so_history_keeps_names(self):
        self.client.put(URL + "access/", {"seated_or_lying_only": True}, format="json")
        names = {e["name"] for e in self.client.get(URL + "exercises/").data["exercises"]}
        self.assertIn("Squat", names)

    def test_an_untagged_exercise_is_hidden_from_a_restricted_member(self):
        BodieZExercise.objects.create(name="Mystery Move", muscle_group="abs", equipment="bodyweight")
        self.client.put(URL + "access/", {"seated_or_lying_only": True}, format="json")
        self.assertFalse(self._flags()["Mystery Move"])

    def test_access_round_trips_and_rejects_junk(self):
        r = self.client.put(URL + "access/", {"legs_ok": False}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(URL + "access/").data["legs_ok"], False)
        bad = self.client.put(URL + "access/", {"arms_ok": "maybe"}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertTrue(BodieZAccess.objects.get(user=self.user).arms_ok)

    def test_access_is_per_member(self):
        self.client.put(URL + "access/", {"legs_ok": False}, format="json")
        other = APIClient()
        other.force_authenticate(user=User.objects.create_user(username="a2", password="pw"))
        self.assertTrue(other.get(URL + "access/").data["legs_ok"])

    def test_access_requires_auth(self):
        self.assertEqual(APIClient().get(URL + "access/").status_code, 401)


class LibraryCoverageTests(TestCase):
    def test_every_exercise_is_tagged_with_a_known_position(self):
        known = {k for k, _ in BodieZExercise.POSITION_CHOICES}
        for ex in BodieZExercise.objects.all():
            self.assertTrue(ex.position_list, ex.name)
            self.assertTrue(set(ex.position_list) <= known, ex.name)

    def test_seated_lying_members_have_something_for_every_muscle_they_can_reach(self):
        # Glutes had no exercise at all before this; a restricted member must
        # not hit an empty group for a muscle the library can train sitting.
        for muscle in ("chest", "back", "shoulders", "biceps", "triceps", "abs",
                       "upper_legs", "lower_legs", "glutes", "cardio"):
            ok = [e for e in BodieZExercise.objects.filter(muscle_group=muscle)
                  if {"seated", "lying"} & set(e.position_list)]
            self.assertTrue(ok, muscle)

    def test_there_are_arm_free_and_leg_free_options(self):
        self.assertTrue(BodieZExercise.objects.filter(needs_arms=False, positions__regex="seated|lying").exists())
        self.assertTrue(BodieZExercise.objects.filter(needs_legs=False, positions__regex="seated|lying").exists())

    def test_uploaded_clips_are_wired(self):
        for name in ("Push-Up", "Dip", "EZ Bar Upright Row", "Kettlebell Row",
                     "Overhead Press", "Lat Pulldown", "Dumbbell Romanian Deadlift"):
            ex = BodieZExercise.objects.get(name=name)
            self.assertTrue(ex.demo_url.startswith("/exercise-demos/"), name)


class MuscleCoachRatingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="r1", password="pw")
        self.client.force_authenticate(user=self.user)
        self.bench = BodieZExercise.objects.create(name="T Bench", muscle_group="chest", equipment="barbell")
        self.fly = BodieZExercise.objects.create(name="T Fly", muscle_group="chest", equipment="dumbbell")

    def _log(self, ex, days_ago, reps, weight):
        BodieZSet.objects.create(session=_finished_session(self.user, days_ago=days_ago),
                                 exercise=ex, set_number=1, reps=reps, weight_kg=weight)

    def _chest(self):
        r = self.client.get(URL + "bodymap/")
        return next(m for m in r.data["muscles"] if m["muscle_group"] == "chest"), r.data

    def test_unrated_until_an_exercise_has_two_sessions(self):
        self._log(self.bench, 0, 8, 60)
        chest, data = self._chest()
        self.assertIsNone(chest["coach_rating"])
        self.assertTrue(chest["coach_why"])
        self.assertEqual(data["rating_caveat"], RATING_CAVEAT)

    def test_untrained_muscle_is_unrated_not_zero(self):
        r = self.client.get(URL + "bodymap/")
        legs = next(m for m in r.data["muscles"] if m["muscle_group"] == "upper_legs")
        self.assertIsNone(legs["coach_rating"])

    def test_a_lift_that_went_up_rates_ten_and_shows_its_numbers(self):
        self._log(self.bench, 10, 8, 60)
        self._log(self.bench, 0, 8, 70)
        chest, _ = self._chest()
        self.assertEqual(chest["coach_rating"], 10)
        ex = chest["coach_exercises"][0]
        self.assertEqual(ex["trend"], "up")
        self.assertGreater(ex["latest"], ex["earlier_best"])

    def test_held_is_six(self):
        self._log(self.bench, 10, 8, 60)
        self._log(self.bench, 0, 8, 60)
        self.assertEqual(self._chest()[0]["coach_rating"], 6)

    def test_a_real_drop_is_three_but_one_tired_day_is_not(self):
        self._log(self.bench, 10, 8, 60)
        self._log(self.bench, 0, 8, 50)
        self.assertEqual(self._chest()[0]["coach_rating"], 3)
        BodieZSet.objects.all().delete()
        self._log(self.bench, 10, 8, 60)
        self._log(self.bench, 0, 8, 57)   # ~95%: held
        self.assertEqual(self._chest()[0]["coach_rating"], 6)

    def test_muscle_rating_averages_its_exercises(self):
        self._log(self.bench, 10, 8, 60); self._log(self.bench, 0, 8, 70)   # up 10
        self._log(self.fly, 10, 10, 20); self._log(self.fly, 0, 10, 20)     # held 6
        self.assertEqual(self._chest()[0]["coach_rating"], 8)

    def test_effort_without_progress_does_not_raise_it(self):
        # Five sessions in the window, nothing improving: volume_score climbs,
        # the coach rating does not.
        for d in (4, 3, 2, 1, 0):
            self._log(self.bench, d, 8, 60)
        chest, _ = self._chest()
        self.assertEqual(chest["coach_rating"], 6)

    def test_bodyweight_lifts_compare_on_reps(self):
        push = BodieZExercise.objects.create(name="T Push", muscle_group="chest", equipment="bodyweight")
        self._log(push, 10, 10, None)
        self._log(push, 0, 15, None)
        self.assertEqual(self._chest()[0]["coach_rating"], 10)

    def test_an_unfinished_session_never_counts(self):
        from .models import BodieZSession
        self._log(self.bench, 10, 8, 60)
        sess = BodieZSession.objects.create(user=self.user)
        BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=8, weight_kg=200)
        self.assertIsNone(self._chest()[0]["coach_rating"])
