"""Chargebacks, and subscription status changes we never used to hear about.

A dispute means the card issuer has already taken the money back. Before this,
nothing in the codebase referenced `charge.dispute.created` — so somebody could
fund a wallet, spend it into other members' wallets, dispute the charge, and
keep both. Not a leak: a repeatable way to withdraw money that was never paid.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import (PaymentIntent, Wallet, WalletFrozen, check_spendable,
                     pay_between, wallet_for)
from .payments import _apply_subscription_update, _freeze_for_dispute

User = get_user_model()


def member(name, cents=0):
    u = User.objects.create_user(username=name, password="dispute-pass-1")
    if cents:
        w = wallet_for(u)
        w.money_cents = cents
        w.save(update_fields=["money_cents"])
    return u


def funded(user, ref="ch_test_1", cents=50_000):
    return PaymentIntent.objects.create(
        user=user, provider=PaymentIntent.PROVIDER_STRIPE, provider_ref=ref,
        amount_cents=cents, net_cents=cents,
        status=PaymentIntent.STATUS_COMPLETED)


class FreezeTests(TestCase):
    def setUp(self):
        self.u = member("disputer", cents=50_000)
        self.pi = funded(self.u)

    def dispute(self, **over):
        return _freeze_for_dispute(dict(
            {"id": "dp_1", "charge": "ch_test_1", "payment_intent": None}, **over))

    def test_a_dispute_freezes_the_wallet_it_funded(self):
        self.dispute()
        w = wallet_for(self.u)
        self.assertTrue(w.frozen)
        self.assertIn("disputed", w.frozen_reason)
        self.assertIsNotNone(w.frozen_at)

    def test_the_intent_is_marked_disputed(self):
        self.dispute()
        self.pi.refresh_from_db()
        self.assertEqual(self.pi.status, PaymentIntent.STATUS_DISPUTED)

    def test_the_balance_is_not_zeroed(self):
        """Part of it may be money they really deposited, and a dispute is a
        claim rather than a finding. Freezing stops the part that can't be
        undone; the accounting is a human's call."""
        self.dispute()
        self.assertEqual(wallet_for(self.u).money_cents, 50_000)

    def test_it_matches_on_the_payment_intent_reference_too(self):
        other = member("pi_ref_user", cents=1000)
        funded(other, ref="pi_abc")
        _freeze_for_dispute({"id": "dp_2", "payment_intent": "pi_abc",
                             "charge": "ch_unknown"})
        self.assertTrue(wallet_for(other).frozen)

    def test_a_dispute_on_an_unknown_charge_freezes_nobody(self):
        _freeze_for_dispute({"id": "dp_3", "charge": "ch_not_ours",
                             "payment_intent": None})
        self.assertFalse(wallet_for(self.u).frozen)

    def test_a_second_dispute_does_not_overwrite_the_first_reason(self):
        self.dispute()
        first = wallet_for(self.u).frozen_reason
        funded(self.u, ref="ch_test_2", cents=100)
        _freeze_for_dispute({"id": "dp_4", "charge": "ch_test_2",
                             "payment_intent": None})
        self.assertEqual(wallet_for(self.u).frozen_reason, first)


class FrozenWalletCannotSpendTests(TestCase):
    """The freeze has to actually stop money leaving. A flag nothing checks is
    a note to ourselves, not a control."""

    def setUp(self):
        self.payer = member("frozen_payer", cents=50_000)
        self.payee = member("innocent_payee")
        funded(self.payer)
        _freeze_for_dispute({"id": "dp_1", "charge": "ch_test_1",
                             "payment_intent": None})

    def test_pay_between_refuses(self):
        with self.assertRaises(WalletFrozen):
            pay_between(self.payer, self.payee, 1000, note="CollabZ")

    def test_the_payee_receives_nothing(self):
        try:
            pay_between(self.payer, self.payee, 1000, note="CollabZ")
        except WalletFrozen:
            pass
        self.assertEqual(wallet_for(self.payee).money_cents, 0)

    def test_the_error_carries_a_reason_a_member_can_read(self):
        with self.assertRaises(WalletFrozen) as ctx:
            check_spendable(self.payer)
        self.assertIn("on hold", str(ctx.exception))

    def test_an_unfrozen_member_is_unaffected(self):
        ok = member("ordinary", cents=5000)
        pay_between(ok, self.payee, 1000, note="CollabZ")
        self.assertGreater(wallet_for(self.payee).money_cents, 0)

    def test_receiving_money_still_works_while_frozen(self):
        """A freeze stops them spending, not everyone else paying them. Blocking
        incoming would punish the collaborator who did the work."""
        sender = member("sender", cents=5000)
        pay_between(sender, self.payer, 1000, note="CollabZ payout")
        self.assertGreater(wallet_for(self.payer).money_cents, 50_000)


class SubscriptionUpdateTests(TestCase):
    """`customer.subscription.updated` never reached us. A member who fixed
    their card stayed downgraded until they emailed support."""

    def setUp(self):
        self.u = member("subscriber")
        from .models import membership_for
        self.m = membership_for(self.u)
        self.m.stripe_customer_id = "cus_1"
        self.m.tier = "free"
        self.m.save(update_fields=["stripe_customer_id", "tier"])

    def sub(self, status, kind=None):
        obj = {"id": "sub_1", "customer": "cus_1", "status": status}
        if kind:
            obj["items"] = {"data": [{"price": {"metadata": {"kind": kind}}}]}
        return obj

    def test_becoming_active_on_a_premium_price_grants_premium(self):
        _apply_subscription_update(self.sub("active", "premium_sub"))
        self.m.refresh_from_db()
        self.assertEqual(self.m.tier, "premium")

    def test_switching_plans_moves_the_tier(self):
        _apply_subscription_update(self.sub("active", "premium_sub"))
        _apply_subscription_update(self.sub("active", "statz_sub"))
        self.m.refresh_from_db()
        self.assertEqual(self.m.tier, "statz")

    def test_cancelled_drops_to_free(self):
        _apply_subscription_update(self.sub("active", "statz_sub"))
        _apply_subscription_update(self.sub("canceled"))
        self.m.refresh_from_db()
        self.assertEqual(self.m.tier, "free")

    def test_past_due_leaves_the_tier_alone(self):
        """Stripe is still retrying. Downgrading mid-retry punishes an expired
        card, and invoice.payment_failed already handles the real end."""
        _apply_subscription_update(self.sub("active", "premium_sub"))
        _apply_subscription_update(self.sub("past_due"))
        self.m.refresh_from_db()
        self.assertEqual(self.m.tier, "premium")

    def test_a_lifetime_member_is_never_downgraded(self):
        self.m.lifetime = True
        self.m.tier = "statz"
        self.m.save(update_fields=["lifetime", "tier"])
        _apply_subscription_update(self.sub("canceled"))
        self.m.refresh_from_db()
        self.assertEqual(self.m.tier, "statz")

    def test_an_auto_topup_subscription_never_touches_the_tier(self):
        from .models import AutoTopUp
        AutoTopUp.objects.create(user=self.u, stripe_subscription_id="sub_1",
                                 stripe_customer_id="cus_1",
                                 amount_cents=1000, active=True)
        _apply_subscription_update(self.sub("canceled"))
        self.m.refresh_from_db()
        self.assertEqual(self.m.tier, "free")
        self.assertFalse(AutoTopUp.objects.get(stripe_subscription_id="sub_1").active)
