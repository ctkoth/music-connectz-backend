from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.economy.models import (REFERRAL_REWARD_JOINEE_SPINAZ, REFERRAL_REWARD_MONTHLY_CAP,
                                 REFERRAL_REWARD_REFERRER_SPINAZ, record_referral, wallet_for)

User = get_user_model()


class ReferralMintCapTests(TestCase):
    def setUp(self):
        self.ref = User.objects.create_user("capref", password="pw-12345-xyz")

    def _join(self, i):
        u = User.objects.create_user(f"capj{i}", password="pw-12345-xyz")
        return u, record_referral(self.ref, u)

    def test_referrer_is_paid_up_to_the_cap_then_not(self):
        for i in range(REFERRAL_REWARD_MONTHLY_CAP):
            self._join(i)
        capped = REFERRAL_REWARD_MONTHLY_CAP * REFERRAL_REWARD_REFERRER_SPINAZ
        self.assertEqual(wallet_for(self.ref).spinaz, capped)
        joinee, referral = self._join(99)
        self.assertIsNotNone(referral)                       # still recorded
        self.assertEqual(wallet_for(self.ref).spinaz, capped)  # nothing more minted
        self.assertEqual(wallet_for(joinee).spinaz, REFERRAL_REWARD_JOINEE_SPINAZ)  # joinee still welcomed
