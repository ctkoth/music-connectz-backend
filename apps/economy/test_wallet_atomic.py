"""The wallet primitives were a read-modify-write in Python.

    w = wallet_for(user)
    w.spinaz = (w.spinaz or 0) + int(amount)
    w.save(update_fields=["spinaz", "updated_at"])

No lock, no floor, and the arithmetic done in the process rather than the
database — so two requests that read the same row each computed their own
total and the later write won. Gunicorn runs two workers of four threads, so
eight request threads can be inside this at once, and EVERY reward on the
platform goes through it: rating, referrals, AdZ, OfferZ, the zodiac bonuses,
battle entries and wagers, collab escrow.

Proven rather than theorised, and both failures are in these tests as the
thing that must not come back.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import (Wallet, award_energy, award_promptz, award_spinaz,
                     spend_spinaz, wallet_for)

User = get_user_model()
PW = "hunter2hunter2"


def bal(user, field="spinaz"):
    return Wallet.objects.values_list(field, flat=True).filter(user=user).first()


class ConcurrentMovesAddUpTests(TestCase):

    def setUp(self):
        self.u = User.objects.create_user("u", "u@x.test", PW)
        w = wallet_for(self.u)
        w.spinaz, w.energy, w.promptz = 100, 100, 100
        w.save(update_fields=["spinaz", "energy", "promptz"])

    def test_two_spends_both_land(self):
        """The bug, at its simplest: spending 50 twice from 100 used to leave
        50, because one of the two spends vanished."""
        award_spinaz(self.u, -50, "a")
        award_spinaz(self.u, -50, "b")
        self.assertEqual(bal(self.u), 0)

    def test_a_stale_object_in_hand_cannot_overwrite_the_row(self):
        """What a second request thread actually holds: an object read before
        the other one wrote. The arithmetic is the database's now, so the
        stale copy cannot undo anything."""
        stale = wallet_for(self.u)
        self.assertEqual(stale.spinaz, 100)
        award_spinaz(self.u, -30, "somebody else's request")
        award_spinaz(self.u, -30, "this request")
        self.assertEqual(bal(self.u), 40)

    def test_energy_and_promptz_were_the_same_code(self):
        award_energy(self.u, -25, "a")
        award_energy(self.u, -25, "b")
        self.assertEqual(bal(self.u, "energy"), 50)
        award_promptz(self.u, -25, "a")
        award_promptz(self.u, -25, "b")
        self.assertEqual(bal(self.u, "promptz"), 50)

    def test_a_credit_still_returns_the_new_balance(self):
        self.assertEqual(award_spinaz(self.u, 25, "gift"), 125)


class ABalanceHasAFloorTests(TestCase):
    """`award_spinaz(user, -500)` on a balance of 10 left **-490**."""

    def setUp(self):
        self.u = User.objects.create_user("v", "v@x.test", PW)
        w = wallet_for(self.u)
        w.spinaz = 100
        w.save(update_fields=["spinaz"])

    def test_an_overdraw_is_refused_and_changes_nothing(self):
        self.assertIsNone(spend_spinaz(self.u, 500, "nope"))
        self.assertEqual(bal(self.u), 100)

    def test_an_affordable_spend_goes_through(self):
        self.assertEqual(spend_spinaz(self.u, 40, "ok"), 60)
        self.assertEqual(bal(self.u), 60)

    def test_the_exact_balance_is_spendable(self):
        self.assertEqual(spend_spinaz(self.u, 100, "all in"), 0)

    def test_the_same_stake_cannot_be_spent_twice(self):
        """The race the battle paths had: check the balance, then spend it, in
        two statements a member is not obliged to wait between."""
        self.assertEqual(spend_spinaz(self.u, 60, "first"), 40)
        self.assertIsNone(spend_spinaz(self.u, 60, "second"))
        self.assertEqual(bal(self.u), 40)

    def test_a_refused_spend_writes_no_ledger_row(self):
        """LogZ exists so a balance change has a reason behind it. A spend
        that did not happen must not appear as one."""
        from .models import Transaction
        before = Transaction.objects.count()
        spend_spinaz(self.u, 500, "nope")
        self.assertEqual(Transaction.objects.count(), before)

    def test_a_spend_of_nothing_is_not_a_spend(self):
        self.assertIsNone(spend_spinaz(self.u, 0, "zero"))
        self.assertIsNone(spend_spinaz(self.u, -5, "negative"))
        self.assertEqual(bal(self.u), 100)


class TheBattlePathsRefuseRatherThanOverdrawTests(TestCase):

    def setUp(self):
        from .models import Battle
        self.host = User.objects.create_user("host", "h@x.test", PW)
        self.better = User.objects.create_user("better", "b@x.test", PW)
        w = wallet_for(self.better)
        w.spinaz = 50
        w.save(update_fields=["spinaz"])
        self.b = Battle.objects.create(host=self.host, title="b", entry_spinaz=0)
        self.c = APIClient()
        self.c.force_authenticate(self.better)

    def test_a_wager_beyond_the_balance_is_402_not_a_negative_wallet(self):
        r = self.c.post(f"/api/economy/battlez/{self.b.pk}/wager/",
                        {"side": "host", "amount": 500}, format="json")
        self.assertEqual(r.status_code, 402)
        self.assertEqual(bal(self.better), 50)

    def test_an_affordable_wager_is_held(self):
        r = self.c.post(f"/api/economy/battlez/{self.b.pk}/wager/",
                        {"side": "host", "amount": 30}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(bal(self.better), 20)
