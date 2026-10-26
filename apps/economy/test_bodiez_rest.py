"""The rest a session asks for follows the plan's intensity, and the server says so."""
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from .bodiez import GOALS, REST_BY_REPS, rest_for_plan
from .models import BodieZExercise, BodieZRoutine


def _plan(*reps):
    return [{"exercise_id": i + 1, "sets": 3, "reps": r} for i, r in enumerate(reps)]


class RestForPlanTests(SimpleTestCase):
    def test_a_goal_wins_and_is_the_goals_own_number(self):
        for key, g in GOALS.items():
            r = rest_for_plan(_plan(20), key)
            self.assertEqual(r["seconds"], g["rest_seconds"], key)
            self.assertEqual(r["basis"], "goal")

    def test_heavier_reps_rest_longer(self):
        secs = [rest_for_plan(_plan(n))["seconds"] for n in (3, 6, 10, 15, 25)]
        self.assertEqual(secs, sorted(secs, reverse=True))
        self.assertEqual(len(set(secs)), len(secs))

    def test_one_light_finisher_does_not_turn_a_heavy_day_light(self):
        self.assertEqual(rest_for_plan(_plan(5, 5, 5, 20))["seconds"], rest_for_plan(_plan(5))["seconds"])

    def test_no_goal_and_no_reps_is_no_opinion_never_a_guess(self):
        self.assertIsNone(rest_for_plan([]))
        self.assertIsNone(rest_for_plan([{"exercise_id": 1, "sets": 3}]))
        self.assertIsNone(rest_for_plan(None))

    def test_junk_rows_are_skipped_not_fatal(self):
        self.assertEqual(rest_for_plan(["x", None, {"reps": "abc"}, {"reps": 5}])["basis"], "reps")

    def test_the_bands_end_open_so_no_rep_count_falls_through(self):
        self.assertEqual(REST_BY_REPS[-1][0], 1000)
        self.assertEqual(rest_for_plan(_plan(100))["label"], REST_BY_REPS[-1][2])

    def test_it_agrees_with_the_published_goals(self):
        """The reps scale is drawn through the goal numbers; if the goals move so
        must it, and this fails rather than the two quietly disagreeing."""
        for key, g in GOALS.items():
            mid = (g["reps_low"] + g["reps_high"]) // 2
            by_reps = rest_for_plan(_plan(mid))["seconds"]
            self.assertLessEqual(abs(by_reps - g["rest_seconds"]), 45, key)


class SessionCarriesRestTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="rester", password="pw")
        self.client.force_authenticate(user=self.user)
        self.ex = BodieZExercise.objects.create(name="RT Squat", muscle_group="upper_legs", equipment="barbell")

    def start(self, routine=None):
        r = self.client.post("/api/economy/bodiez/sessions/", {"routine_id": routine.id} if routine else {}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def test_a_heavy_routine_starts_with_a_long_rest(self):
        rt = BodieZRoutine.objects.create(user=self.user, title="Heavy", goal="",
                                          exercises=[{"exercise_id": self.ex.id, "sets": 5, "reps": 3}])
        s = self.start(rt)
        self.assertEqual(s["rest"]["seconds"], 180)
        self.assertTrue(s["rest"]["why"])

    def test_a_goal_routine_uses_its_goal(self):
        rt = BodieZRoutine.objects.create(user=self.user, title="Size", goal="muscle_gain",
                                          exercises=[{"exercise_id": self.ex.id, "sets": 4, "reps": 3}])
        self.assertEqual(self.start(rt)["rest"]["seconds"], GOALS["muscle_gain"]["rest_seconds"])

    def test_ad_hoc_has_no_intensity_to_read(self):
        self.assertIsNone(self.start()["rest"])
