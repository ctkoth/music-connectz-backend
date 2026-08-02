"""Seed the print-on-demand blank catalog. Idempotent — run it on every deploy.

    python manage.py seed_pod

Updates existing rows in place rather than replacing them, so re-running after a
price change reprices only what changed and leaves every listing intact.
"""
from django.core.management.base import BaseCommand

from apps.economy.models import PrintProduct
from apps.economy.pod import provider_name, seed_blanks, suggested_price_cents


class Command(BaseCommand):
    help = "Create or update the print-on-demand blank products."

    def handle(self, *args, **options):
        created = seed_blanks()
        products = PrintProduct.objects.filter(active=True)

        self.stdout.write(self.style.MIGRATE_HEADING("\nBlanks"))
        for p in products:
            self.stdout.write(
                f"  {p.key:<14} {p.name:<28} "
                f"cost ${p.landed_cost_cents / 100:>6.2f}   "
                f"suggested ${suggested_price_cents(p) / 100:>6.2f}"
            )
        provider = provider_name()
        self.stdout.write(
            f"\n  {products.count()} blanks ({created} new). Provider: {provider}."
        )
        if provider == "manual":
            self.stdout.write(
                "  No POD provider configured — orders rest at 'pending' on the seller's\n"
                "  fulfilment list. Set POD_PROVIDER + PRINTFUL_API_KEY / PRINTIFY_API_KEY\n"
                "  to submit them automatically."
            )
