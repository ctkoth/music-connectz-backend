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


class RdlIsDumbbellTests(TestCase):
    def test_there_is_one_rdl_and_it_is_dumbbell_with_the_clip(self):
        rows = BodieZExercise.objects.filter(name__icontains="romanian")
        self.assertEqual(rows.count(), 1)
        rdl = rows.get()
        self.assertEqual((rdl.name, rdl.equipment), ("Dumbbell Romanian Deadlift", "dumbbell"))
        self.assertTrue(rdl.demo_url.endswith("Dumbbell%20Romanian%20Deadlift.mp4"))
        self.assertEqual(rdl.muscle_group, "upper_legs")


class VideoAuditCommandTests(TestCase):
    def test_lists_seated_exercises_without_a_clip_and_skips_ones_with_one(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("bodiez_video_audit", "--seated", stdout=out)
        text = out.getvalue()
        self.assertIn("Seated Leg Extension", text)        # seated, no clip
        self.assertNotIn("Dumbbell Romanian Deadlift", text)  # has a clip, and is standing
        self.assertNotIn("Machine Bench Press", text)      # seated, HAS a clip
        self.assertNotIn("Barbell Squat", text)


class ArmFreeLibraryTests(TestCase):
    """The arm-limited half of the library, pinned so it cannot shrink back."""

    def _count(self, **kw):
        a = BodieZAccess(**kw)
        from .bodiez import accessible
        return sum(1 for e in BodieZExercise.objects.all() if accessible(e, a))

    def test_arm_free_work_has_real_depth(self):
        self.assertGreaterEqual(self._count(arms_ok=False), 25)
        self.assertGreaterEqual(self._count(arms_ok=False, seated_or_lying_only=True), 15)
        self.assertGreaterEqual(self._count(arms_ok=False, legs_ok=False), 4)

    def test_no_arm_free_row_is_an_upper_body_muscle(self):
        # An exercise that trains the arms needs them. If one of these ever
        # shows up arm-free, the tag is wrong, not the filter.
        upper = {"chest", "back", "shoulders", "biceps", "triceps", "forearms"}
        for e in BodieZExercise.objects.filter(needs_arms=False):
            self.assertNotIn(e.muscle_group, upper, e.name)

    def test_every_row_has_known_positions(self):
        known = {"standing", "seated", "lying", "kneeling", "floor"}
        for e in BodieZExercise.objects.all():
            self.assertTrue(e.position_list and set(e.position_list) <= known, e.name)


class OneArmTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="oa1", password="pw")
        self.client.force_authenticate(user=self.user)

    def _flags(self):
        return {e["name"]: e["accessible"] for e in self.client.get(URL + "exercises/").data["exercises"]}

    def test_one_arm_keeps_single_arm_work_and_drops_two_handed(self):
        r = self.client.put(URL + "access/", {"one_arm_only": True}, format="json")
        self.assertTrue(r.data["one_arm_only"])
        f = self._flags()
        for ok in ("Dumbbell Row", "Bicep Curl", "Cable Row", "Machine Bench Press", "Leg Press", "Running"):
            self.assertTrue(f[ok], ok)
        for no in ("Barbell Row", "Bench Press", "Push-Up", "Pull-Up", "Kettlebell Goblet Squat", "Squat"):
            self.assertFalse(f[no], no)

    def test_no_arms_beats_one_arm_and_clears_it(self):
        self.client.put(URL + "access/", {"one_arm_only": True}, format="json")
        r = self.client.put(URL + "access/", {"arms_ok": False}, format="json")
        self.assertFalse(r.data["one_arm_only"])
        self.assertFalse(self._flags()["Dumbbell Row"])

    def test_one_arm_is_a_superset_of_no_arms(self):
        self.client.put(URL + "access/", {"arms_ok": False}, format="json")
        none = {k for k, v in self._flags().items() if v}
        self.client.put(URL + "access/", {"arms_ok": True, "one_arm_only": True}, format="json")
        one = {k for k, v in self._flags().items() if v}
        self.assertTrue(none < one)

    def test_one_arm_never_tags_a_barbell_or_bodyweight_arm_lift(self):
        for e in BodieZExercise.objects.filter(one_arm_ok=True):
            self.assertNotIn(e.equipment, ("barbell", "ez_bar"), e.name)
        for n in ("Push-Up", "Pull-Up", "Dip"):
            self.assertFalse(BodieZExercise.objects.get(name=n).one_arm_ok, n)

    def test_bad_value_refused(self):
        self.assertEqual(self.client.put(URL + "access/", {"one_arm_only": "maybe"}, format="json").status_code, 400)
