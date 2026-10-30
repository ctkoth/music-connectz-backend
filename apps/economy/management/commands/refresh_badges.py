"""Re-check everyone who holds a TEMPORARY badge, so a lapsed one comes down.

Temporary badges track a window or a median — the Thorough ladder (28 days of
sessions), the coach badges (30 days of takes), Gifted, Sexy, the royalty pair.
They move when the member acts, but a member who simply STOPS never acts again,
so nothing would take a mark off them. This is that something. It only visits
current holders of a temporary badge — earning is covered where the thing
happens — and is idempotent. Hourly, from the same cron service as the habit
reminders. (It was `refresh_thorough` while the ladder was the only window.)
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.economy.models import BADGES, Badge, recheck_badges


class Command(BaseCommand):
    help = "Re-check holders of temporary badges and take back what has lapsed."

    def handle(self, *args, **opts):
        keys = [k for k, s in BADGES.items() if s.get("temporary")]
        ids = set(Badge.objects.filter(key__in=keys).values_list("user_id", flat=True))
        checked = 0
        for user in get_user_model().objects.filter(id__in=ids):
            recheck_badges(user)
            checked += 1
        self.stdout.write(f"badges: {checked} holders of a temporary badge re-checked")
