"""The public tier ladder serves the numbers MembershipZ used to type in."""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import DEV_TAX, ENERGY_TOPUP_MULT, SUBMISSION_DAILY_CAP


class PublicTiersTests(TestCase):
    def test_the_comparison_numbers_come_from_the_catalog(self):
        tiers = {t["key"]: t for t in APIClient().get("/api/economy/tiers/").json()["tiers"]}
        for key in ("free", "premium", "statz"):
            self.assertEqual(tiers[key]["platform_fee_pct"], round(DEV_TAX[key] * 100, 2))
            self.assertEqual(tiers[key]["energy_per_dollar"], ENERGY_TOPUP_MULT[key])
            self.assertEqual(tiers[key]["scored_per_day"], SUBMISSION_DAILY_CAP[key])
