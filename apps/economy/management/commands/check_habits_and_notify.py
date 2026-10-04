"""Daily habit reminders, at the member's own evening.

Runs HOURLY (render.yaml's cron). Each run reminds the members whose local
hour is REMINDER_HOUR and who have a daily habit not done today — so the
reminder lands at 6pm wherever they are, once a day. It used to run once at
08:00 UTC, which is 1am in California and 4am in New York: a reminder that
arrives while somebody is asleep is one they swipe away unread.

A member with no timezone on file yet is treated as US Eastern (New York /
Connecticut) — push.DEFAULT_TZ — rather than UTC, which put the reminder in
the American middle of the night.

The reminder is an in-app Notification, and push.py's signal turns it into a
push for anybody who allowed one — so this command never talks to a push
service itself.

Usage: python manage.py check_habits_and_notify [--dry-run] [--hour N]
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.economy.models import Habit, Notification, UserPreferences
from apps.economy.push import tz_of

REMINDER_HOUR = 18


def _local_now(prefs, now):
    return now.astimezone(tz_of(prefs))


class Command(BaseCommand):
    help = "Remind members of today's unfinished daily habits at 6pm their time (run hourly)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Show what would be sent without creating notifications")
        parser.add_argument("--hour", type=int, default=REMINDER_HOUR,
                            help="Local hour to remind at (default 18)")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        hour = options["hour"]
        now = timezone.now()
        sent = skipped = 0

        habits = Habit.objects.filter(frequency="daily").select_related("user")
        prefs_by_user = {p.user_id: p for p in UserPreferences.objects.filter(
            user_id__in=habits.values_list("user_id", flat=True))}

        for habit in habits:
            prefs = prefs_by_user.get(habit.user_id)
            if prefs is None or not prefs.notifications_enabled:
                skipped += 1
                continue
            local = _local_now(prefs, now)
            if local.hour != hour:
                skipped += 1
                continue
            local_midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
            if habit.last_completed and habit.last_completed >= local_midnight:
                skipped += 1
                continue
            item = f"habit:{habit.id}"
            # Once a day, even if the cron fires twice in the hour.
            if Notification.objects.filter(user=habit.user, kind="habit_reminder", item_id=item,
                                           created_at__gte=now - timedelta(hours=20)).exists():
                skipped += 1
                continue
            text = f"Still on for today: {habit.title}"
            if dry:
                self.stdout.write(f"[DRY RUN] would remind @{habit.user.username}: {text}")
            else:
                Notification.objects.create(user=habit.user, kind="habit_reminder", text=text, item_id=item)
            sent += 1

        self.stdout.write(self.style.SUCCESS(f"Reminded {sent}, skipped {skipped}"))
