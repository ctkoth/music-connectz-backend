from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.economy.models import (award_spinaz, credit_funds, profile_for,
                                 wallet_for)

from .models import (CURRENCY_MONEY, CURRENCY_SPINAZ, FORMAT_1V1, SIDE_A,
                     SIDE_B, STATUS_LIVE, Battle, BattleEntry, BattleVote, Bet,
                     money_bet_error, spinaz_bet_error, take_stake)

User = get_user_model()


def member(name, cash=0, spinaz=0, adult=False):
    u = User.objects.create_user(username=name, password="battlez-pass-1")
    if cash:
        # Set the balance directly. credit_funds() taxes a gross deposit, so
        # using it here would make every fixture 10% smaller than it reads and
        # quietly break the arithmetic these tests exist to check.
        w = wallet_for(u)
        w.money_cents = cash
        w.save(update_fields=["money_cents"])
    if spinaz:
        award_spinaz(u, spinaz, note="test")
    if adult:
        p = profile_for(u)
        p.verified_18plus = True
        p.save(update_fields=["verified_18plus"])
    return u


class EligibilityTests(TestCase):
    def setUp(self):
        self.host = member("host")
        self.battle = Battle.objects.create(created_by=self.host, title="Bars",
                                            format=FORMAT_1V1)
        self.a = member("side_a", cash=10_000, adult=True)
        self.b = member("side_b", cash=10_000, adult=True)
        BattleEntry.objects.create(battle=self.battle, user=self.a, side=SIDE_A)
        BattleEntry.objects.create(battle=self.battle, user=self.b, side=SIDE_B)

    def test_contestant_can_back_themselves_with_money(self):
        self.assertIsNone(money_bet_error(self.battle, self.a, SIDE_A))

    def test_contestant_cannot_back_their_opponent(self):
        self.assertIn("on yourself", money_bet_error(self.battle, self.a, SIDE_B))

    def test_spectator_cannot_bet_money(self):
        watcher = member("watcher", cash=10_000, adult=True)
        self.assertIn("Only contestants",
                      money_bet_error(self.battle, watcher, SIDE_A))

    def test_unverified_contestant_cannot_bet_money(self):
        """A birthday typed into a form is not age verification."""
        kid = member("unverified", cash=10_000, adult=False)
        BattleEntry.objects.create(battle=self.battle, user=kid, side=SIDE_A)
        self.assertIn("verified 18+", money_bet_error(self.battle, kid, SIDE_A))

    def test_contestant_cannot_bet_spinaz(self):
        self.assertIn("back yourself", spinaz_bet_error(self.battle, self.a, SIDE_A))

    def test_spectator_can_bet_spinaz(self):
        watcher = member("watcher2", spinaz=500)
        self.assertIsNone(spinaz_bet_error(self.battle, watcher, SIDE_A))


class StakeTests(TestCase):
    def test_cannot_stake_more_money_than_you_have(self):
        u = member("broke", cash=100)
        self.assertIn("balance", take_stake(u, CURRENCY_MONEY, 500))
        self.assertEqual(wallet_for(u).money_cents, 100)

    def test_cannot_stake_more_spinaz_than_you_have(self):
        u = member("brokez", spinaz=10)
        self.assertIn("SpinAZ", take_stake(u, CURRENCY_SPINAZ, 50))
        self.assertEqual(wallet_for(u).spinaz, 10)

    def test_zero_and_negative_stakes_are_refused(self):
        u = member("zero", cash=1000)
        self.assertIsNotNone(take_stake(u, CURRENCY_MONEY, 0))
        self.assertIsNotNone(take_stake(u, CURRENCY_MONEY, -100))
        self.assertEqual(wallet_for(u).money_cents, 1000)

    def test_a_good_stake_debits_exactly_once(self):
        u = member("payer", cash=1000)
        self.assertIsNone(take_stake(u, CURRENCY_MONEY, 400))
        self.assertEqual(wallet_for(u).money_cents, 600)


