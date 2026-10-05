"""Retake reminders — the trial's way back. See apps/economy/retake.py."""
from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy import retake
from apps.economy.models import RetakeReminder, TrialTake

REMIND = "/api/economy/trial/remind/"
STOP = "/api/economy/trial/remind/stop/"
SMTP = override_settings(EMAIL_HOST="smtp.example.com",
                         EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")


def take(token="tok1", score=6, anon="browser-a", app="singz", **kw):
    return TrialTake.objects.create(
        token=token, app_key=app, anon_id=anon, scored=score is not None,
        result={"score": score, "verdict": "Solid pitch.", "fixes": ["Breath ran out on line 3"],
                "next_drill": "Hiss for 20s on one breath"}, **kw)


@SMTP
class RemindTests(TestCase):
    def setUp(self):
        self.c = APIClient()

    def test_sends_the_score_now_and_arms_the_schedule(self):
        take()
        r = self.c.post(REMIND, {"claim_token": "tok1", "email": "a@b.co"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertIn("6/10", m.subject)
        self.assertIn("Hiss for 20s", m.body)
        self.assertIn("/api/economy/trial/remind/stop/?t=", m.body)
        self.assertIn("List-Unsubscribe", m.extra_headers)
        self.assertEqual(RetakeReminder.objects.get().stage, RetakeReminder.STAGE_SCORE)

    def test_the_schedule_is_stated_before_they_type(self):
        self.assertIn("day 3", self.c.get(REMIND).data["schedule"])
        self.assertTrue(self.c.get(REMIND).data["ready"])

    def test_pressing_twice_sends_once(self):
        take()
        self.c.post(REMIND, {"claim_token": "tok1", "email": "a@b.co"}, format="json")
        self.c.post(REMIND, {"claim_token": "tok1", "email": "A@b.co"}, format="json")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(RetakeReminder.objects.count(), 1)

    def test_needs_a_real_scored_take(self):
        take(score=None)
        for tok in ("tok1", "nope", ""):
            r = self.c.post(REMIND, {"claim_token": tok, "email": "a@b.co"}, format="json")
            self.assertEqual(r.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_an_expired_take_cannot_arm_one(self):
        t = take()
        TrialTake.objects.filter(pk=t.pk).update(created_at=timezone.now() - timedelta(days=60))
        r = self.c.post(REMIND, {"claim_token": "tok1", "email": "a@b.co"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_rejects_a_non_address(self):
        take()
        r = self.c.post(REMIND, {"claim_token": "tok1", "email": "not an email"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_one_inbox_cannot_be_flooded(self):
        for i in range(retake.PER_EMAIL_PER_DAY + 1):
            take(token=f"t{i}", anon=f"b{i}")
        codes = [self.c.post(REMIND, {"claim_token": f"t{i}", "email": "victim@x.co"},
                             format="json").status_code
                 for i in range(retake.PER_EMAIL_PER_DAY + 1)]
        self.assertEqual(codes[-1], 429)
        self.assertEqual(len(mail.outbox), retake.PER_EMAIL_PER_DAY)

    def test_a_failed_send_arms_nothing(self):
        take()
        with self.settings(EMAIL_BACKEND="apps.economy.test_retake.Broken"):
            r = self.c.post(REMIND, {"claim_token": "tok1", "email": "a@b.co"}, format="json")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(RetakeReminder.objects.get().stop_reason, "failed")
        self.assertEqual(list(retake.due(timezone.now() + timedelta(days=30))), [])


class Broken:
    def __init__(self, *a, **k): pass

    def send_messages(self, msgs):
        raise OSError("smtp down")


class NoMailTests(TestCase):
    @override_settings(EMAIL_HOST="")
    def test_no_email_host_means_no_field_and_no_pretending(self):
        take()
        c = APIClient()
        self.assertFalse(c.get(REMIND).data["ready"])
        r = c.post(REMIND, {"claim_token": "tok1", "email": "a@b.co"}, format="json")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(RetakeReminder.objects.count(), 0)


@SMTP
class ScheduleTests(TestCase):
    def arm(self, days_ago):
        t = take()
        return RetakeReminder.objects.create(
            email="a@b.co", app_key="singz", trial_take=t, anon_id="browser-a", token="rt",
            stage=RetakeReminder.STAGE_SCORE, armed_at=timezone.now() - timedelta(days=days_ago))

    def test_nothing_before_day_three(self):
        self.arm(2)
        self.assertEqual(retake.run_due(), (0, 0))

    def test_day_three_then_day_seven_then_nothing(self):
        r = self.arm(3.1)
        self.assertEqual(retake.run_due(), (1, 0))
        self.assertIn("retake_d3", mail.outbox[-1].body)
        self.assertIn("6/10", mail.outbox[-1].subject)
        self.assertEqual(retake.run_due(), (0, 0))  # not twice
        RetakeReminder.objects.filter(pk=r.pk).update(armed_at=timezone.now() - timedelta(days=7.1))
        self.assertEqual(retake.run_due(), (1, 0))
        self.assertIn("retake_d7", mail.outbox[-1].body)
        RetakeReminder.objects.filter(pk=r.pk).update(armed_at=timezone.now() - timedelta(days=90))
        self.assertEqual(retake.run_due(), (0, 0))
        self.assertEqual(len(mail.outbox), 2)

    def test_a_new_take_from_the_same_browser_restarts_the_clock(self):
        r = self.arm(3.1)
        newer = take(token="tok2", score=8)
        retake.rearm_for(newer)
        self.assertEqual(retake.run_due(), (0, 0))
        r.refresh_from_db()
        self.assertEqual(r.trial_take_id, newer.id)

    def test_failures_retry_then_stop(self):
        r = self.arm(3.1)
        with self.settings(EMAIL_BACKEND="apps.economy.test_retake.Broken"):
            for _ in range(retake.MAX_FAILURES):
                self.assertEqual(retake.run_due(), (0, 1))
        r.refresh_from_db()
        self.assertEqual((r.stage, r.stop_reason), (RetakeReminder.STAGE_SCORE, "failed"))
        self.assertEqual(retake.run_due(), (0, 0))

    def test_stop_link_get_changes_nothing_and_post_stops(self):
        r = self.arm(3.1)
        c = APIClient()
        self.assertEqual(c.get(STOP, {"t": "rt"}).status_code, 200)
        r.refresh_from_db()
        self.assertIsNone(r.stopped_at)
        c.post(f"{STOP}?t=rt")
        r.refresh_from_db()
        self.assertEqual(r.stop_reason, "unsubscribed")
        self.assertEqual(retake.run_due(), (0, 0))
        self.assertEqual(c.get(STOP, {"t": "wrong"}).status_code, 400)

    def test_joining_stops_them(self):
        self.arm(3.1)
        c = APIClient()
        r = c.post("/api/auth/register/", {"username": "newbie", "email": "A@b.co",
                                           "password": "a-Long-unusual-pass-91"}, format="json")
        self.assertIn(r.status_code, (200, 201), r.data)
        self.assertEqual(RetakeReminder.objects.get().stop_reason, "joined")
        self.assertEqual(retake.run_due(), (0, 0))

    def test_the_command_says_when_it_attempted_nothing(self):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        with self.settings(EMAIL_HOST=""):
            call_command("send_retake_reminders", stdout=out)
        self.assertIn("no reminders attempted", out.getvalue())


@SMTP
class TrialResponseTests(TestCase):
    def test_the_trial_response_offers_it(self):
        from unittest import mock
        payload = {"score": 7, "fixes": [], "next_drill": ""}
        with mock.patch("apps.economy.trial.score_take", return_value=(payload, None)), \
             mock.patch("apps.economy.models.mint_score_share", return_value=""):
            from django.core.files.uploadedfile import SimpleUploadedFile
            f = SimpleUploadedFile("t.webm", b"x" * 100, content_type="audio/webm")
            r = APIClient().post("/api/singz/trial/", {"take": f, "anon_id": "b1"})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["remind"]["ready"])
