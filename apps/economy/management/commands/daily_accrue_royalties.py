"""Management command: daily_accrue_royalties

Run this command daily (early morning UTC preferred) to accrue playlist
royalties from ListenProgress records. Reads plays from the previous calendar
day and creates RoyaltyEntry + Transaction records per creator.

Safe to re-run on the same date (idempotent based on date in source field).

Usage:
    python manage.py daily_accrue_royalties
    python manage.py daily_accrue_royalties --date 2025-09-27
"""
from datetime import datetime, date, timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.economy.playlistz import accrue_playlist_royalties_for_date


class Command(BaseCommand):
    help = "Accrue playlist royalties from yesterday's ListenProgress records"

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            help="Date to accrue (YYYY-MM-DD). Default: yesterday.",
        )

    def handle(self, *args, **options):
        # Parse date argument
        date_str = options.get("date")
        if date_str:
            try:
                target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError as e:
                raise CommandError(f"Invalid date format: {date_str}. Use YYYY-MM-DD.")
        else:
            # Default to yesterday
            target_date = (timezone.now() - timedelta(days=1)).date()

        self.stdout.write(f"Accruing playlist royalties for {target_date}...")

        try:
            result = accrue_playlist_royalties_for_date(target_date)
            self.stdout.write(
                self.style.SUCCESS(
                    f"✓ Accrued for {result['creators']} creators "
                    f"({result['accruals']} plays, "
                    f"${result['total_cents'] / 100:.2f} total)"
                )
            )
        except Exception as e:
            raise CommandError(f"Failed to accrue royalties: {str(e)}")