class SettlementTests(TestCase):
    def setUp(self):
        self.host = member("host2")
        self.battle = Battle.objects.create(created_by=self.host, title="Cash",
                                            format=FORMAT_1V1, status=STATUS_LIVE)
        self.a = member("winner", cash=10_000, adult=True)
        self.b = member("loser", cash=10_000, adult=True)
        BattleEntry.objects.create(battle=self.battle, user=self.a, side=SIDE_A)
        BattleEntry.objects.create(battle=self.battle, user=self.b, side=SIDE_B)

    def _stake(self, user, side, currency, amount):
        take_stake(user, currency, amount)
        return Bet.objects.create(battle=self.battle, user=user, side=side,
                                  currency=currency, amount=amount)

    def _vote(self, name, side):
        BattleVote.objects.create(battle=self.battle, user=member(name), side=side)

    def test_winner_never_gets_back_less_than_they_staked(self):
        """The rake comes off the losing pool, so the stake always returns."""
        self._stake(self.a, SIDE_A, CURRENCY_MONEY, 1000)
        self._stake(self.b, SIDE_B, CURRENCY_MONEY, 1000)
        self._vote("v1", SIDE_A)

        before = wallet_for(self.a).money_cents
        self.battle.settle()
        after = wallet_for(self.a).money_cents
        self.assertGreater(after, before)
        self.assertGreaterEqual(after - before, 1000)

    def test_losing_side_is_paid_nothing_and_keeps_nothing(self):
        self._stake(self.a, SIDE_A, CURRENCY_MONEY, 1000)
        self._stake(self.b, SIDE_B, CURRENCY_MONEY, 1000)
        self._vote("v2", SIDE_A)
        before = wallet_for(self.b).money_cents
        self.battle.settle()
        self.assertEqual(wallet_for(self.b).money_cents, before)

    def test_cash_and_spinaz_never_cross(self):
        """A spectator's play money must not fund a cash payout, or vice versa."""
        self._stake(self.a, SIDE_A, CURRENCY_MONEY, 1000)
        self._stake(self.b, SIDE_B, CURRENCY_MONEY, 1000)
        watcher = member("spectator", spinaz=800)
        self._stake(watcher, SIDE_A, CURRENCY_SPINAZ, 800)
        self._vote("v3", SIDE_A)

        cash_before = wallet_for(self.a).money_cents
        spinaz_before = wallet_for(watcher).spinaz
        report = self.battle.settle()

        # Side A's cash winner is paid out of the cash pool.
        self.assertEqual(report["currencies"][CURRENCY_MONEY]["outcome"], "paid")
        self.assertGreater(wallet_for(self.a).money_cents, cash_before)
        # The lone SpinAZ bettor had nobody opposing — refunded, not "won".
        self.assertEqual(report["currencies"][CURRENCY_SPINAZ]["outcome"], "refunded")
        self.assertEqual(wallet_for(watcher).spinaz, spinaz_before + 800)
        # And the cash winner's SpinAZ balance was never touched.
        self.assertEqual(wallet_for(self.a).spinaz, 0)

    def test_a_tie_refunds_everybody(self):
        self._stake(self.a, SIDE_A, CURRENCY_MONEY, 1000)
        self._stake(self.b, SIDE_B, CURRENCY_MONEY, 1000)
        self._vote("t1", SIDE_A)
        self._vote("t2", SIDE_B)

        report = self.battle.settle()
        self.assertEqual(report["reason"], "tie")
        self.assertEqual(wallet_for(self.a).money_cents, 10_000)
        self.assertEqual(wallet_for(self.b).money_cents, 10_000)

    def test_an_unopposed_pool_is_refunded_not_won(self):
        self._stake(self.a, SIDE_A, CURRENCY_MONEY, 2500)
        self._vote("u1", SIDE_A)
        self.battle.settle()
        self.assertEqual(wallet_for(self.a).money_cents, 10_000,
                         "staking against nobody should return the stake intact")

    def test_settling_twice_does_not_pay_twice(self):
        self._stake(self.a, SIDE_A, CURRENCY_MONEY, 1000)
        self._stake(self.b, SIDE_B, CURRENCY_MONEY, 1000)
        self._vote("d1", SIDE_A)
        self.battle.settle()
        paid_once = wallet_for(self.a).money_cents
        self.battle.settle()
        self.assertEqual(wallet_for(self.a).money_cents, paid_once)

    def test_every_cent_of_the_losing_pool_is_accounted_for(self):
        """Integer division must not quietly evaporate a remainder."""
        w1 = member("w1", spinaz=333)
        w2 = member("w2", spinaz=667)
        loser = member("l1", spinaz=1000)
        self._stake(w1, SIDE_A, CURRENCY_SPINAZ, 333)
        self._stake(w2, SIDE_A, CURRENCY_SPINAZ, 667)
        self._stake(loser, SIDE_B, CURRENCY_SPINAZ, 1000)
        self._vote("r1", SIDE_A)
        self.battle.settle()

        # No dev tax on SpinAZ, so the winners should hold exactly their stakes
        # plus the entire losing pool.
        total = wallet_for(w1).spinaz + wallet_for(w2).spinaz
        self.assertEqual(total, 333 + 667 + 1000)


class ApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.host = member("api_host", cash=5000, adult=True)
        self.client.force_authenticate(self.host)

    def test_catalog_is_public(self):
        anon = APIClient()
        r = anon.get(reverse("battlez-catalog"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["formats"]), 3)

    def test_create_join_and_bet_flow(self):
        r = self.client.post(reverse("battlez-battles"),
                             {"title": "Round one", "format": FORMAT_1V1},
                             format="json")
        self.assertEqual(r.status_code, 201)
        bid = r.json()["battle"]["id"]

        r = self.client.post(reverse("battlez-entries", args=[bid]),
                             {"side": SIDE_A}, format="json")
        self.assertEqual(r.status_code, 201)

        r = self.client.post(reverse("battlez-bets", args=[bid]),
                             {"side": SIDE_A, "currency": CURRENCY_MONEY,
                              "amount": 500}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(wallet_for(self.host).money_cents, 4500)

    def test_1v1_side_holds_only_one_artist(self):
        r = self.client.post(reverse("battlez-battles"),
                             {"title": "Solo", "format": FORMAT_1V1},
                             format="json")
        bid = r.json()["battle"]["id"]
        self.client.post(reverse("battlez-entries", args=[bid]),
                         {"side": SIDE_A}, format="json")

        other = APIClient()
        other.force_authenticate(member("crasher"))
        r = other.post(reverse("battlez-entries", args=[bid]),
                       {"side": SIDE_A}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertIn("one artist a side", r.json()["detail"])

    def test_contestants_cannot_vote_in_their_own_battle(self):
        r = self.client.post(reverse("battlez-battles"), {"title": "Vote"},
                             format="json")
        bid = r.json()["battle"]["id"]
        self.client.post(reverse("battlez-entries", args=[bid]),
                         {"side": SIDE_A}, format="json")
        self.client.patch(reverse("battlez-battle", args=[bid]),
                          {"status": "live"}, format="json")
        r = self.client.post(reverse("battlez-votes", args=[bid]),
                             {"side": SIDE_A}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_betting_is_refused_once_voting_starts(self):
        r = self.client.post(reverse("battlez-battles"), {"title": "Closed"},
                             format="json")
        bid = r.json()["battle"]["id"]
        self.client.post(reverse("battlez-entries", args=[bid]),
                         {"side": SIDE_A}, format="json")
        self.client.patch(reverse("battlez-battle", args=[bid]),
                          {"status": "live"}, format="json")
        self.client.patch(reverse("battlez-battle", args=[bid]),
                          {"status": "voting"}, format="json")
        r = self.client.post(reverse("battlez-bets", args=[bid]),
                             {"side": SIDE_A, "currency": CURRENCY_MONEY,
                              "amount": 100}, format="json")
        self.assertEqual(r.status_code, 409)
