"""Release CollabZ escrow deals whose auto-release window has passed.

Run on a schedule (cron / Render cron job), e.g. hourly:
    python manage.py release_due_collabs

A fully-funded deal auto-releases ESCROW_AUTO_RELEASE_DAYS after funding so
recipients are never stuck behind an unresponsive payer. Disputed deals are
skipped (their auto_release_at is cleared when the dispute opens).
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.economy.collab import release_deal
from apps.economy.models import CollabDeal


class Command(BaseCommand):
    help = "Release CollabZ escrow deals past their auto-release window."

    def handle(self, *args, **options):
        due = CollabDeal.objects.filter(
            status__in=[CollabDeal.STATUS_FUNDED, CollabDeal.STATUS_DELIVERED],
            auto_release_at__isnull=False,
            auto_release_at__lte=timezone.now(),
        )
        n = 0
        for deal in due:
            release_deal(deal, note="auto-release (scheduled)")
            n += 1
        self.stdout.write(self.style.SUCCESS(f"Auto-released {n} collab deal(s)."))
