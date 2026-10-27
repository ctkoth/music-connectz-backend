"""Re-check everyone who holds a Thorough badge, so a lapsed one comes down.

The ladder moves when a session FINISHES, but the rating is a 28-day window: a
member who stops training never finishes another session, so nothing would take
a mark off them. This is that something. It only visits current holders —
earning is already covered by the finish hook — and is idempotent. Hourly,
from the same cron service as the habit reminders.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.economy import thoroughz
from apps.economy.models import Badge, recheck_badges


class Command(BaseCommand):
    help = "Re-check holders of a Thorough badge and take back what has lapsed."

    def handle(self, *args, **opts):
        ids = set(Badge.objects.filter(key__in=thoroughz.KEYS).values_list("user_id", flat=True))
        checked = 0
        for user in get_user_model().objects.filter(id__in=ids):
            recheck_badges(user)
            checked += 1
        self.stdout.write(f"thorough: {checked} holders re-checked")
