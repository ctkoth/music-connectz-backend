"""Tests for BodieZ — exercises, routines, sessions and progress."""
from datetime import timedelta

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from .models import BodieZExercise, BodieZRoutine, BodieZSession, BodieZSet


class BodieZExercisesViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="u1", password="pw")
        self.client.force_authenticate(user=self.user)
        self.bench = BodieZExercise.objects.create(name="Test Bench Press", muscle_group="chest", equipment="barbell")
        self.squat = BodieZExercise.objects.create(name="Test Squat", muscle_group="upper_legs", equipment="barbell")

    def test_lists_all_exercises(self):
        response = self.client.get("/api/economy/bodiez/exercises/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = {e["name"] for e in response.data["exercises"]}
        self.assertIn("Test Bench Press", names)
        self.assertIn("Test Squat", names)

    def test_filters_by_muscle_group(self):
        response = self.client.get("/api/economy/bodiez/exercises/?muscle_group=upper_legs")
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


class BodieZRoutineDayTagTests(TestCase):
    """`day_tag` and `description` — a member's real Jefit export showed the
    gap: `bucket` is a workflow state and `scheduled_for` is one date, but
    neither can say "this is a Monday routine" as a recurring fact, and
    neither supports MULTIPLE routines sharing a day. See BodieZRoutine's
    own docstring."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="daytag1", password="pw")
        self.client.force_authenticate(user=self.user)

    def test_a_routine_can_be_created_with_a_day_tag_and_description(self):
        r = self.client.post("/api/economy/bodiez/routines/", {
            "title": "chest 1", "exercises": [], "day_tag": "mon",
            "description": "recovery in chair",
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["day_tag"], "mon")
        self.assertEqual(r.data["description"], "recovery in chair")

    def test_multiple_routines_can_share_the_same_day_tag(self):
        # This is the actual gap: a single-slot model (one routine per
        # weekday) cannot represent three named Monday sessions a member
        # picks between. day_tag is many-to-one on purpose.
        for title in ["chest 1", "Band arm1", "New chest"]:
            r = self.client.post("/api/economy/bodiez/routines/",
                                  {"title": title, "exercises": [], "day_tag": "mon"}, format="json")
            self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        mon_titles = set(BodieZRoutine.objects.filter(user=self.user, day_tag="mon")
                          .values_list("title", flat=True))
        self.assertEqual(mon_titles, {"chest 1", "Band arm1", "New chest"})

    def test_an_unrecognised_day_tag_is_dropped_not_rejected(self):
        r = self.client.post("/api/economy/bodiez/routines/",
                              {"title": "Junk day", "exercises": [], "day_tag": "whenever"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["day_tag"], "")

    def test_any_is_a_real_day_tag_distinct_from_blank(self):
        r = self.client.post("/api/economy/bodiez/routines/",
                              {"title": "leg ab", "exercises": [], "day_tag": "any"}, format="json")
        self.assertEqual(r.data["day_tag"], "any")

    def test_patch_can_set_and_clear_the_day_tag(self):
        routine = BodieZRoutine.objects.create(user=self.user, title="chest 1", exercises=[])
        r = self.client.patch(f"/api/economy/bodiez/routines/{routine.id}/",
                               {"day_tag": "mon"}, format="json")
        self.assertEqual(r.data["day_tag"], "mon")
        r = self.client.patch(f"/api/economy/bodiez/routines/{routine.id}/",
                               {"day_tag": ""}, format="json")
        self.assertEqual(r.data["day_tag"], "")

    def test_patch_rejects_a_bad_day_tag(self):
        routine = BodieZRoutine.objects.create(user=self.user, title="chest 1", exercises=[])
        r = self.client.patch(f"/api/economy/bodiez/routines/{routine.id}/",
                               {"day_tag": "someday"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_can_set_the_description(self):
        routine = BodieZRoutine.objects.create(user=self.user, title="Grimesto home", exercises=[])
        r = self.client.patch(f"/api/economy/bodiez/routines/{routine.id}/",
                               {"description": "recovery in chair"}, format="json")
        self.assertEqual(r.data["description"], "recovery in chair")


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

    def test_the_board_serves_day_tag_labels_so_the_client_never_retypes_them(self):
        r = self.client.get("/api/economy/bodiez/board/")
        keys = {row["key"] for row in r.data["day_tag_labels"]}
        self.assertEqual(keys, {"mon", "tue", "wed", "thu", "fri", "sat", "sun", "any"})

    def test_board_requires_auth(self):
        client = APIClient()
        r = client.get("/api/economy/bodiez/board/")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


def _finished_session(user, days_ago=0):
    from django.utils import timezone
    sess = BodieZSession.objects.create(user=user)
    sess.started_at = timezone.now() - timedelta(days=days_ago)
    sess.ended_at = sess.started_at
    sess.save(update_fields=["started_at", "ended_at"])
    return sess


class BodieZBodyMapTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="u1", password="pw")
        self.client.force_authenticate(user=self.user)
        self.bench = BodieZExercise.objects.create(name="Test Bench", muscle_group="chest", equipment="barbell")
        self.squat = BodieZExercise.objects.create(name="Test Squat", muscle_group="upper_legs", equipment="barbell")

    def test_every_muscle_group_is_reported_even_with_no_data(self):
        r = self.client.get("/api/economy/bodiez/bodymap/")
        groups = {row["muscle_group"] for row in r.data["muscles"]}
        self.assertEqual(groups, {k for k, _ in BodieZExercise.MUSCLE_CHOICES})

    def test_an_untouched_muscle_group_is_untrained(self):
        r = self.client.get("/api/economy/bodiez/bodymap/")
        legs = next(row for row in r.data["muscles"] if row["muscle_group"] == "upper_legs")
        self.assertEqual(legs["status"], "untrained")
        self.assertIsNone(legs["last_trained"])

    def test_a_set_logged_today_reads_recent(self):
        sess = _finished_session(self.user, days_ago=0)
        BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/bodymap/")
        chest = next(row for row in r.data["muscles"] if row["muscle_group"] == "chest")
        self.assertEqual(chest["status"], "recent")

    def test_a_set_logged_two_weeks_ago_reads_undertrained(self):
        sess = _finished_session(self.user, days_ago=14)
        BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/bodymap/")
        chest = next(row for row in r.data["muscles"] if row["muscle_group"] == "chest")
        self.assertEqual(chest["status"], "undertrained")

    def test_four_separate_days_in_the_window_reads_overworked(self):
        for d in (0, 1, 2, 3):
            sess = _finished_session(self.user, days_ago=d)
            BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/bodymap/")
        chest = next(row for row in r.data["muscles"] if row["muscle_group"] == "chest")
        self.assertEqual(chest["status"], "overworked")

    def test_overworked_counts_days_not_sets(self):
        # Five sets in ONE session must not read the same as five sessions.
        sess = _finished_session(self.user, days_ago=0)
        for i in range(5):
            BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=i + 1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/bodymap/")
        chest = next(row for row in r.data["muscles"] if row["muscle_group"] == "chest")
        self.assertNotEqual(chest["status"], "overworked")

    def test_an_in_progress_session_does_not_count(self):
        sess = BodieZSession.objects.create(user=self.user)  # ended_at null
        BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/bodymap/")
        chest = next(row for row in r.data["muscles"] if row["muscle_group"] == "chest")
        self.assertEqual(chest["status"], "untrained")

    def test_only_my_own_sets_count(self):
        other = User.objects.create_user(username="u2", password="pw")
        sess = _finished_session(other, days_ago=0)
        BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/bodymap/")
        chest = next(row for row in r.data["muscles"] if row["muscle_group"] == "chest")
        self.assertEqual(chest["status"], "untrained")

    def test_requires_auth(self):
        client = APIClient()
        r = client.get("/api/economy/bodiez/bodymap/")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_an_untouched_muscle_scores_zero(self):
        r = self.client.get("/api/economy/bodiez/bodymap/")
        legs = next(row for row in r.data["muscles"] if row["muscle_group"] == "upper_legs")
        self.assertEqual(legs["volume_score"], 0)

    def test_hitting_the_target_scores_a_full_ten(self):
        # TARGET_WEEKLY_SETS is the FLOOR of the evidence-based range, so
        # meeting it reads as a full 10 rather than needing the ceiling.
        for i in range(10):
            sess = _finished_session(self.user, days_ago=0)
            BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/bodymap/")
        chest = next(row for row in r.data["muscles"] if row["muscle_group"] == "chest")
        self.assertEqual(chest["volume_score"], 10)

    def test_half_the_target_scores_a_five(self):
        for i in range(5):
            sess = _finished_session(self.user, days_ago=0)
            BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/bodymap/")
        chest = next(row for row in r.data["muscles"] if row["muscle_group"] == "chest")
        self.assertEqual(chest["volume_score"], 5)

    def test_the_score_never_exceeds_ten_however_much_volume_is_logged(self):
        for i in range(25):
            sess = _finished_session(self.user, days_ago=0)
            BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/bodymap/")
        chest = next(row for row in r.data["muscles"] if row["muscle_group"] == "chest")
        self.assertEqual(chest["volume_score"], 10)

    def test_the_target_and_citation_are_served_so_the_score_is_checkable(self):
        r = self.client.get("/api/economy/bodiez/bodymap/")
        self.assertEqual(r.data["target_weekly_sets"], 10)
        self.assertIn("Schoenfeld", r.data["volume_citation"])

    def test_the_score_can_be_verified_from_sets_last_7d_and_the_target(self):
        for i in range(3):
            sess = _finished_session(self.user, days_ago=0)
            BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/bodymap/")
        chest = next(row for row in r.data["muscles"] if row["muscle_group"] == "chest")
        expected = min(10, round(10 * chest["sets_last_7d"] / r.data["target_weekly_sets"]))
        self.assertEqual(chest["volume_score"], expected)


class BodieZCoachTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="u1", password="pw")
        self.client.force_authenticate(user=self.user)
        self.bench = BodieZExercise.objects.create(name="Test Bench", muscle_group="chest", equipment="barbell")
        self.pushup = BodieZExercise.objects.create(name="Test Push-Up", muscle_group="chest", equipment="bodyweight")

    def test_one_session_is_not_enough_data(self):
        sess = _finished_session(self.user, days_ago=1)
        BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/coach/")
        row = next(x for x in r.data["exercises"] if x["exercise_id"] == self.bench.id)
        self.assertEqual(row["recommendation"], "not_enough_data")

    def test_same_weight_more_reps_recommends_increase_weight(self):
        s1 = _finished_session(self.user, days_ago=7)
        BodieZSet.objects.create(session=s1, exercise=self.bench, set_number=1, reps=7, weight_kg=60)
        s2 = _finished_session(self.user, days_ago=0)
        BodieZSet.objects.create(session=s2, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/coach/")
        row = next(x for x in r.data["exercises"] if x["exercise_id"] == self.bench.id)
        self.assertEqual(row["recommendation"], "increase_weight")
        self.assertIn("60", row["why"])

    def test_same_weight_fewer_reps_holds_steady(self):
        s1 = _finished_session(self.user, days_ago=7)
        BodieZSet.objects.create(session=s1, exercise=self.bench, set_number=1, reps=10, weight_kg=60)
        s2 = _finished_session(self.user, days_ago=0)
        BodieZSet.objects.create(session=s2, exercise=self.bench, set_number=1, reps=6, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/coach/")
        row = next(x for x in r.data["exercises"] if x["exercise_id"] == self.bench.id)
        self.assertEqual(row["recommendation"], "hold_steady")

    def test_a_weight_increase_already_taken_holds_steady(self):
        s1 = _finished_session(self.user, days_ago=7)
        BodieZSet.objects.create(session=s1, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        s2 = _finished_session(self.user, days_ago=0)
        BodieZSet.objects.create(session=s2, exercise=self.bench, set_number=1, reps=8, weight_kg=65)
        r = self.client.get("/api/economy/bodiez/coach/")
        row = next(x for x in r.data["exercises"] if x["exercise_id"] == self.bench.id)
        self.assertEqual(row["recommendation"], "hold_steady")

    def test_a_weight_drop_is_logged_as_a_deload(self):
        s1 = _finished_session(self.user, days_ago=7)
        BodieZSet.objects.create(session=s1, exercise=self.bench, set_number=1, reps=8, weight_kg=70)
        s2 = _finished_session(self.user, days_ago=0)
        BodieZSet.objects.create(session=s2, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/coach/")
        row = next(x for x in r.data["exercises"] if x["exercise_id"] == self.bench.id)
        self.assertEqual(row["recommendation"], "deload_taken")

    def test_bodyweight_exercise_compares_total_reps(self):
        s1 = _finished_session(self.user, days_ago=7)
        BodieZSet.objects.create(session=s1, exercise=self.pushup, set_number=1, reps=15, weight_kg=None)
        s2 = _finished_session(self.user, days_ago=0)
        BodieZSet.objects.create(session=s2, exercise=self.pushup, set_number=1, reps=20, weight_kg=None)
        r = self.client.get("/api/economy/bodiez/coach/")
        row = next(x for x in r.data["exercises"] if x["exercise_id"] == self.pushup.id)
        self.assertEqual(row["recommendation"], "increase_difficulty")

    def test_a_stale_exercise_says_reintroduce(self):
        for d in (60, 45, 30):
            sess = _finished_session(self.user, days_ago=d)
            BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/coach/")
        row = next(x for x in r.data["exercises"] if x["exercise_id"] == self.bench.id)
        self.assertEqual(row["recommendation"], "reintroduce")

    def test_every_recommendation_carries_why(self):
        s1 = _finished_session(self.user, days_ago=7)
        BodieZSet.objects.create(session=s1, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        s2 = _finished_session(self.user, days_ago=0)
        BodieZSet.objects.create(session=s2, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/coach/")
        for row in r.data["exercises"]:
            self.assertTrue(row["why"])

    def test_labels_are_served_for_every_recommendation_key(self):
        from apps.economy.bodiez import REC_LABELS
        s1 = _finished_session(self.user, days_ago=7)
        BodieZSet.objects.create(session=s1, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/coach/")
        self.assertEqual(set(r.data["labels"]), set(REC_LABELS))
        for row in r.data["exercises"]:
            self.assertIn(row["recommendation"], r.data["labels"])

    def test_only_my_own_sessions_are_considered(self):
        other = User.objects.create_user(username="u2", password="pw")
        s1 = _finished_session(other, days_ago=7)
        BodieZSet.objects.create(session=s1, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        s2 = _finished_session(other, days_ago=0)
        BodieZSet.objects.create(session=s2, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/coach/")
        self.assertEqual(r.data["exercises"], [])

    def test_requires_auth(self):
        client = APIClient()
        r = client.get("/api/economy/bodiez/coach/")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


class BodieZGoalsStrengthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="u1", password="pw")
        self.client.force_authenticate(user=self.user)
        self.bench = BodieZExercise.objects.create(name="Test Bench", muscle_group="chest", equipment="barbell")

    def test_create_a_strength_goal(self):
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "strength", "title": "Bench 100kg", "target_value": 100,
            "exercise_id": self.bench.id,
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["kind"], "strength")
        self.assertIsNone(r.data["current_value"])
        self.assertIsNone(r.data["pct"])
        self.assertFalse(r.data["achieved"])

    def test_a_strength_goal_needs_a_real_exercise(self):
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "strength", "title": "Bench 100kg", "target_value": 100,
            "exercise_id": 999999,
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_progress_reads_the_heaviest_logged_set(self):
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "strength", "title": "Bench 100kg", "target_value": 100,
            "exercise_id": self.bench.id,
        }, format="json")
        goal_id = r.data["id"]
        sess = BodieZSession.objects.create(user=self.user, ended_at=timezone.now())
        BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=5, weight_kg=80)
        r = self.client.get("/api/economy/bodiez/goals/")
        row = next(g for g in r.data["goals"] if g["id"] == goal_id)
        self.assertEqual(row["current_value"], 80.0)
        self.assertEqual(row["pct"], 80.0)
        self.assertFalse(row["achieved"])

    def test_a_matching_set_marks_the_goal_achieved(self):
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "strength", "title": "Bench 100kg", "target_value": 100,
            "exercise_id": self.bench.id,
        }, format="json")
        goal_id = r.data["id"]
        sess = BodieZSession.objects.create(user=self.user, ended_at=timezone.now())
        BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=5, weight_kg=100)
        r = self.client.get("/api/economy/bodiez/goals/")
        row = next(g for g in r.data["goals"] if g["id"] == goal_id)
        self.assertTrue(row["achieved"])

    def test_target_reps_filters_out_sets_that_dont_meet_it(self):
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "strength", "title": "Bench 100kg x5", "target_value": 100,
            "exercise_id": self.bench.id, "target_reps": 5,
        }, format="json")
        goal_id = r.data["id"]
        sess = BodieZSession.objects.create(user=self.user, ended_at=timezone.now())
        # 100kg but only 2 reps — doesn't meet the rep target.
        BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=2, weight_kg=100)
        r = self.client.get("/api/economy/bodiez/goals/")
        row = next(g for g in r.data["goals"] if g["id"] == goal_id)
        self.assertIsNone(row["current_value"])

    def test_an_in_progress_session_does_not_count_toward_a_goal(self):
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "strength", "title": "Bench 100kg", "target_value": 100,
            "exercise_id": self.bench.id,
        }, format="json")
        goal_id = r.data["id"]
        sess = BodieZSession.objects.create(user=self.user)  # ended_at null
        BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=5, weight_kg=100)
        r = self.client.get("/api/economy/bodiez/goals/")
        row = next(g for g in r.data["goals"] if g["id"] == goal_id)
        self.assertIsNone(row["current_value"])


class BodieZGoalsFrequencyAndCountTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="u1", password="pw")
        self.client.force_authenticate(user=self.user)

    def test_frequency_goal_counts_distinct_days_in_the_trailing_week(self):
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "frequency", "title": "Train 3x/week", "target_value": 3,
        }, format="json")
        goal_id = r.data["id"]
        for d in (0, 1, 2):
            _finished_session(self.user, days_ago=d)
        r = self.client.get("/api/economy/bodiez/goals/")
        row = next(g for g in r.data["goals"] if g["id"] == goal_id)
        self.assertEqual(row["current_value"], 3)
        self.assertTrue(row["achieved"])

    def test_frequency_goal_ignores_sessions_outside_the_window(self):
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "frequency", "title": "Train 3x/week", "target_value": 3,
        }, format="json")
        goal_id = r.data["id"]
        _finished_session(self.user, days_ago=30)
        r = self.client.get("/api/economy/bodiez/goals/")
        row = next(g for g in r.data["goals"] if g["id"] == goal_id)
        self.assertEqual(row["current_value"], 0)

    def test_count_goal_reads_lifetime_finished_sessions(self):
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "count", "title": "100 workouts", "target_value": 100,
        }, format="json")
        goal_id = r.data["id"]
        for d in range(5):
            _finished_session(self.user, days_ago=d)
        r = self.client.get("/api/economy/bodiez/goals/")
        row = next(g for g in r.data["goals"] if g["id"] == goal_id)
        self.assertEqual(row["current_value"], 5)
        self.assertEqual(row["pct"], 5.0)
        self.assertFalse(row["achieved"])

    def test_a_goal_only_sees_my_own_sessions(self):
        other = User.objects.create_user(username="u2", password="pw")
        _finished_session(other, days_ago=0)
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "count", "title": "100 workouts", "target_value": 100,
        }, format="json")
        goal_id = r.data["id"]
        r = self.client.get("/api/economy/bodiez/goals/")
        row = next(g for g in r.data["goals"] if g["id"] == goal_id)
        self.assertEqual(row["current_value"], 0)


class BodieZGoalsBodyweightTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="u1", password="pw")
        self.client.force_authenticate(user=self.user)

    def test_weight_log_round_trip(self):
        r = self.client.post("/api/economy/bodiez/weightlog/", {"weight_kg": 80}, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        r = self.client.get("/api/economy/bodiez/weightlog/")
        self.assertEqual(len(r.data["logs"]), 1)
        self.assertEqual(r.data["logs"][0]["weight_kg"], 80.0)

    def test_bodyweight_goal_snapshots_starting_value_at_creation(self):
        self.client.post("/api/economy/bodiez/weightlog/", {"weight_kg": 90}, format="json")
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "bodyweight", "title": "Lose to 75kg", "target_value": 75,
        }, format="json")
        self.assertEqual(r.data["starting_value"], 90.0)

    def test_losing_weight_progress_and_achievement(self):
        self.client.post("/api/economy/bodiez/weightlog/", {"weight_kg": 90}, format="json")
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "bodyweight", "title": "Lose to 75kg", "target_value": 75,
        }, format="json")
        goal_id = r.data["id"]
        self.client.post("/api/economy/bodiez/weightlog/", {"weight_kg": 82.5}, format="json")
        r = self.client.get("/api/economy/bodiez/goals/")
        row = next(g for g in r.data["goals"] if g["id"] == goal_id)
        self.assertEqual(row["current_value"], 82.5)
        self.assertEqual(row["pct"], 50.0)
        self.assertFalse(row["achieved"])

    def test_reaching_or_passing_the_losing_target_is_achieved(self):
        self.client.post("/api/economy/bodiez/weightlog/", {"weight_kg": 90}, format="json")
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "bodyweight", "title": "Lose to 75kg", "target_value": 75,
        }, format="json")
        goal_id = r.data["id"]
        self.client.post("/api/economy/bodiez/weightlog/", {"weight_kg": 70}, format="json")
        r = self.client.get("/api/economy/bodiez/goals/")
        row = next(g for g in r.data["goals"] if g["id"] == goal_id)
        self.assertTrue(row["achieved"])

    def test_gaining_weight_progress_and_achievement(self):
        self.client.post("/api/economy/bodiez/weightlog/", {"weight_kg": 60}, format="json")
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "bodyweight", "title": "Bulk to 70kg", "target_value": 70,
        }, format="json")
        goal_id = r.data["id"]
        self.client.post("/api/economy/bodiez/weightlog/", {"weight_kg": 65}, format="json")
        r = self.client.get("/api/economy/bodiez/goals/")
        row = next(g for g in r.data["goals"] if g["id"] == goal_id)
        self.assertEqual(row["pct"], 50.0)
        self.assertFalse(row["achieved"])

    def test_a_bodyweight_goal_with_no_log_at_all_has_no_current_value(self):
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "bodyweight", "title": "Lose to 75kg", "target_value": 75,
        }, format="json")
        self.assertIsNone(r.data["current_value"])
        self.assertIsNone(r.data["pct"])
        self.assertFalse(r.data["achieved"])


class BodieZGoalsGeneralTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="u1", password="pw")
        self.client.force_authenticate(user=self.user)

    def test_an_unknown_kind_is_refused(self):
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "not_a_real_kind", "title": "x", "target_value": 1,
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_there_is_no_custom_kind(self):
        # The whole point: every kind must read off real logged data.
        from apps.economy.models import BODIEZ_GOAL_KINDS
        self.assertNotIn("custom", {k for k, _ in BODIEZ_GOAL_KINDS})

    def test_a_zero_target_is_refused(self):
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "count", "title": "x", "target_value": 0,
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_blank_title_is_refused(self):
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "count", "title": "", "target_value": 5,
        }, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_title_and_date(self):
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "count", "title": "100 workouts", "target_value": 100,
        }, format="json")
        goal_id = r.data["id"]
        r = self.client.patch(f"/api/economy/bodiez/goals/{goal_id}/",
                              {"title": "150 workouts", "target_date": "2026-12-31"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["title"], "150 workouts")
        self.assertEqual(r.data["target_date"], "2026-12-31")

    def test_target_value_is_not_editable_via_patch(self):
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "count", "title": "100 workouts", "target_value": 100,
        }, format="json")
        goal_id = r.data["id"]
        self.client.patch(f"/api/economy/bodiez/goals/{goal_id}/",
                          {"target_value": 5}, format="json")
        r = self.client.get("/api/economy/bodiez/goals/")
        row = next(g for g in r.data["goals"] if g["id"] == goal_id)
        self.assertEqual(row["target_value"], 100.0)

    def test_delete_goal(self):
        r = self.client.post("/api/economy/bodiez/goals/", {
            "kind": "count", "title": "100 workouts", "target_value": 100,
        }, format="json")
        goal_id = r.data["id"]
        r = self.client.delete(f"/api/economy/bodiez/goals/{goal_id}/")
        self.assertEqual(r.status_code, status.HTTP_204_NO_CONTENT)
        r = self.client.get("/api/economy/bodiez/goals/")
        self.assertEqual(r.data["goals"], [])

    def test_patch_other_users_goal_404s(self):
        other = User.objects.create_user(username="u2", password="pw")
        other_client = APIClient()
        other_client.force_authenticate(other)
        r = other_client.post("/api/economy/bodiez/goals/", {
            "kind": "count", "title": "not yours", "target_value": 100,
        }, format="json")
        goal_id = r.data["id"]
        r = self.client.patch(f"/api/economy/bodiez/goals/{goal_id}/", {"title": "mine now"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_kinds_are_served_for_the_client_to_render(self):
        from apps.economy.models import BODIEZ_GOAL_KINDS
        r = self.client.get("/api/economy/bodiez/goals/")
        self.assertEqual({k["key"] for k in r.data["kinds"]}, {k for k, _ in BODIEZ_GOAL_KINDS})

    def test_goals_require_auth(self):
        client = APIClient()
        r = client.get("/api/economy/bodiez/goals/")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_weightlog_requires_auth(self):
        client = APIClient()
        r = client.get("/api/economy/bodiez/weightlog/")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


class BodieZRecoveryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="u1", password="pw")
        self.client.force_authenticate(user=self.user)
        self.bench = BodieZExercise.objects.create(name="Test Bench", muscle_group="chest", equipment="barbell")

    def test_a_checkin_round_trips(self):
        r = self.client.post("/api/economy/bodiez/recovery/",
                              {"soreness": 3, "sleep_quality": 4, "fatigue": 2, "notes": "shoulders tight"},
                              format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["soreness"], 3)
        r = self.client.get("/api/economy/bodiez/recovery/")
        self.assertEqual(len(r.data["logs"]), 1)
        self.assertEqual(r.data["logs"][0]["notes"], "shoulders tight")

    def test_out_of_range_values_are_refused(self):
        r = self.client.post("/api/economy/bodiez/recovery/",
                              {"soreness": 6, "sleep_quality": 3, "fatigue": 2}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_numeric_values_are_refused(self):
        r = self.client.post("/api/economy/bodiez/recovery/",
                              {"soreness": "sore", "sleep_quality": 3, "fatigue": 2}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_rest_signal_with_no_data_at_all(self):
        r = self.client.get("/api/economy/bodiez/recovery/")
        self.assertFalse(r.data["rest_suggested"])
        self.assertEqual(r.data["days_trained_last_7d"], 0)

    def test_high_soreness_alone_suggests_rest(self):
        self.client.post("/api/economy/bodiez/recovery/",
                          {"soreness": 5, "sleep_quality": 3, "fatigue": 2}, format="json")
        r = self.client.get("/api/economy/bodiez/recovery/")
        self.assertTrue(r.data["rest_suggested"])
        self.assertIn("self_reported", r.data["rest_suggested_because"])
        self.assertNotIn("trained_often", r.data["rest_suggested_because"])

    def test_training_five_separate_days_alone_suggests_rest(self):
        for d in (0, 1, 2, 3, 4):
            sess = _finished_session(self.user, days_ago=d)
            BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/recovery/")
        self.assertTrue(r.data["rest_suggested"])
        self.assertIn("trained_often", r.data["rest_suggested_because"])
        self.assertNotIn("self_reported", r.data["rest_suggested_because"])
        self.assertEqual(r.data["days_trained_last_7d"], 5)

    def test_low_soreness_and_light_training_never_suggests_rest(self):
        self.client.post("/api/economy/bodiez/recovery/",
                          {"soreness": 1, "sleep_quality": 5, "fatigue": 1}, format="json")
        sess = _finished_session(self.user, days_ago=0)
        BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get("/api/economy/bodiez/recovery/")
        self.assertFalse(r.data["rest_suggested"])

    def test_only_the_most_recent_checkin_drives_the_self_reported_signal(self):
        self.client.post("/api/economy/bodiez/recovery/",
                          {"soreness": 5, "sleep_quality": 1, "fatigue": 5}, format="json")
        self.client.post("/api/economy/bodiez/recovery/",
                          {"soreness": 1, "sleep_quality": 5, "fatigue": 1}, format="json")
        r = self.client.get("/api/economy/bodiez/recovery/")
        self.assertFalse(r.data["rest_suggested"])

    def test_only_my_own_data_is_considered(self):
        other = User.objects.create_user(username="u2", password="pw")
        other_client = APIClient()
        other_client.force_authenticate(other)
        other_client.post("/api/economy/bodiez/recovery/",
                          {"soreness": 5, "sleep_quality": 1, "fatigue": 5}, format="json")
        r = self.client.get("/api/economy/bodiez/recovery/")
        self.assertFalse(r.data["rest_suggested"])
        self.assertEqual(r.data["logs"], [])

    def test_requires_auth(self):
        client = APIClient()
        r = client.get("/api/economy/bodiez/recovery/")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


class BodieZExerciseHistoryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="u1", password="pw")
        self.client.force_authenticate(user=self.user)
        self.bench = BodieZExercise.objects.create(name="Test Bench", muscle_group="chest", equipment="barbell")

    def test_no_history_returns_null(self):
        r = self.client.get(f"/api/economy/bodiez/exercises/{self.bench.id}/history/")
        self.assertIsNone(r.data["last_session"])

    def test_returns_the_most_recent_finished_sessions_sets(self):
        older = _finished_session(self.user, days_ago=5)
        BodieZSet.objects.create(session=older, exercise=self.bench, set_number=1, reps=5, weight_kg=50)
        newer = _finished_session(self.user, days_ago=0)
        BodieZSet.objects.create(session=newer, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        BodieZSet.objects.create(session=newer, exercise=self.bench, set_number=2, reps=7, weight_kg=60)
        r = self.client.get(f"/api/economy/bodiez/exercises/{self.bench.id}/history/")
        sets = r.data["last_session"]["sets"]
        self.assertEqual(len(sets), 2)
        self.assertEqual(sets[0]["weight_kg"], 60.0)

    def test_an_in_progress_session_is_not_history_yet(self):
        sess = BodieZSession.objects.create(user=self.user)  # ended_at null
        BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get(f"/api/economy/bodiez/exercises/{self.bench.id}/history/")
        self.assertIsNone(r.data["last_session"])

    def test_only_my_own_history_is_returned(self):
        other = User.objects.create_user(username="u2", password="pw")
        sess = _finished_session(other, days_ago=0)
        BodieZSet.objects.create(session=sess, exercise=self.bench, set_number=1, reps=8, weight_kg=60)
        r = self.client.get(f"/api/economy/bodiez/exercises/{self.bench.id}/history/")
        self.assertIsNone(r.data["last_session"])

    def test_requires_auth(self):
        client = APIClient()
        r = client.get(f"/api/economy/bodiez/exercises/{self.bench.id}/history/")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)


class BodieZEquipmentExpansionTests(TestCase):
    """ez_bar, kettlebell and cable each need a real exercise using them, or
    the filter is a dropdown entry pointing at an empty room — see the
    migration's own docstring."""

    def setUp(self):
        self.user = User.objects.create_user(username="equip", password="pw")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_every_new_equipment_value_has_at_least_one_exercise(self):
        for equipment in ("ez_bar", "kettlebell", "cable"):
            self.assertTrue(
                BodieZExercise.objects.filter(equipment=equipment).exists(),
                f"no exercise uses {equipment}")

    def test_relabeled_exercises_carry_their_corrected_equipment(self):
        self.assertEqual(
            BodieZExercise.objects.get(name="Tricep Pushdown").equipment, "cable")
        self.assertEqual(
            BodieZExercise.objects.get(name="Kettlebell Swing").equipment, "kettlebell")

    def test_bench_angle_is_not_a_separate_equipment_value(self):
        # Incline/decline live in the exercise NAME; the equipment stays
        # whatever tool the movement actually uses.
        incline = BodieZExercise.objects.get(name="Incline Barbell Bench Press")
        self.assertEqual(incline.equipment, "barbell")
        choices = {k for k, _ in BodieZExercise.EQUIPMENT_CHOICES}
        self.assertNotIn("incline_bench", choices)
        self.assertNotIn("decline_bench", choices)

    def test_exercise_dict_carries_demo_url_even_when_blank(self):
        r = self.client.get("/api/economy/bodiez/exercises/")
        row = r.data["exercises"][0]
        self.assertIn("demo_url", row)


class BodieZCoachGoalsTests(TestCase):
    """Real, cited rep/set/rest schemes — never a model's guess. See
    bodiez.py's GOALS docstring."""

    def setUp(self):
        self.user = User.objects.create_user(username="goals", password="pw")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_coach_serves_all_three_goals(self):
        from .bodiez import GOALS
        r = self.client.get("/api/economy/bodiez/coach/")
        self.assertEqual(set(r.data["goals"].keys()), set(GOALS.keys()))

    def test_every_goal_carries_a_real_citation_and_a_reachable_scheme(self):
        from .bodiez import GOALS
        for key, scheme in GOALS.items():
            self.assertTrue(scheme["citation"], f"{key} has no citation")
            self.assertLess(scheme["reps_low"], scheme["reps_high"])
            self.assertGreater(scheme["sets"], 0)
            self.assertGreater(scheme["rest_seconds"], 0)

    def test_the_key_is_strength_training_never_strength(self):
        # BodieZGoal already owns "strength" as a KIND driven by logged 1RM
        # progress — a second dict entry keyed "strength" here would be the
        # same word meaning two different things on one screen. The LABEL is
        # allowed to say "Strength" (that's what a member is choosing); the
        # key is what a second writer would collide on, so that's what stays
        # distinct.
        from .bodiez import GOALS
        self.assertNotIn("strength", GOALS)
        self.assertIn("strength_training", GOALS)
        self.assertEqual(GOALS["strength_training"]["label"], "Strength")

    def test_strength_training_is_heavier_and_longer_rest_than_muscle_gain(self):
        from .bodiez import GOALS
        strength = GOALS["strength_training"]
        gain = GOALS["muscle_gain"]
        self.assertLess(strength["reps_high"], gain["reps_low"])
        self.assertGreater(strength["rest_seconds"], gain["rest_seconds"])


class BodieZDemoVideoTests(TestCase):
    """The first real demo_url values — self-recorded, rights cleared. See
    migration 0138's own docstring."""

    def setUp(self):
        self.user = User.objects.create_user(username="demovids", password="pw")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_five_exercises_carry_a_real_demo_url(self):
        # Not a total count — later migrations add more real videos, and a
        # count pinned here would break every time one does, the same trap
        # the funnel's own eleven-kinds story warns against. Check that
        # THESE five specifically got one.
        names = {"Tricep Kickback", "Dumbbell Tricep Extension", "Barbell Tricep Extension",
                 "Barbell Curl", "EZ Bar Skullcrusher"}
        with_demo = set(BodieZExercise.objects.exclude(demo_url="").values_list("name", flat=True))
        self.assertTrue(names.issubset(with_demo))

    def test_demo_urls_are_root_relative_not_a_frozen_host(self):
        for ex in BodieZExercise.objects.exclude(demo_url=""):
            self.assertTrue(ex.demo_url.startswith("/exercise-demos/"), ex.demo_url)

    def test_barbell_curl_is_a_new_row_not_a_relabeled_bicep_curl(self):
        # Bicep Curl stays dumbbell; Barbell Curl is its own exercise.
        self.assertEqual(BodieZExercise.objects.get(name="Bicep Curl").equipment, "dumbbell")
        barbell_curl = BodieZExercise.objects.get(name="Barbell Curl")
        self.assertEqual(barbell_curl.equipment, "barbell")
        self.assertTrue(barbell_curl.demo_url)

    def test_exercise_dict_serves_the_real_url(self):
        r = self.client.get("/api/economy/bodiez/exercises/")
        row = next(e for e in r.data["exercises"] if e["name"] == "Barbell Curl")
        self.assertEqual(row["demo_url"], "/exercise-demos/barbell-curl.mp4")


class BodieZShoulderDemoVideoTests(TestCase):
    """Second batch of real demo_url values. See migration 0139's docstring."""

    def setUp(self):
        self.user = User.objects.create_user(username="demovids2", password="pw")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_this_batchs_three_exercises_carry_a_real_demo_url(self):
        # Not a total — see 0138's test for why a pinned count is the wrong
        # check here.
        names = {"Dumbbell Front Raise", "Dumbbell Shoulder Press", "Lateral Raise"}
        with_demo = set(BodieZExercise.objects.exclude(demo_url="").values_list("name", flat=True))
        self.assertTrue(names.issubset(with_demo))

    def test_dumbbell_shoulder_press_is_not_the_barbell_overhead_press(self):
        overhead = BodieZExercise.objects.get(name="Overhead Press")
        self.assertEqual(overhead.equipment, "barbell")
        self.assertFalse(overhead.demo_url)
        dumbbell_press = BodieZExercise.objects.get(name="Dumbbell Shoulder Press")
        self.assertEqual(dumbbell_press.equipment, "dumbbell")
        self.assertTrue(dumbbell_press.demo_url)

    def test_lateral_raise_kept_its_id_and_gained_a_demo_url(self):
        lateral = BodieZExercise.objects.get(name="Lateral Raise")
        self.assertEqual(lateral.demo_url, "/exercise-demos/dumbbell-lateral-raise.mp4")


class BodieZSplitsTests(TestCase):
    """1-6 days/week splits — real, named conventions covering every
    muscle group across the week. See SPLITS' own docstring for why arms
    rides on both Push and Pull days rather than being dropped from one."""

    def setUp(self):
        self.user = User.objects.create_user(username="splitz", password="pw")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_coach_serves_all_six_day_counts(self):
        from .bodiez import SPLITS
        r = self.client.get("/api/economy/bodiez/coach/")
        self.assertEqual(set(r.data["splits"].keys()), {1, 2, 3, 4, 5, 6})
        self.assertEqual(set(r.data["splits"].keys()), set(SPLITS.keys()))

    def test_every_split_has_exactly_that_many_days(self):
        from .bodiez import SPLITS
        for day_count, split in SPLITS.items():
            self.assertEqual(len(split["days"]), day_count, split["label"])

    def test_every_split_covers_every_real_muscle_group(self):
        from .bodiez import SPLITS
        # cardio and full_body are deliberately not muscle groups a split
        # assigns to a day — they're not what "leg day" or "push day" means.
        real_groups = {"chest", "back", "shoulders", "biceps", "triceps", "forearms",
                       "upper_legs", "lower_legs", "abs", "glutes"}
        for day_count, split in SPLITS.items():
            covered = set()
            for day in split["days"]:
                covered.update(day["muscles"])
            self.assertEqual(covered, real_groups, split["label"])

    def test_trial_serves_the_identical_splits_table(self):
        from .bodiez import SPLITS
        r = self.client.get("/api/economy/bodiez/trial/")
        self.assertEqual(r.data["splits"], SPLITS)


class BodieZChestAndReverseCurlDemoTests(TestCase):
    """Fourth batch. See migration 0141's docstring."""

    def setUp(self):
        self.user = User.objects.create_user(username="demovids4", password="pw")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_this_batchs_exercises_carry_a_real_demo_url(self):
        names = {"Reverse Barbell Curl", "Bench Press",
                 "Incline Barbell Bench Press", "Decline Barbell Bench Press"}
        with_demo = set(BodieZExercise.objects.exclude(demo_url="").values_list("name", flat=True))
        self.assertTrue(names.issubset(with_demo))

    def test_reverse_curl_is_not_a_relabeled_barbell_curl(self):
        barbell_curl = BodieZExercise.objects.get(name="Barbell Curl")
        reverse_curl = BodieZExercise.objects.get(name="Reverse Barbell Curl")
        self.assertNotEqual(barbell_curl.id, reverse_curl.id)
        self.assertTrue(reverse_curl.demo_url)


class BodieZLegsDemoVideoTests(TestCase):
    """Fifth batch, the first to touch legs. See migration 0142's docstring."""

    def setUp(self):
        self.user = User.objects.create_user(username="demovids5", password="pw")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_this_batchs_exercises_carry_a_real_demo_url(self):
        names = {"Squat", "Deadlift", "Leg Press", "Dumbbell Squat", "Dumbbell Deadlift"}
        with_demo = set(BodieZExercise.objects.exclude(demo_url="").values_list("name", flat=True))
        self.assertTrue(names.issubset(with_demo))

    def test_dumbbell_variants_are_not_relabeled_barbell_or_kettlebell_rows(self):
        squat = BodieZExercise.objects.get(name="Squat")
        dumbbell_squat = BodieZExercise.objects.get(name="Dumbbell Squat")
        goblet_squat = BodieZExercise.objects.get(name="Kettlebell Goblet Squat")
        deadlift = BodieZExercise.objects.get(name="Deadlift")
        dumbbell_deadlift = BodieZExercise.objects.get(name="Dumbbell Deadlift")
        self.assertNotEqual(squat.id, dumbbell_squat.id)
        self.assertNotEqual(goblet_squat.id, dumbbell_squat.id)
        self.assertNotEqual(deadlift.id, dumbbell_deadlift.id)
        self.assertTrue(dumbbell_squat.demo_url)
        self.assertTrue(dumbbell_deadlift.demo_url)


class BodieZJefitMuscleGroupsTests(TestCase):
    """The library's 8 muscle groups became Jefit's 11 plus Full Body. See
    migration 0145's docstring for the reasoning and the full REASSIGN map."""

    def setUp(self):
        self.user = User.objects.create_user(username="jefitgroups", password="pw")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_old_coarse_groups_are_gone_from_the_choices(self):
        keys = {k for k, _ in BodieZExercise.MUSCLE_CHOICES}
        self.assertNotIn("arms", keys)
        self.assertNotIn("legs", keys)
        self.assertNotIn("core", keys)

    def test_new_groups_match_jefits_eleven_plus_full_body(self):
        keys = {k for k, _ in BodieZExercise.MUSCLE_CHOICES}
        self.assertEqual(keys, {"abs", "back", "biceps", "cardio", "chest", "forearms",
                                 "glutes", "shoulders", "triceps", "upper_legs",
                                 "lower_legs", "full_body"})

    def test_biceps_and_triceps_are_reachable_separately(self):
        # The entire point: a member filtering to Biceps must not see
        # Tricep Pushdown, and vice versa — the old "arms" bucket answered
        # both with the same list.
        curl = BodieZExercise.objects.get(name="Barbell Curl")
        pushdown = BodieZExercise.objects.get(name="Tricep Pushdown")
        self.assertEqual(curl.muscle_group, "biceps")
        self.assertEqual(pushdown.muscle_group, "triceps")
        self.assertNotEqual(curl.muscle_group, pushdown.muscle_group)

    def test_forearm_focused_curls_moved_off_biceps(self):
        self.assertEqual(BodieZExercise.objects.get(name="Reverse Barbell Curl").muscle_group, "forearms")
        self.assertEqual(BodieZExercise.objects.get(name="Zottman Curl").muscle_group, "forearms")

    def test_legs_split_into_upper_and_lower(self):
        self.assertEqual(BodieZExercise.objects.get(name="Squat").muscle_group, "upper_legs")
        self.assertEqual(BodieZExercise.objects.get(name="Calf Raise").muscle_group, "lower_legs")

    def test_core_exercises_are_now_labeled_abs(self):
        for name in ("Cable Crunch", "Plank", "Russian Twist"):
            self.assertEqual(BodieZExercise.objects.get(name=name).muscle_group, "abs")

    def test_full_body_lifts_kept_their_category_rather_than_being_forced_into_one_muscle(self):
        for name in ("Burpee", "Clean and Press", "Kettlebell Swing", "Turkish Get-Up"):
            self.assertEqual(BodieZExercise.objects.get(name=name).muscle_group, "full_body")

    def test_chest_back_shoulders_cardio_were_untouched(self):
        self.assertEqual(BodieZExercise.objects.get(name="Bench Press").muscle_group, "chest")
        self.assertEqual(BodieZExercise.objects.get(name="Deadlift").muscle_group, "back")
        self.assertEqual(BodieZExercise.objects.get(name="Overhead Press").muscle_group, "shoulders")
        self.assertEqual(BodieZExercise.objects.get(name="Running").muscle_group, "cardio")

    def test_bodymap_reports_all_twelve_groups(self):
        r = self.client.get("/api/economy/bodiez/bodymap/")
        groups = {row["muscle_group"] for row in r.data["muscles"]}
        self.assertEqual(groups, {k for k, _ in BodieZExercise.MUSCLE_CHOICES})


class BodieZCableDemoVideoTests(TestCase):
    """Sixth batch, the first done on a cable stack — no new rows, five
    existing ones. See migration 0144's docstring."""

    def setUp(self):
        self.user = User.objects.create_user(username="demovids6", password="pw")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_this_batchs_exercises_carry_a_real_demo_url(self):
        names = {"Tricep Pushdown", "Cable Row", "Cable Fly", "Cable Face Pull", "Cable Crunch"}
        with_demo = set(BodieZExercise.objects.exclude(demo_url="").values_list("name", flat=True))
        self.assertTrue(names.issubset(with_demo))

    def test_no_new_rows_were_created_only_existing_ones_updated(self):
        # Every name in this batch predates 0130's seed — a row created here
        # would mean this migration typo'd a name past the exact match
        # `filter(name=...)` requires and silently made a duplicate instead.
        for name in ("Tricep Pushdown", "Cable Row", "Cable Fly", "Cable Face Pull", "Cable Crunch"):
            self.assertEqual(BodieZExercise.objects.filter(name=name).count(), 1, name)

    def test_exercise_dict_serves_the_real_url(self):
        r = self.client.get("/api/economy/bodiez/exercises/")
        row = next(e for e in r.data["exercises"] if e["name"] == "Cable Row")
        self.assertEqual(row["demo_url"], "/exercise-demos/cable-row.mp4")


class BodieZDemoCreditTests(TestCase):
    """The IFPA citation travels on the library response once, not per
    video — see bodiez.py's DEMO_CREDIT comment for why."""

    def setUp(self):
        self.user = User.objects.create_user(username="democredit", password="pw")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_credit_is_served_when_a_video_exists(self):
        r = self.client.get("/api/economy/bodiez/exercises/")
        self.assertIn("demo_credit", r.data)
        self.assertTrue(r.data["demo_credit"])
        self.assertIn("IFPA", r.data["demo_credit"])

    def test_credit_is_blank_when_no_exercise_has_a_video(self):
        BodieZExercise.objects.update(demo_url="")
        r = self.client.get("/api/economy/bodiez/exercises/")
        self.assertEqual(r.data["demo_credit"], "")


class CleanTrialSplitTests(TestCase):
    """`clean_trial_split` is the untrusted-input side of the trial's "Build
    a week" flow — the client that calls it was never authenticated, so
    nothing it sends is trusted past this function. See its docstring."""

    def setUp(self):
        self.ex = BodieZExercise.objects.create(name="Trial Split Test Squat", muscle_group="upper_legs", equipment="barbell")

    def test_a_clean_day_survives(self):
        from apps.economy.bodiez import clean_trial_split
        out = clean_trial_split([{"title": "Day 1", "exercises": [
            {"exercise_id": self.ex.id, "order": 0, "sets": 4, "reps": 8, "weight_kg": 100}]}])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["exercises"][0]["exercise_id"], self.ex.id)

    def test_not_a_list_returns_empty(self):
        from apps.economy.bodiez import clean_trial_split
        self.assertEqual(clean_trial_split("nonsense"), [])
        self.assertEqual(clean_trial_split(None), [])
        self.assertEqual(clean_trial_split({}), [])

    def test_unknown_exercise_id_is_dropped(self):
        from apps.economy.bodiez import clean_trial_split
        out = clean_trial_split([{"title": "Day 1", "exercises": [
            {"exercise_id": 999999, "order": 0, "sets": 3, "reps": 10}]}])
        self.assertEqual(out, [])

    def test_a_day_with_no_title_is_dropped(self):
        from apps.economy.bodiez import clean_trial_split
        out = clean_trial_split([{"title": "  ", "exercises": [
            {"exercise_id": self.ex.id, "order": 0, "sets": 3, "reps": 10}]}])
        self.assertEqual(out, [])

    def test_more_than_six_days_is_truncated(self):
        from apps.economy.bodiez import clean_trial_split
        raw = [{"title": f"Day {i}", "exercises": [
            {"exercise_id": self.ex.id, "order": 0, "sets": 3, "reps": 10}]} for i in range(9)]
        out = clean_trial_split(raw)
        self.assertLessEqual(len(out), 6)

    def test_junk_sets_falls_back_to_defaults_for_the_whole_exercise(self):
        from apps.economy.bodiez import clean_trial_split
        out = clean_trial_split([{"title": "Day 1", "exercises": [
            {"exercise_id": self.ex.id, "order": 0, "sets": "not a number", "reps": 8}]}])
        self.assertEqual(len(out), 1)
        ex = out[0]["exercises"][0]
        self.assertEqual(ex["sets"], 3)
        self.assertEqual(ex["reps"], 10)

    def test_an_out_of_range_rep_count_is_clamped_not_replaced(self):
        from apps.economy.bodiez import clean_trial_split
        out = clean_trial_split([{"title": "Day 1", "exercises": [
            {"exercise_id": self.ex.id, "order": 0, "sets": 3, "reps": -50}]}])
        self.assertEqual(out[0]["exercises"][0]["reps"], 1)
