"""Lilith's dates: a day on any task outside Today, and the way the board is ordered by them."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import lilith_taskz as L
from apps.economy.models import LilithTask

User = get_user_model()
TASKS = "/api/economy/lilith/tasks/"
BOARD = "/api/economy/lilith/"
MOVE = "/api/economy/lilith/move/"


def member(name):
    return User.objects.create_user(name, f"{name}@mcz.test", "pw12345!")


class DueParsingTests(TestCase):
    def test_blank_is_no_date(self):
        self.assertIsNone(L.parse_due(None))
        self.assertIsNone(L.parse_due(""))

    def test_a_day_is_a_day(self):
        self.assertEqual(L.parse_due("2026-12-01"), date(2026, 12, 1))

    def test_each_refusal_says_what_is_wrong(self):
        for raw, why in (("next tuesday", "looks like"), ("2026-02-30", "real day"),
                         ("1999-12-31", "between 2000 and 2100"), ("2101-01-01", "between 2000 and 2100")):
            with self.assertRaises(L.DueError) as cm:
                L.parse_due(raw)
            self.assertIn(why, str(cm.exception), raw)


class DueOnTasksTests(TestCase):
    def setUp(self):
        self.u = member("dated")
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def test_a_task_outside_today_takes_a_date_and_says_it_back_as_a_day(self):
        r = self.c.post(TASKS, {"title": "Send the stems", "bucket": "upcoming", "due": "2026-12-01"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["due"], "2026-12-01")              # the day exactly as sent, not a timestamp
        self.assertEqual(LilithTask.objects.get(pk=r.json()["id"]).due, date(2026, 12, 1))

    def test_a_bad_date_is_refused_with_a_sentence_not_a_server_error(self):
        r = self.c.post(TASKS, {"title": "x", "bucket": "upcoming", "due": "next tuesday"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("2026-12-01", r.json()["detail"])
        self.assertFalse(LilithTask.objects.filter(user=self.u).exists())

    def test_today_has_no_date(self):
        r = self.c.post(TASKS, {"title": "x", "bucket": "today", "due": "2026-12-01"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(LilithTask.objects.filter(user=self.u).exists())

    def test_a_date_can_be_set_kept_moved_and_cleared(self):
        t = LilithTask.objects.create(user=self.u, title="x", bucket="anytime")
        url = f"{TASKS}{t.pk}/"
        self.assertEqual(self.c.patch(url, {"due": "2026-12-03"}, format="json").json()["due"], "2026-12-03")
        self.assertEqual(self.c.patch(url, {"bucket": "someday"}, format="json").json()["due"], "2026-12-03")
        self.assertIsNone(self.c.patch(url, {"due": ""}, format="json").json()["due"])

    def test_today_refuses_a_date_and_moving_into_today_clears_it(self):
        t = LilithTask.objects.create(user=self.u, title="x", bucket="upcoming", due=date(2026, 12, 3))
        url = f"{TASKS}{t.pk}/"
        self.assertEqual(self.c.patch(url, {"bucket": "today", "due": "2026-12-04"}, format="json").status_code, 400)
        self.assertIsNone(self.c.patch(url, {"bucket": "today"}, format="json").json()["due"])
        self.assertIsNone(LilithTask.objects.get(pk=t.pk).due)

    def test_moving_a_dated_task_into_today_from_the_move_menu_clears_it(self):
        t = LilithTask.objects.create(user=self.u, title="x", bucket="upcoming", due=date(2026, 12, 3))
        self.assertEqual(self.c.post(MOVE, {"kind": "task", "id": t.pk, "to": "today"}, format="json").status_code, 200)
        self.assertIsNone(LilithTask.objects.get(pk=t.pk).due)

    def test_the_board_draws_dated_tasks_soonest_first_and_undated_after(self):
        LilithTask.objects.create(user=self.u, title="undated", bucket="upcoming")
        LilithTask.objects.create(user=self.u, title="late", bucket="upcoming", due=date(2026, 12, 9))
        LilithTask.objects.create(user=self.u, title="soon", bucket="upcoming", due=date(2026, 12, 2))
        titles = [t["title"] for t in self.c.get(BOARD).json()["buckets"]["upcoming"]]
        self.assertEqual(titles, ["soon", "late", "undated"])

    def test_a_due_day_is_served_as_the_same_calendar_day(self):
        LilithTask.objects.create(user=self.u, title="x", bucket="anytime", due=date(2026, 12, 31))
        rows = self.c.get(BOARD).json()["buckets"]["anytime"]
        self.assertEqual(rows[0]["due"], "2026-12-31")               # no timezone turns it into the day before
