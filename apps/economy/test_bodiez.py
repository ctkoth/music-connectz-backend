"""Tests for BodieZ — exercises, routines, sessions and progress."""
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status

from .models import BodieZExercise, BodieZRoutine, BodieZSession, BodieZSet


class BodieZExercisesViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="u1", password="pw")
        self.client.force_authenticate(user=self.user)
        self.bench = BodieZExercise.objects.create(name="Test Bench Press", muscle_group="chest", equipment="barbell")
        self.squat = BodieZExercise.objects.create(name="Test Squat", muscle_group="legs", equipment="barbell")

    def test_lists_all_exercises(self):
        response = self.client.get("/api/economy/bodiez/exercises/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = {e["name"] for e in response.data["exercises"]}
        self.assertIn("Test Bench Press", names)
        self.assertIn("Test Squat", names)

    def test_filters_by_muscle_group(self):
        response = self.client.get("/api/economy/bodiez/exercises/?muscle_group=legs")
        names = {e["name"] for e in response.data["exercises"]}
        self.assertIn("Test Squat", names)
        self.assertNotIn("Test Bench Press", names)

    def test_requires_auth(self):
        client = APIClient()
        response = client.get("/api/economy/bodiez/exercises/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class BodieZRoutinesViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="u1", password="pw")
        self.client.force_authenticate(user=self.user)
        self.bench = BodieZExercise.objects.create(name="Test Bench Press", muscle_group="chest", equipment="barbell")

    def test_create_routine(self):
        response = self.client.post("/api/economy/bodiez/routines/", {
            "title": "Push Day",
            "exercises": [{"exercise_id": self.bench.id, "sets": 3, "reps": 8, "order": 1}],
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "Push Day")
        self.assertTrue(BodieZRoutine.objects.filter(user=self.user, title="Push Day").exists())

    def test_create_routine_requires_title(self):
        response = self.client.post("/api/economy/bodiez/routines/", {"exercises": []}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_routine_rejects_unknown_exercise(self):
        response = self.client.post("/api/economy/bodiez/routines/", {
            "title": "Push Day",
            "exercises": [{"exercise_id": 999999, "sets": 3, "reps": 8}],
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_only_own_routines(self):
        other = User.objects.create_user(username="u2", password="pw")
        BodieZRoutine.objects.create(user=other, title="Not mine", exercises=[])
        BodieZRoutine.objects.create(user=self.user, title="Mine", exercises=[])
        response = self.client.get("/api/economy/bodiez/routines/")
        titles = {r["title"] for r in response.data["routines"]}
        self.assertEqual(titles, {"Mine"})

    def test_patch_routine(self):
        routine = BodieZRoutine.objects.create(user=self.user, title="Old", exercises=[])
        response = self.client.patch(f"/api/economy/bodiez/routines/{routine.id}/",
                                      {"title": "New"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        routine.refresh_from_db()
        self.assertEqual(routine.title, "New")

    def test_patch_other_users_routine_404s(self):
        other = User.objects.create_user(username="u2", password="pw")
        routine = BodieZRoutine.objects.create(user=other, title="Not mine", exercises=[])
        response = self.client.patch(f"/api/economy/bodiez/routines/{routine.id}/",
                                      {"title": "Hacked"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_routine(self):
        routine = BodieZRoutine.objects.create(user=self.user, title="Gone soon", exercises=[])
        response = self.client.delete(f"/api/economy/bodiez/routines/{routine.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(BodieZRoutine.objects.filter(id=routine.id).exists())


class BodieZSessionsViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="u1", password="pw")
        self.client.force_authenticate(user=self.user)
        self.bench = BodieZExercise.objects.create(name="Test Bench Press", muscle_group="chest", equipment="barbell")

    def test_start_ad_hoc_session(self):
        response = self.client.post("/api/economy/bodiez/sessions/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data["routine_id"])
        self.assertIsNone(response.data["ended_at"])

    def test_start_session_against_routine(self):
        routine = BodieZRoutine.objects.create(user=self.user, title="Push Day", exercises=[])
        response = self.client.post("/api/economy/bodiez/sessions/",
                                     {"routine_id": routine.id}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["routine_id"], routine.id)

    def test_cannot_start_second_session_while_one_open(self):
        self.client.post("/api/economy/bodiez/sessions/", {}, format="json")
        response = self.client.post("/api/economy/bodiez/sessions/", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_log_set(self):
        sess = BodieZSession.objects.create(user=self.user)
        response = self.client.post(f"/api/economy/bodiez/sessions/{sess.id}/sets/", {
            "exercise_id": self.bench.id, "reps": 8, "weight_kg": 60,
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["set_number"], 1)
        self.assertEqual(response.data["weight_kg"], 60.0)

    def test_log_bodyweight_set_has_null_weight(self):
        sess = BodieZSession.objects.create(user=self.user)
        pushup = BodieZExercise.objects.create(name="Test Push-Up", muscle_group="chest", equipment="bodyweight")
        response = self.client.post(f"/api/economy/bodiez/sessions/{sess.id}/sets/", {
            "exercise_id": pushup.id, "reps": 20,
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data["weight_kg"])

    def test_set_numbers_increment_per_exercise(self):
        sess = BodieZSession.objects.create(user=self.user)
        for _ in range(3):
            self.client.post(f"/api/economy/bodiez/sessions/{sess.id}/sets/", {
                "exercise_id": self.bench.id, "reps": 8, "weight_kg": 60,
            }, format="json")
        numbers = list(BodieZSet.objects.filter(session=sess).values_list("set_number", flat=True))
        self.assertEqual(numbers, [1, 2, 3])

    def test_cannot_log_set_on_finished_session(self):
        sess = BodieZSession.objects.create(user=self.user)
        self.client.patch(f"/api/economy/bodiez/sessions/{sess.id}/", {"finish": True}, format="json")
        response = self.client.post(f"/api/economy/bodiez/sessions/{sess.id}/sets/", {
            "exercise_id": self.bench.id, "reps": 8, "weight_kg": 60,
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_negative_weight(self):
        sess = BodieZSession.objects.create(user=self.user)
        response = self.client.post(f"/api/economy/bodiez/sessions/{sess.id}/sets/", {
            "exercise_id": self.bench.id, "reps": 8, "weight_kg": -5,
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_zero_reps(self):
        sess = BodieZSession.objects.create(user=self.user)
        response = self.client.post(f"/api/economy/bodiez/sessions/{sess.id}/sets/", {
            "exercise_id": self.bench.id, "reps": 0, "weight_kg": 60,
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_finish_session(self):
        sess = BodieZSession.objects.create(user=self.user)
        response = self.client.patch(f"/api/economy/bodiez/sessions/{sess.id}/",
                                      {"finish": True}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data["ended_at"])

    def test_cannot_finish_twice(self):
        sess = BodieZSession.objects.create(user=self.user)
        self.client.patch(f"/api/economy/bodiez/sessions/{sess.id}/", {"finish": True}, format="json")
        response = self.client.patch(f"/api/economy/bodiez/sessions/{sess.id}/", {"finish": True}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class BodieZProgressViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="u1", password="pw")
        self.client.force_authenticate(user=self.user)
        self.bench = BodieZExercise.objects.create(name="Test Bench Press", muscle_group="chest", equipment="barbell")
        self.pushup = BodieZExercise.objects.create(name="Test Push-Up", muscle_group="chest", equipment="bodyweight")

    def test_empty_progress(self):
        response = self.client.get("/api/economy/bodiez/progress/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["sessions_completed"], 0)
        self.assertEqual(response.data["total_volume_kg"], 0)

    def test_volume_only_counts_weighted_sets(self):
        from django.utils import timezone
        sess = BodieZSession.objects.create(user=self.user, ended_at=timezone.now())
        BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=10, weight_kg=100)
        BodieZSet.objects.create(session=sess, exercise=self.pushup, set_number=1, reps=20, weight_kg=None)
        response = self.client.get("/api/economy/bodiez/progress/")
        self.assertEqual(response.data["sessions_completed"], 1)
        self.assertEqual(response.data["sets_logged"], 2)
        self.assertEqual(response.data["total_volume_kg"], 1000.0)

    def test_in_progress_session_not_counted(self):
        BodieZSession.objects.create(user=self.user)  # ended_at is null
        response = self.client.get("/api/economy/bodiez/progress/")
        self.assertEqual(response.data["sessions_completed"], 0)

    def test_only_own_sessions_counted(self):
        from django.utils import timezone
        other = User.objects.create_user(username="u2", password="pw")
        other_sess = BodieZSession.objects.create(user=other, ended_at=timezone.now())
        BodieZSet.objects.create(session=other_sess, exercise=self.bench, set_number=1, reps=10, weight_kg=100)
        response = self.client.get("/api/economy/bodiez/progress/")
        self.assertEqual(response.data["sessions_completed"], 0)
        self.assertEqual(response.data["total_volume_kg"], 0)


class BodieZSchedulerTests(TestCase):
    """The Jefit-on-a-Lilith-scheduler piece: routines organized into
    Inbox/Today/Upcoming/Anytime/Someday/Trash, same bucket shape Lilith
    already gives a task."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="u1", password="pw")
        self.client.force_authenticate(user=self.user)

    def test_a_new_routine_lands_in_inbox_by_default(self):
        r = self.client.post("/api/economy/bodiez/routines/", {"title": "Push Day"}, format="json")
        self.assertEqual(r.data["bucket"], "inbox")

    def test_a_routine_can_be_created_straight_into_a_bucket(self):
        r = self.client.post("/api/economy/bodiez/routines/",
                              {"title": "Push Day", "bucket": "today"}, format="json")
        self.assertEqual(r.data["bucket"], "today")

    def test_an_unknown_bucket_on_create_falls_back_to_inbox(self):
        r = self.client.post("/api/economy/bodiez/routines/",
                              {"title": "Push Day", "bucket": "not-a-real-bucket"}, format="json")
        self.assertEqual(r.data["bucket"], "inbox")

    def test_moving_a_routine_between_buckets(self):
        routine = BodieZRoutine.objects.create(user=self.user, title="Push Day")
        r = self.client.patch(f"/api/economy/bodiez/routines/{routine.id}/",
                               {"bucket": "upcoming"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["bucket"], "upcoming")
        routine.refresh_from_db()
        self.assertEqual(routine.bucket, "upcoming")

    def test_an_unknown_bucket_on_move_is_refused(self):
        routine = BodieZRoutine.objects.create(user=self.user, title="Push Day")
        r = self.client.patch(f"/api/economy/bodiez/routines/{routine.id}/",
                               {"bucket": "not-a-real-bucket"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_scheduling_a_routine_for_a_date(self):
        routine = BodieZRoutine.objects.create(user=self.user, title="Push Day")
        r = self.client.patch(f"/api/economy/bodiez/routines/{routine.id}/",
                               {"scheduled_for": "2026-10-01"}, format="json")
        self.assertEqual(r.data["scheduled_for"], "2026-10-01")

    def test_clearing_a_scheduled_date(self):
        routine = BodieZRoutine.objects.create(user=self.user, title="Push Day",
                                                scheduled_for="2026-10-01")
        r = self.client.patch(f"/api/economy/bodiez/routines/{routine.id}/",
                               {"scheduled_for": ""}, format="json")
        self.assertIsNone(r.data["scheduled_for"])

    def test_an_unparseable_date_is_refused(self):
        routine = BodieZRoutine.objects.create(user=self.user, title="Push Day")
        r = self.client.patch(f"/api/economy/bodiez/routines/{routine.id}/",
                               {"scheduled_for": "not-a-date"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_moving_to_trash_does_not_delete_the_row(self):
        routine = BodieZRoutine.objects.create(user=self.user, title="Push Day")
        self.client.patch(f"/api/economy/bodiez/routines/{routine.id}/",
                           {"bucket": "trash"}, format="json")
        self.assertTrue(BodieZRoutine.objects.filter(id=routine.id).exists())

    def test_the_board_groups_every_routine_by_bucket_in_one_request(self):
        BodieZRoutine.objects.create(user=self.user, title="A", bucket="inbox")
        BodieZRoutine.objects.create(user=self.user, title="B", bucket="today")
        BodieZRoutine.objects.create(user=self.user, title="C", bucket="today")
        BodieZRoutine.objects.create(user=self.user, title="D", bucket="someday")
        r = self.client.get("/api/economy/bodiez/board/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        b = r.data["buckets"]
        self.assertEqual(set(b), {"inbox", "today", "upcoming", "anytime", "someday", "trash"})
        self.assertEqual(len(b["inbox"]), 1)
        self.assertEqual(len(b["today"]), 2)
        self.assertEqual(len(b["upcoming"]), 0)

    def test_the_board_only_shows_my_own_routines(self):
        other = User.objects.create_user(username="u2", password="pw")
        BodieZRoutine.objects.create(user=other, title="Not mine", bucket="today")
        r = self.client.get("/api/economy/bodiez/board/")
        self.assertEqual(r.data["buckets"]["today"], [])

    def test_the_board_serves_bucket_labels_so_the_client_never_retypes_them(self):
        r = self.client.get("/api/economy/bodiez/board/")
        keys = {row["key"] for row in r.data["bucket_labels"]}
        self.assertEqual(keys, {"inbox", "today", "upcoming", "anytime", "someday", "trash"})

    def test_board_requires_auth(self):
        client = APIClient()
        r = client.get("/api/economy/bodiez/board/")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
