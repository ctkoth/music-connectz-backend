"""Daily habit reminder notifications.

Sends in-app notifications to users for habits they haven't completed today,
respecting their notifications_enabled preference.

Usage: python manage.py check_habits_and_notify [--dry-run]
"""
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth.models import User

from apps.economy.models import Habit, Notification, UserPreferences


class Command(BaseCommand):
    help = "Send daily habit reminder notifications to users who opted in"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be sent without actually creating notifications",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Get all daily habits whose users have opted in for notifications
        daily_habits = Habit.objects.filter(frequency="daily").select_related("user")

        notified_count = 0
        skipped_count = 0
        errors = []

        for habit in daily_habits:
            try:
                # Skip if user doesn't have preferences (shouldn't happen)
                try:
                    prefs = UserPreferences.objects.get(user=habit.user)
                except UserPreferences.DoesNotExist:
                    skipped_count += 1
                    continue

                # Skip if user has disabled notifications
                if not prefs.notifications_enabled:
                    skipped_count += 1
                    continue

                # Skip if already completed today
                if habit.last_completed and habit.last_completed >= today_start:
                    skipped_count += 1
                    continue

                # Prepare notification
                text = f"Time to complete your habit: {habit.title}"

                if dry_run:
                    self.stdout.write(
                        f"[DRY RUN] Would notify {habit.user.username}: {text}"
                    )
                    notified_count += 1
                else:
                    # Create notification
                    notification = Notification.objects.create(
                        user=habit.user,
                        kind="habit_reminder",
                        text=text,
                        item_id=f"habit:{habit.id}",
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"✓ Notified {habit.user.username}: {habit.title}"
                        )
                    )
                    notified_count += 1

            except Exception as e:
                errors.append(f"Error processing habit {habit.id}: {str(e)}")
                self.stdout.write(self.style.ERROR(f"✗ Error: {str(e)}"))

        # Summary
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"✓ Sent {notified_count} habit reminders")
        )
        self.stdout.write(self.style.WARNING(f"⊘ Skipped {skipped_count} users"))

        if errors:
            self.stdout.write(self.style.ERROR(f"✗ {len(errors)} errors occurred:"))
            for error in errors:
                self.stdout.write(f"  {error}")
