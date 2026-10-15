"""The coach's pre-filled choices come from the member's own history, and only that.

What these pin:
- a new member gets nulls, so the screen keeps its built-in choice;
- genre and difficulty are the most-used values in the last DEFAULTS_WINDOW
  takes on THIS app, and range is the latest one the coach heard;
- another member's takes and another instrument's takes never count;
- the read is a fixed number of queries however long the history is.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.economy.models import TIER_STATZ, TakeScore, membership_for
from apps.economy.takescorez import DEFAULTS_WINDOW, coach_defaults

User = get_user_model()


def take(user, app_key="singz", genre="", difficulty="", range_class=""):
    return TakeScore.objects.create(user=user, app_key=app_key, overall=6,
                                    genre=genre, difficulty=difficulty,
                                    range_class=range_class)


class CoachDefaultsTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("me", "me@e.com", "pw12345678")
        self.other = User.objects.create_user("other", "o@e.com", "pw12345678")

    def test_a_new_member_gets_nulls(self):
        self.assertEqual(coach_defaults(self.me, "singz"),
                         {"genre": None, "difficulty": None, "range": None})

    def test_most_used_genre_and_difficulty_and_latest_range(self):
        take(self.me, genre="R&B", difficulty="performer", range_class="bass")
        take(self.me, genre="Soul", difficulty="builder")
        take(self.me, genre="Soul", difficulty="builder", range_class="tenor")
        take(self.me, genre="R&B", difficulty="builder")
        d = coach_defaults(self.me, "singz")
        self.assertEqual(d["genre"], "Soul")
        self.assertEqual(d["difficulty"], "builder")
        # The most recent non-blank range, not the most common one.
        self.assertEqual(d["range"], "tenor")

    def test_a_tie_goes_to_the_most_recent_value(self):
        take(self.me, genre="Jazz")
        take(self.me, genre="Soul")
        self.assertEqual(coach_defaults(self.me, "singz")["genre"], "Soul")

    def test_blank_values_are_not_a_genre(self):
        take(self.me, genre="", difficulty="")
        take(self.me, genre="")
        self.assertEqual(coach_defaults(self.me, "singz"),
                         {"genre": None, "difficulty": None, "range": None})

    def test_only_this_apps_takes_count(self):
        for _ in range(5):
            take(self.me, app_key="rapz", genre="Trap", difficulty="stageboss",
                 range_class="soprano")
        take(self.me, app_key="singz", genre="Soul", difficulty="builder")
        self.assertEqual(coach_defaults(self.me, "singz"),
                         {"genre": "Soul", "difficulty": "builder", "range": None})

    def test_another_members_takes_are_ignored(self):
        for _ in range(5):
            take(self.other, genre="Trap", difficulty="stageboss", range_class="soprano")
        self.assertEqual(coach_defaults(self.me, "singz"),
                         {"genre": None, "difficulty": None, "range": None})

    def test_only_the_last_window_of_takes_counts_for_genre(self):
        # 40 older Jazz takes, then 30 newer Soul. Without the window Jazz
        # would win on count; with it, only the 30 newest are read.
        for _ in range(40):
            take(self.me, genre="Jazz")
        for _ in range(DEFAULTS_WINDOW):
            take(self.me, genre="Soul")
        self.assertEqual(coach_defaults(self.me, "singz")["genre"], "Soul")

    def test_the_read_is_a_fixed_number_of_queries(self):
        take(self.me, genre="Soul", difficulty="builder", range_class="tenor")
        with CaptureQueriesContext(connection) as few:
            coach_defaults(self.me, "singz")
        for i in range(19):
            take(self.me, genre="Soul" if i % 2 else "R&B", difficulty="builder")
        with CaptureQueriesContext(connection) as many:
            coach_defaults(self.me, "singz")
        self.assertEqual(len(few.captured_queries), len(many.captured_queries))
        self.assertLessEqual(len(many.captured_queries), 2)


class CoachDefaultsEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.client.force_authenticate(self.user)
        m = membership_for(self.user); m.tier = TIER_STATZ; m.save()

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    def test_the_coach_get_carries_defaults_for_a_new_member(self, _k):
        resp = self.client.get("/api/singz/coach/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["defaults"],
                         {"genre": None, "difficulty": None, "range": None})

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    def test_the_coach_get_reports_the_members_history(self, _k):
        take(self.user, genre="Soul", difficulty="performer", range_class="alto")
        resp = self.client.get("/api/singz/coach/")
        self.assertEqual(resp.data["defaults"],
                         {"genre": "Soul", "difficulty": "performer", "range": "alto"})
