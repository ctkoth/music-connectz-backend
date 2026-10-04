"""Push notifications: about you, asked for, capped, quiet at night."""
from datetime import datetime, timedelta, timezone as dt_tz
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import Habit, Notification, PushLog, PushSubscription, UserPreferences, notify
from .push import DAILY_CAP, _quiet_now, should_send, url_for

User = get_user_model()
ON = dict(VAPID_PUBLIC_KEY="pub", VAPID_PRIVATE_KEY="priv", VAPID_SUBJECT="mailto:t@e.com", PUSH_SYNC=True)
SUB = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "k" * 80, "auth": "a" * 20}}


class Base(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("pushee", "p@e.com", "pw-Long-enough-1")
        self.them = User.objects.create_user("rater", "r@e.com", "pw-Long-enough-1")
        self.c = APIClient()
        self.c.force_authenticate(self.me)

    def subscribe(self, tz="UTC"):
        return self.c.post("/api/economy/push/subscribe/", {"subscription": SUB, "tz": tz}, format="json")


class OffUntilConfiguredTests(Base):
    def test_without_keys_it_says_so_and_offers_nothing(self):
        d = self.c.get("/api/economy/push/").data
        self.assertFalse(d["enabled"])
        self.assertEqual(d["public_key"], "")
        self.assertEqual(self.subscribe().status_code, 503)

    @patch("pywebpush.webpush")
    def test_without_keys_a_notification_pushes_nothing(self, wp):
        notify(self.me, "rate", "rated 8", actor=self.them)
        wp.assert_not_called()


@override_settings(**ON)
class SubscribeTests(Base):
    def test_a_browser_subscribes_and_its_timezone_is_kept(self):
        r = self.subscribe("America/Los_Angeles")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["devices"], 1)
        self.assertEqual(UserPreferences.objects.get(user=self.me).push_tz, "America/Los_Angeles")

    def test_the_same_browser_twice_is_one_device(self):
        self.subscribe()
        self.subscribe()
        self.assertEqual(PushSubscription.objects.count(), 1)

    def test_junk_is_refused(self):
        r = self.c.post("/api/economy/push/subscribe/", {"subscription": {"endpoint": "http://x"}}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_a_bad_timezone_is_ignored_not_stored(self):
        self.subscribe("Mars/Olympus")
        self.assertEqual(UserPreferences.objects.get(user=self.me).push_tz, "")

    def test_unsubscribe_removes_it(self):
        self.subscribe()
        self.c.delete("/api/economy/push/subscribe/", {"endpoint": SUB["endpoint"]}, format="json")
        self.assertEqual(PushSubscription.objects.count(), 0)

    def test_the_public_key_is_served_and_the_private_one_never(self):
        d = self.c.get("/api/economy/push/").data
        self.assertEqual(d["public_key"], "pub")
        self.assertNotIn("priv", str(d))


@override_settings(**ON)
class WhatPushesTests(Base):
    def setUp(self):
        super().setUp()
        self.subscribe(tz="UTC")
        # Quiet hours off (start == end) so these don't depend on what time
        # the suite happens to run — QuietHoursTests covers quiet hours.
        UserPreferences.objects.filter(user=self.me).update(quiet_start=0, quiet_end=0)

    def notify(self, *a, **kw):
        # Push is sent after commit; TestCase never commits, so run them.
        with self.captureOnCommitCallbacks(execute=True):
            return notify(*a, **kw)

    @patch("pywebpush.webpush")
    def test_a_rating_reaches_the_phone_and_lands_on_the_post(self, wp):
        self.notify(self.me, "rate", "@rater rated your post 8/10", actor=self.them, item_id="post:12")
        self.assertEqual(wp.call_count, 1)
        import json
        payload = json.loads(wp.call_args.kwargs["data"])
        self.assertEqual(payload["url"], "/p/12")
        self.assertIn("8/10", payload["body"])

    @patch("pywebpush.webpush")
    def test_likes_are_off_unless_switched_on(self, wp):
        self.notify(self.me, "like", "liked", actor=self.them)
        wp.assert_not_called()
        self.c.post("/api/economy/push/prefs/", {"kinds": {"like": True}}, format="json")
        self.notify(self.me, "like", "liked again", actor=self.them)
        self.assertEqual(wp.call_count, 1)

    @patch("pywebpush.webpush")
    def test_a_muted_kind_stays_quiet(self, wp):
        self.c.post("/api/economy/push/prefs/", {"kinds": {"rate": False}}, format="json")
        self.notify(self.me, "rate", "rated", actor=self.them)
        wp.assert_not_called()

    @patch("pywebpush.webpush")
    def test_a_broadcast_never_buzzes(self, wp):
        # Parcel's campaign DMs are bulk_create — no signal, no push.
        Notification.objects.bulk_create([Notification(user=self.me, actor=self.them, kind="message", text="📣")])
        wp.assert_not_called()

    @patch("pywebpush.webpush")
    def test_the_daily_cap_holds(self, wp):
        for i in range(DAILY_CAP + 2):
            self.notify(self.me, "rate", f"rated {i}", actor=self.them)
        self.assertEqual(wp.call_count, DAILY_CAP)

    @patch("pywebpush.webpush")
    def test_notifications_off_means_no_push(self, wp):
        p = UserPreferences.objects.get(user=self.me)
        p.notifications_enabled = False
        p.save()
        self.notify(self.me, "rate", "rated", actor=self.them)
        wp.assert_not_called()

    def test_a_dead_subscription_is_deleted(self):
        from pywebpush import WebPushException

        class Gone:
            status_code = 410
        with patch("pywebpush.webpush", side_effect=WebPushException("gone", response=Gone())):
            self.notify(self.me, "rate", "rated", actor=self.them)
        self.assertEqual(PushSubscription.objects.count(), 0)

    def test_a_failing_push_never_breaks_what_caused_it(self):
        with patch("pywebpush.webpush", side_effect=RuntimeError("network down")):
            n = self.notify(self.me, "rate", "rated", actor=self.them)
        self.assertIsNotNone(n.pk)


class QuietHoursTests(Base):
    def prefs(self, tz, start=22, end=8):
        p, _ = UserPreferences.objects.get_or_create(user=self.me)
        p.push_tz, p.quiet_start, p.quiet_end = tz, start, end
        p.save()
        return p

    def test_late_night_in_their_timezone_is_quiet(self):
        p = self.prefs("America/Los_Angeles")
        # 07:00 UTC is 00:00 in Los Angeles (PDT).
        self.assertTrue(_quiet_now(p, datetime(2026, 7, 1, 7, tzinfo=dt_tz.utc)))
        self.assertFalse(_quiet_now(p, datetime(2026, 7, 1, 20, tzinfo=dt_tz.utc)))

    def test_no_timezone_means_us_eastern_not_utc(self):
        p = self.prefs("")
        # 03:00 UTC is 11pm in New York — quiet. 15:00 UTC is 11am — not.
        self.assertTrue(_quiet_now(p, datetime(2026, 7, 1, 3, tzinfo=dt_tz.utc)))
        self.assertFalse(_quiet_now(p, datetime(2026, 7, 1, 15, tzinfo=dt_tz.utc)))

    def test_the_app_reports_the_browsers_zone_without_push(self):
        r = self.c.post("/api/economy/push/prefs/", {"tz": "America/Chicago"}, format="json")
        self.assertEqual(r.data["quiet"]["tz"], "America/Chicago")
        self.assertFalse(r.data["quiet"]["tz_guessed"])

    def test_an_unknown_zone_is_said_to_be_a_guess(self):
        self.assertTrue(self.c.get("/api/economy/push/").data["quiet"]["tz_guessed"])

    def test_quiet_hours_block_a_push(self):
        self.prefs("UTC", start=0, end=23)
        self.assertEqual(should_send(self.me, "rate", datetime(2026, 7, 1, 12, tzinfo=dt_tz.utc)), "quiet hours")

    def test_hours_must_be_real_hours(self):
        r = self.c.post("/api/economy/push/prefs/", {"quiet_start": 25}, format="json")
        self.assertEqual(r.status_code, 400)


class UrlTests(TestCase):
    def test_each_kind_lands_somewhere_real(self):
        u = User.objects.create_user("x", "x@e.com", "pw-Long-enough-1")
        self.assertEqual(url_for(Notification(user=u, kind="message", text="")), "/message")
        self.assertEqual(url_for(Notification(user=u, kind="habit_reminder", text="", item_id="habit:3")), "/journal")
        self.assertEqual(url_for(Notification(user=u, kind="follow", text="", actor=u)), "/u/x")
        self.assertEqual(url_for(Notification(user=u, kind="system", text="")), "/")


class HabitReminderTests(TestCase):
    """Hourly, at 6pm in the member's own timezone, once a day."""

    def setUp(self):
        self.u = User.objects.create_user("habitual", "h@e.com", "pw-Long-enough-1")
        self.h = Habit.objects.create(user=self.u, title="Vocal warmup", frequency="daily")
        UserPreferences.objects.create(user=self.u, push_tz="America/New_York")

    def run_at(self, utc_hour):
        at = datetime(2026, 7, 1, utc_hour, 5, tzinfo=dt_tz.utc)
        with patch("django.utils.timezone.now", return_value=at):
            call_command("check_habits_and_notify", stdout=StringIO())

    def reminders(self):
        return Notification.objects.filter(user=self.u, kind="habit_reminder").count()

    def test_it_waits_for_their_evening(self):
        self.run_at(12)            # 8am in New York
        self.assertEqual(self.reminders(), 0)
        self.run_at(22)            # 6pm in New York (EDT)
        self.assertEqual(self.reminders(), 1)

    def test_once_a_day_even_if_the_cron_fires_twice(self):
        self.run_at(22)
        self.run_at(22)
        self.assertEqual(self.reminders(), 1)

    def test_done_today_means_no_reminder(self):
        self.h.last_completed = datetime(2026, 7, 1, 20, tzinfo=dt_tz.utc)
        self.h.save()
        self.run_at(22)
        self.assertEqual(self.reminders(), 0)

    def test_no_timezone_is_treated_as_us_eastern(self):
        UserPreferences.objects.filter(user=self.u).update(push_tz="")
        self.run_at(18)            # 2pm in New York: not yet
        self.assertEqual(self.reminders(), 0)
        self.run_at(22)            # 6pm in New York
        self.assertEqual(self.reminders(), 1)
