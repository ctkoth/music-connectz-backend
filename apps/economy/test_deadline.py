"""The 853-second spinner, and what now stops it.

A member sent a 3:05 take and watched "Scoring your take… 853s". Nothing was
broken in any way that reports: no exception, no 500, no dropped connection.
Every part was doing exactly what it was configured to do — and the sum of
those parts was 39 minutes.
"""
import time
from unittest.mock import patch

from django.test import TestCase

from . import gemini_files
from .deadline import COACH_BUDGET_SECONDS, Deadline, Expired


class TheArithmeticThatProducedItTests(TestCase):

    def test_the_poll_loop_alone_could_run_for_860_seconds(self):
        """40 tries x (20s GET timeout + 1.5s sleep). The screenshot said 853,
        which is this loop one tick from the end of its own worst case."""
        old_worst = gemini_files.POLL_TRIES * (20 + gemini_files.POLL_SECONDS)
        self.assertAlmostEqual(old_worst, 860.0)

    def test_the_status_get_no_longer_carries_a_transfer_timeout(self):
        """It reads one line of JSON. 20s meant a stalled poll cost 20 seconds
        to learn nothing, forty times over."""
        self.assertLessEqual(gemini_files.POLL_TIMEOUT, 5)

    def test_the_budget_is_shorter_than_a_person_will_sit_through(self):
        self.assertLessEqual(COACH_BUDGET_SECONDS, 120)


class TheBudgetIsSharedNotAddedTests(TestCase):

    def test_remaining_never_exceeds_what_is_left(self):
        d = Deadline(10)
        self.assertLessEqual(d.remaining(), 10)
        self.assertLessEqual(d.remaining(cap=300), 10,
                             "a cap must never hand back more than the budget has")

    def test_remaining_never_returns_a_timeout_that_cannot_succeed(self):
        """A 0.2s timeout is not a call, it is a guaranteed failure that costs
        a round trip to discover."""
        d = Deadline(10, floor=1.0)
        d.started = time.monotonic() - 9.95
        self.assertGreaterEqual(d.remaining(), 1.0)

    def test_an_expired_budget_reports_rather_than_hangs(self):
        d = Deadline(0.01)
        time.sleep(0.02)
        self.assertTrue(d.expired())
        with self.assertRaises(Expired):
            d.check()

    def test_the_expiry_carries_the_sentence_the_member_reads(self):
        d = Deadline(0.01)
        time.sleep(0.02)
        with self.assertRaises(Expired) as cm:
            d.check("the take was still uploading when the time ran out")
        self.assertIn("still uploading", cm.exception.message)


class ThePollStopsOnTheClockNotTheCountTests(TestCase):

    def test_an_expired_budget_ends_the_poll_immediately(self):
        d = Deadline(0.01)
        time.sleep(0.02)
        with patch.object(gemini_files, "_key", return_value="k"), \
             patch.object(gemini_files.requests, "get") as get:
            ready, why = gemini_files.wait_active({"name": "files/x", "state": "PROCESSING"},
                                                  deadline=d)
        self.assertFalse(ready)
        self.assertTrue(why)
        self.assertEqual(get.call_count, 0,
                         "an out-of-time run must not start another poll")

    def test_a_file_already_active_never_polls_at_all(self):
        ready, why = gemini_files.wait_active({"name": "files/x", "state": "ACTIVE"},
                                              deadline=Deadline(10))
        self.assertTrue(ready)
        self.assertIsNone(why)

    def test_the_poll_timeout_asks_for_no_more_than_the_budget_has(self):
        d = Deadline(2)
        seen = []

        def fake_get(url, timeout=None):
            seen.append(timeout)
            raise gemini_files.requests.RequestException("nope")

        with patch.object(gemini_files, "_key", return_value="k"), \
             patch.object(gemini_files.requests, "get", side_effect=fake_get), \
             patch.object(gemini_files.time, "sleep", lambda s: None):
            gemini_files.wait_active({"name": "files/x", "state": "PROCESSING"}, deadline=d)
        self.assertTrue(seen)
        for t in seen:
            self.assertLessEqual(t, gemini_files.POLL_TIMEOUT)


class TheSpinnerIsNowAnAnswerTests(TestCase):
    """End to end: a run that would have hung returns a reported failure."""

    def test_an_over_budget_run_returns_504_and_says_so(self):
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile

        from . import vocalcoach

        take = SimpleUploadedFile("t.webm", b"x" * 1024, content_type="audio/webm")

        def slow_part(f, mime, size, deadline=None):
            # Stand in for an upload + poll that eats the whole budget, which
            # is exactly what happened: 853 seconds inside wait_active.
            deadline.started -= deadline.total + 1
            return {"inline_data": {"mime_type": mime, "data": ""}}, None, None

        with patch.object(vocalcoach, "_key", return_value="k"), \
             patch.object(vocalcoach, "_media_part", side_effect=slow_part), \
             patch.object(vocalcoach, "generate_content") as gen:
            payload, err = vocalcoach.score_take(
                "singz", take, "audio/webm",
                genre="rock", target="tenor", difficulty="builder")

        self.assertIsNone(payload)
        body, code = err
        self.assertEqual(code, 504)
        self.assertTrue(body["timed_out"])
        self.assertIn("Nothing was charged", body["detail"])
        self.assertGreater(body["waited_seconds"], 0)
        self.assertEqual(gen.call_count, 0,
                         "an out-of-time run must not start the expensive leg")

    def test_a_normal_run_is_untouched_by_any_of_this(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from . import vocalcoach

        take = SimpleUploadedFile("t.webm", b"x" * 1024, content_type="audio/webm")

        class Resp:
            status_code = 200

            @staticmethod
            def json():
                return {"candidates": [{"content": {"parts": [{"text":
                        '{"score": 7, "verdict": "Solid.", "scores": {}}'}]}}]}

        with patch.object(vocalcoach, "_key", return_value="k"), \
             patch.object(vocalcoach, "generate_content",
                          return_value=(Resp(), ["gemini-2.5-flash"])):
            payload, err = vocalcoach.score_take(
                "singz", take, "audio/webm",
                genre="rock", target="tenor", difficulty="builder")
        self.assertIsNone(err)
        self.assertEqual(payload["score"], 7)
