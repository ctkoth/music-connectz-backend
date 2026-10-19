"""RoutineZ: every routine editable whoever built it, a logged workout
editable after the fact, and a logged workout turned into a routine."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import BodieZExercise, BodieZRoutine, BodieZSession, BodieZSet


class _Base(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="lifter", password="pw")
        self.client.force_authenticate(user=self.user)
        self.bench = BodieZExercise.objects.create(name="RZ Bench", muscle_group="chest", equipment="barbell")
        self.row = BodieZExercise.objects.create(name="RZ Row", muscle_group="back", equipment="barbell")

    def past(self, sets, days_ago=2):
        day = (timezone.localdate() - timedelta(days=days_ago)).isoformat()
        r = self.client.post("/api/economy/bodiez/sessions/past/", {"date": day, "sets": sets}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data


class RoutineSourceTests(_Base):
    def test_member_built_by_default(self):
        r = self.client.post("/api/economy/bodiez/routines/", {"title": "Mine"}, format="json")
        self.assertEqual(r.data["source"], "member")

    def test_coach_built_is_labelled_and_still_editable(self):
        r = self.client.post("/api/economy/bodiez/routines/", {
            "title": "Coach day", "source": "coach",
            "exercises": [{"exercise_id": self.bench.id, "sets": 3, "reps": 10}]}, format="json")
        self.assertEqual(r.data["source"], "coach")
        p = self.client.patch(f"/api/economy/bodiez/routines/{r.data['id']}/", {
            "title": "Coach day, my way",
            "exercises": [{"exercise_id": self.row.id, "sets": 4, "reps": 8}]}, format="json")
        self.assertEqual(p.status_code, 200)
        self.assertEqual(p.data["title"], "Coach day, my way")
        self.assertEqual(p.data["exercises"][0]["exercise_id"], self.row.id)

    def test_a_client_cannot_claim_a_server_only_source(self):
        for claimed in ("session", "trial", "nonsense"):
            r = self.client.post("/api/economy/bodiez/routines/", {"title": "x", "source": claimed}, format="json")
            self.assertEqual(r.data["source"], "member", claimed)

    def test_copy_is_a_new_routine_and_leaves_the_original(self):
        src = BodieZRoutine.objects.create(user=self.user, title="Push", source="coach", goal="",
                                           exercises=[{"exercise_id": self.bench.id, "sets": 3, "reps": 5}])
        r = self.client.post(f"/api/economy/bodiez/routines/{src.id}/copy/", {}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertNotEqual(r.data["id"], src.id)
        self.assertEqual(r.data["source"], "member")
        self.assertEqual(r.data["title"], "Push (copy)")
        self.assertEqual(r.data["exercises"], src.exercises)

    def test_cannot_copy_someone_elses(self):
        other = User.objects.create_user(username="other", password="pw")
        src = BodieZRoutine.objects.create(user=other, title="Theirs", exercises=[])
        r = self.client.post(f"/api/economy/bodiez/routines/{src.id}/copy/", {}, format="json")
        self.assertEqual(r.status_code, 404)


class EditLoggedWorkoutTests(_Base):
    def test_replace_sets_keeps_ids_and_drops_the_missing(self):
        sess = self.past([{"exercise_id": self.bench.id, "reps": 5, "weight_kg": 60},
                          {"exercise_id": self.bench.id, "reps": 5, "weight_kg": 60}])
        first, second = sess["sets"]
        r = self.client.put(f"/api/economy/bodiez/sessions/{sess['id']}/sets/", {"sets": [
            {"id": first["id"], "exercise_id": self.bench.id, "reps": 6, "weight_kg": 62.5},
            {"exercise_id": self.row.id, "reps": 10, "weight_kg": None},
        ]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        rows = list(BodieZSet.objects.filter(session_id=sess["id"]).order_by("id"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].id, first["id"])
        self.assertEqual((rows[0].reps, rows[0].weight_kg), (6, Decimal("62.50")))
        self.assertFalse(BodieZSet.objects.filter(id=second["id"]).exists())
        self.assertEqual(rows[1].exercise_id, self.row.id)
        self.assertIn("summary", r.data)

    def test_edited_weight_is_never_converted_again_by_the_pounds_fix(self):
        sess = self.past([{"exercise_id": self.bench.id, "reps": 5, "weight_kg": 60}])
        s = sess["sets"][0]
        self.client.put(f"/api/economy/bodiez/sessions/{sess['id']}/sets/", {"sets": [
            {"id": s["id"], "exercise_id": self.bench.id, "reps": 5, "weight_kg": 61}]}, format="json")
        self.assertTrue(BodieZSet.objects.get(id=s["id"]).converted_from_lb)

    def test_a_bad_row_changes_nothing(self):
        sess = self.past([{"exercise_id": self.bench.id, "reps": 5, "weight_kg": 60}])
        r = self.client.put(f"/api/economy/bodiez/sessions/{sess['id']}/sets/", {"sets": [
            {"exercise_id": self.bench.id, "reps": 0}]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Set 1", r.data["detail"])
        self.assertEqual(BodieZSet.objects.get(session_id=sess["id"]).reps, 5)

    def test_empty_is_refused_with_the_way_out(self):
        sess = self.past([{"exercise_id": self.bench.id, "reps": 5}])
        r = self.client.put(f"/api/economy/bodiez/sessions/{sess['id']}/sets/", {"sets": []}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("delete the workout", r.data["detail"])

    def test_live_session_is_not_rewritten(self):
        live = BodieZSession.objects.create(user=self.user)
        r = self.client.put(f"/api/economy/bodiez/sessions/{live.id}/sets/", {"sets": [
            {"exercise_id": self.bench.id, "reps": 5}]}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_cannot_edit_someone_elses(self):
        other = User.objects.create_user(username="other", password="pw")
        theirs = BodieZSession.objects.create(user=other, ended_at=timezone.now())
        r = self.client.put(f"/api/economy/bodiez/sessions/{theirs.id}/sets/", {"sets": [
            {"exercise_id": self.bench.id, "reps": 5}]}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_backfilled_date_moves_and_live_date_does_not(self):
        sess = self.past([{"exercise_id": self.bench.id, "reps": 5}], days_ago=3)
        new_day = (timezone.localdate() - timedelta(days=5))
        r = self.client.patch(f"/api/economy/bodiez/sessions/{sess['id']}/",
                              {"date": new_day.isoformat()}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(timezone.localtime(BodieZSession.objects.get(id=sess["id"]).started_at).date(), new_day)

        live = BodieZSession.objects.create(user=self.user, ended_at=timezone.now())
        r = self.client.patch(f"/api/economy/bodiez/sessions/{live.id}/",
                              {"date": new_day.isoformat()}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_future_date_refused(self):
        sess = self.past([{"exercise_id": self.bench.id, "reps": 5}])
        r = self.client.patch(f"/api/economy/bodiez/sessions/{sess['id']}/",
                              {"date": (timezone.localdate() + timedelta(days=1)).isoformat()}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_delete_workout(self):
        sess = self.past([{"exercise_id": self.bench.id, "reps": 5}])
        r = self.client.delete(f"/api/economy/bodiez/sessions/{sess['id']}/")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(BodieZSession.objects.filter(id=sess["id"]).exists())
        self.assertFalse(BodieZSet.objects.filter(session_id=sess["id"]).exists())
        other = User.objects.create_user(username="other", password="pw")
        theirs = BodieZSession.objects.create(user=other, ended_at=timezone.now())
        self.assertEqual(self.client.delete(f"/api/economy/bodiez/sessions/{theirs.id}/").status_code, 404)
        self.assertTrue(BodieZSession.objects.filter(id=theirs.id).exists())


class WorkoutToRoutineTests(_Base):
    def test_one_row_per_lift_with_the_top_set_as_target(self):
        sess = self.past([
            {"exercise_id": self.bench.id, "reps": 10, "weight_kg": 40},
            {"exercise_id": self.bench.id, "reps": 5, "weight_kg": 70},
            {"exercise_id": self.bench.id, "reps": 6, "weight_kg": 65},
            {"exercise_id": self.row.id, "reps": 12, "weight_kg": None},
        ])
        r = self.client.post(f"/api/economy/bodiez/sessions/{sess['id']}/routine/", {}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["source"], "session")
        self.assertEqual(r.data["bucket"], "inbox")
        ex = r.data["exercises"]
        self.assertEqual([e["exercise_id"] for e in ex], [self.bench.id, self.row.id])
        self.assertEqual((ex[0]["sets"], ex[0]["reps"], ex[0]["weight_kg"]), (3, 5, 70.0))
        self.assertEqual((ex[1]["sets"], ex[1]["reps"], ex[1]["weight_kg"]), (1, 12, None))
        # The workout itself is untouched.
        self.assertEqual(BodieZSet.objects.filter(session_id=sess["id"]).count(), 4)

    def test_title_can_be_given(self):
        sess = self.past([{"exercise_id": self.bench.id, "reps": 5}])
        r = self.client.post(f"/api/economy/bodiez/sessions/{sess['id']}/routine/",
                             {"title": "Upright row day"}, format="json")
        self.assertEqual(r.data["title"], "Upright row day")

    def test_not_from_someone_elses(self):
        other = User.objects.create_user(username="other", password="pw")
        theirs = BodieZSession.objects.create(user=other, ended_at=timezone.now())
        r = self.client.post(f"/api/economy/bodiez/sessions/{theirs.id}/routine/", {}, format="json")
        self.assertEqual(r.status_code, 404)


class JefitGapExercisesTests(TestCase):
    """The everyday lifts migration 0190 added are in the shared library."""

    def test_upright_rows_and_friends_exist(self):
        for name in ("Barbell Upright Row", "Dumbbell Upright Row", "Cable Upright Row",
                     "Arnold Press", "Chin-Up", "Hammer Curl", "Barbell Hip Thrust",
                     "Barbell Shrug", "Front Squat", "Stiff-Leg Deadlift"):
            self.assertTrue(BodieZExercise.objects.library().filter(name=name).exists(), name)

    def test_every_new_row_has_known_positions(self):
        from .migrations import __path__ as mig_path  # noqa: F401
        import importlib
        mod = importlib.import_module("apps.economy.migrations.0190_bodiez_jefit_gap_exercises")
        known = {k for k, _ in BodieZExercise.POSITION_CHOICES}
        muscles = {k for k, _ in BodieZExercise.MUSCLE_CHOICES}
        equipment = {k for k, _ in BodieZExercise.EQUIPMENT_CHOICES}
        names = [row[0] for row in mod.NEW]
        self.assertEqual(len(names), len(set(names)))
        for name, group, equip, pos, *_ in mod.NEW:
            self.assertIn(group, muscles, name)
            self.assertIn(equip, equipment, name)
            self.assertTrue(set(pos.split(",")) <= known, name)


class RoutineTitleFitsTheColumnTests(_Base):
    """SQLite ignores varchar length; Postgres refuses it. A whole-body Coach
    title ran past 80 and would have 500'd only in production."""

    def test_long_title_is_cut_to_80_on_create_and_edit(self):
        r = self.client.post("/api/economy/bodiez/routines/", {"title": "x" * 200}, format="json")
        self.assertEqual(len(r.data["title"]), 80)
        p = self.client.patch(f"/api/economy/bodiez/routines/{r.data['id']}/", {"title": "y" * 200}, format="json")
        self.assertEqual(len(p.data["title"]), 80)
