"""Taking money out — the only path where funds leave the platform.

Most of these are about what happens when it goes WRONG, because that is where
the money is. A withdrawal that succeeds is one line; a withdrawal that fails
after the wallet was debited and never gives it back is somebody's rent.

The provider is stubbed throughout — no key exists in CI or on a dev box — so
these pin the protocol we BELIEVE in and cannot tell us we believed the wrong
thing. `tools/payout_live_check.sh` is the check that can. What they DO pin is
every decision on our side of the call, which is all of the dangerous ones.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from .catalog import PAYOUT_MAX_CENTS, PAYOUT_MIN_CENTS
from .models import Payout, PayoutAccount, Transaction, wallet_for

User = get_user_model()
URL = "/api/economy/payouts/"


class FakeTransfer:
    id = "tr_stub_1"


def ok_stripe():
    """A provider that accepts, and records what it was asked for.

    `_stripe()` is CALLED by the code, so the client is `.return_value` — the
    first version of this stubbed the factory itself, and every attribute came
    back a MagicMock that Django then tried to resolve as a query expression.
    """
    factory = patch("apps.economy.payouts._stripe").start()
    client = factory.return_value
    client.Transfer.create.return_value = FakeTransfer()
    return client


class PayoutBase(TestCase):
    def setUp(self):
        self.u = User.objects.create_user(username="earner", password="pw",
                                          email="earner@example.com")
        self.client.force_login(self.u)
        w = wallet_for(self.u)
        w.money_cents = 10_000          # $100
        w.save()
        PayoutAccount.objects.create(user=self.u, account_id="acct_1",
                                     payouts_enabled=True)
        self.addCleanup(patch.stopall)


class ItPaysOut(PayoutBase):
    def test_a_withdrawal_debits_the_wallet_and_records_the_row(self):
        st = ok_stripe()
        r = self.client.post(URL, {"amount_cents": 5000}, "application/json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(wallet_for(self.u).money_cents, 5000)
        p = Payout.objects.get()
        self.assertEqual((p.amount_cents, p.status), (5000, Payout.STATUS_PAID))
        self.assertEqual(p.provider_ref, "tr_stub_1")
        st.Transfer.create.assert_called_once()

    def test_the_provider_is_told_the_net_and_given_our_idempotency_key(self):
        """The key is what stops a retried request becoming a second payment."""
        st = ok_stripe()
        self.client.post(URL, {"amount_cents": 5000}, "application/json")
        kwargs = st.Transfer.create.call_args.kwargs
        p = Payout.objects.get()
        self.assertEqual(kwargs["amount"], p.net_cents)
        self.assertEqual(kwargs["idempotency_key"], p.idempotency_key)
        self.assertEqual(kwargs["destination"], "acct_1")

    def test_it_writes_a_ledger_row_of_its_own_kind(self):
        """Its own kind because it is the only movement that is not revenue,
        not a reward and not internal — totalling it as any of those would
        overstate all three."""
        ok_stripe()
        self.client.post(URL, {"amount_cents": 5000}, "application/json")
        t = Transaction.objects.filter(kind=Transaction.KIND_PAYOUT).get()
        self.assertEqual(t.amount_cents, -5000)

    def test_withdrawing_everything_is_the_default(self):
        ok_stripe()
        r = self.client.post(URL, {}, "application/json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(wallet_for(self.u).money_cents, 0)


class WhenItFails(PayoutBase):
    def test_a_refused_transfer_gives_the_money_back(self):
        """The property the whole file is arranged around."""
        st = patch("apps.economy.payouts._stripe").start()
        st.return_value.Transfer.create.side_effect = Exception("bank rejected the account")
        r = self.client.post(URL, {"amount_cents": 5000}, "application/json")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(wallet_for(self.u).money_cents, 10_000)   # all of it

    def test_a_refusal_says_what_the_provider_said(self):
        """"It didn't work" is not something a member can act on."""
        st = patch("apps.economy.payouts._stripe").start()
        st.return_value.Transfer.create.side_effect = Exception("bank rejected the account")
        r = self.client.post(URL, {"amount_cents": 5000}, "application/json")
        self.assertIn("bank rejected the account", r.json()["detail"])
        self.assertEqual(Payout.objects.get().status, Payout.STATUS_FAILED)

    def test_the_return_is_written_down_too(self):
        """A balance that changes with nothing behind it is what LogZ exists
        to stop — and that applies to money coming BACK as much as going."""
        st = patch("apps.economy.payouts._stripe").start()
        st.return_value.Transfer.create.side_effect = Exception("nope")
        self.client.post(URL, {"amount_cents": 5000}, "application/json")
        rows = Transaction.objects.filter(kind=Transaction.KIND_PAYOUT)
        self.assertEqual(rows.count(), 2)                       # out, then back
        self.assertEqual(sum(t.amount_cents for t in rows), 0)  # net zero


class WhatItRefuses(PayoutBase):
    def test_under_the_minimum(self):
        ok_stripe()
        r = self.client.post(URL, {"amount_cents": PAYOUT_MIN_CENTS - 1},
                             "application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(wallet_for(self.u).money_cents, 10_000)

    def test_over_the_maximum(self):
        ok_stripe()
        r = self.client.post(URL, {"amount_cents": PAYOUT_MAX_CENTS + 1},
                             "application/json")
        self.assertEqual(r.status_code, 400)

    def test_more_than_the_balance(self):
        ok_stripe()
        r = self.client.post(URL, {"amount_cents": 50_000}, "application/json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(wallet_for(self.u).money_cents, 10_000)

    def test_with_no_payout_account(self):
        ok_stripe()
        PayoutAccount.objects.all().delete()
        r = self.client.post(URL, {"amount_cents": 5000}, "application/json")
        self.assertEqual(r.status_code, 409)
        self.assertIn("Connect a payout account", r.json()["detail"])

    def test_while_the_provider_has_not_approved_the_account(self):
        """Reaching the end of the form is not the same fact as 'money can be
        sent', and only one of them is safe to act on."""
        ok_stripe()
        PayoutAccount.objects.update(payouts_enabled=False,
                                     requirements=["a photo of your ID"])
        r = self.client.post(URL, {"amount_cents": 5000}, "application/json")
        self.assertEqual(r.status_code, 409)
        self.assertIn("photo of your ID", r.json()["detail"])

    def test_when_no_provider_is_configured_at_all(self):
        with patch("apps.economy.payouts._stripe", return_value=None):
            r = self.client.post(URL, {"amount_cents": 5000}, "application/json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(wallet_for(self.u).money_cents, 10_000)

    def test_a_nonsense_amount(self):
        ok_stripe()
        r = self.client.post(URL, {"amount_cents": "all of it"}, "application/json")
        self.assertEqual(r.status_code, 400)


class TheQuote(PayoutBase):
    """Stated before the button, like every other price in this app."""

    def test_it_answers_before_anything_is_pressed(self):
        ok_stripe()
        q = self.client.get(URL).json()["quote"]
        self.assertEqual(q["balance_cents"], 10_000)
        self.assertEqual(q["min_cents"], PAYOUT_MIN_CENTS)
        self.assertTrue(q["can_withdraw"])

    def test_it_says_WHY_not_rather_than_going_quiet(self):
        """A greyed-out button is not a fact somebody can act on."""
        ok_stripe()
        w = wallet_for(self.u)
        w.money_cents = 100
        w.save()
        q = self.client.get(URL).json()["quote"]
        self.assertFalse(q["can_withdraw"])
        self.assertTrue(any("minimum" in r for r in q["why_not"]))

    def test_the_fee_is_published_even_when_it_is_zero(self):
        """Zero is a price and belongs on screen: a member should not have to
        press it to learn we take nothing."""
        ok_stripe()
        q = self.client.get(URL).json()["quote"]
        self.assertIn("fee_cents", q)
        self.assertEqual(q["net_cents"], q["balance_cents"] - q["fee_cents"])

    def test_it_is_yours_alone(self):
        ok_stripe()
        other = User.objects.create_user(username="nosy", password="pw")
        self.client.post(URL, {"amount_cents": 5000}, "application/json")
        self.client.force_login(other)
        self.assertEqual(self.client.get(URL).json()["payouts"], [])
