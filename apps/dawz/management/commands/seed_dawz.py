from django.core.management.base import BaseCommand

from apps.dawz.seed import seed_dawz


class Command(BaseCommand):
    help = "Seed the 7 DawZ proposals (idempotent)."

    def handle(self, *args, **opts):
        n = seed_dawz()
        self.stdout.write(self.style.SUCCESS(f"Seeded {n} new DAW proposals."))
