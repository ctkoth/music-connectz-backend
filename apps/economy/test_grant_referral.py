from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.economy.models import (
    REFERRAL_REWARD_JOINEE_SPINAZ,
    REFERRAL_REWARD_REFERRER_SPINAZ,
    Referral,
    wallet_for,
)

User = get_user_model()


def run(*args):
    out, err = StringIO(), StringIO()
    call_command("grant_referral", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


class GrantReferralTests(TestCase):
    """Crediting a referral that happened without the invite link."""

    def setUp(self):
        self.referrer = User.objects.create_user("K-Oth", "k@e.com", "pw12345678")
        self.joinee = User.objects.create_user("steve515", "s@e.com", "pw12345678")

    def test_pays_both_sides_and_links_them(self):
        out, _ = run("K-Oth", "steve515")
        self.assertIn("✓", out)
        self.assertTrue(Referral.objects.filter(referrer=self.referrer, joinee=self.joinee).exists())
        self.assertEqual(wallet_for(self.referrer).spinaz, REFERRAL_REWARD_REFERRER_SPINAZ)
        self.assertEqual(wallet_for(self.joinee).spinaz, REFERRAL_REWARD_JOINEE_SPINAZ)

    def test_resolves_by_email_too(self):
        run("k@e.com", "s@e.com")
        self.assertTrue(Referral.objects.filter(referrer=self.referrer, joinee=self.joinee).exists())

    def test_username_match_is_case_insensitive(self):
        run("k-oth", "STEVE515")
        self.assertTrue(Referral.objects.filter(referrer=self.referrer, joinee=self.joinee).exists())

    def test_running_it_twice_does_not_pay_twice(self):
        run("K-Oth", "steve515")
        out, _ = run("K-Oth", "steve515")
        self.assertIn("Already credited", out)
        self.assertEqual(Referral.objects.count(), 1)
        self.assertEqual(wallet_for(self.referrer).spinaz, REFERRAL_REWARD_REFERRER_SPINAZ)
        self.assertEqual(wallet_for(self.joinee).spinaz, REFERRAL_REWARD_JOINEE_SPINAZ)

    def test_will_not_steal_a_joinee_from_another_referrer(self):
        other = User.objects.create_user("someone", "o@e.com", "pw12345678")
        run("someone", "steve515")
        _, err = run("K-Oth", "steve515")
        self.assertIn("already referred by someone", err)
        self.assertEqual(Referral.objects.get(joinee=self.joinee).referrer, other)
        self.assertEqual(wallet_for(self.referrer).spinaz, 0)

    def test_dry_run_pays_nobody(self):
        out, _ = run("K-Oth", "steve515", "--dry-run")
        self.assertIn("Would credit", out)
        self.assertFalse(Referral.objects.exists())
        self.assertEqual(wallet_for(self.referrer).spinaz, 0)

    def test_self_referral_refused(self):
        _, err = run("K-Oth", "K-Oth")
        self.assertIn("refer themselves", err)
        self.assertFalse(Referral.objects.exists())

    def test_unknown_user_names_which_side_is_missing(self):
        _, err = run("K-Oth", "nobody")
        self.assertIn("No joinee matches 'nobody'", err)
        self.assertFalse(Referral.objects.exists())
