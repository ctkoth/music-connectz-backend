"""A CollabZ advance: real money out of escrow, early. The invariant is conservation — across every wallet, the
deal's held money and the platform's tax, not a cent is created or lost whatever order advance / release / refund
happen in."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import CollabDeal, Membership, TIER_PREMIUM, wallet_for
from apps.economy.collab import release_deal, refund_deal

User = get_user_model()
PW = "hunter2hunter2"


def money(*users):
    return sum(wallet_for(u).money_cents for u in users)


class AdvanceTests(TestCase):
    def setUp(self):
        self.payer = User.objects.create_user("payer", "p@e.com", PW)
        self.mate = User.objects.create_user("mate", "m@e.com", PW)
        for u in (self.payer, self.mate):
            Membership.objects.get_or_create(user=u, defaults={"tier": TIER_PREMIUM})
        self.c, self.m = APIClient(), APIClient()
        self.c.force_authenticate(self.payer); self.m.force_authenticate(self.mate)
        w = wallet_for(self.payer); w.money_cents = 100_000; w.save()
        # payer pays 20000 and is owed nothing; mate is owed 19000 (after tax) and pays nothing.
        self.deal = CollabDeal.objects.create(
            initiator=self.payer, title="Beat", currency="money", status="funded", held_cents=20000,
            participants=[
                {"username": "payer", "pays_cents": 20000, "receives_cents": 0, "funded": True, "accepted_at": "x"},
                {"username": "mate", "pays_cents": 0, "receives_cents": 19000, "funded": True, "accepted_at": "x"},
            ])
        self.url = f"/api/economy/collab/{self.deal.id}/advance/"

    def _pot(self):
        d = CollabDeal.objects.get(pk=self.deal.pk)
        return money(self.payer, self.mate) + d.held_cents

    def test_a_50_dollar_advance_moves_exactly_50_dollars_and_the_rest_stays_held(self):
        before = money(self.payer, self.mate)
        r = self.c.post(self.url, {"to": "mate", "amount": "50"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(wallet_for(self.mate).money_cents, 5000)
        self.assertEqual(CollabDeal.objects.get(pk=self.deal.pk).held_cents, 15000)
        self.assertEqual(money(self.payer, self.mate), before + 5000)            # the held money left escrow, once

    def test_release_pays_only_what_is_still_owed_and_money_is_conserved(self):
        total = self._pot()
        self.c.post(self.url, {"to": "mate", "amount": "50"}, format="json")
        release_deal(CollabDeal.objects.get(pk=self.deal.pk))
        d = CollabDeal.objects.get(pk=self.deal.pk)
        self.assertEqual(wallet_for(self.mate).money_cents, 19000)               # 5000 early + 14000 now = what was owed
        self.assertEqual(d.held_cents, 0)
        self.assertEqual(money(self.payer, self.mate) + 1000, total)             # the 1000 left is the platform's tax, as before

    def test_a_refund_returns_only_what_is_still_held(self):
        start = wallet_for(self.payer).money_cents
        self.c.post(self.url, {"to": "mate", "amount": "50"}, format="json")
        refund_deal(CollabDeal.objects.get(pk=self.deal.pk))
        self.assertEqual(wallet_for(self.payer).money_cents, start + 15000)      # 20000 held − 5000 gone
        self.assertEqual(wallet_for(self.mate).money_cents, 5000)                # the advance stays paid

    def test_it_cannot_exceed_what_the_payer_holds_or_the_payee_is_owed(self):
        self.assertEqual(self.c.post(self.url, {"to": "mate", "amount": "191"}, format="json").status_code, 400)   # owed 190
        self.assertEqual(self.c.post(self.url, {"to": "mate", "amount": "190"}, format="json").status_code, 200)
        self.assertEqual(self.c.post(self.url, {"to": "mate", "amount": "1"}, format="json").status_code, 400)    # nothing owed left
        self.assertEqual(CollabDeal.objects.get(pk=self.deal.pk).held_cents, 1000)

    def test_who_may_advance_and_to_whom(self):
        self.assertEqual(self.m.post(self.url, {"to": "payer", "amount": "5"}, format="json").status_code, 403)     # mate pays nothing
        self.assertEqual(self.c.post(self.url, {"to": "payer", "amount": "5"}, format="json").status_code, 400)     # not yourself
        self.assertEqual(self.c.post(self.url, {"to": "ghost", "amount": "5"}, format="json").status_code, 400)
        stranger = APIClient(); stranger.force_authenticate(User.objects.create_user("x", "x@e.com", PW))
        self.assertEqual(stranger.post(self.url, {"to": "mate", "amount": "5"}, format="json").status_code, 403)
        for bad in ("0", "-5", "abc", ""):
            self.assertEqual(self.c.post(self.url, {"to": "mate", "amount": bad}, format="json").status_code, 400)

    def test_not_to_someone_who_has_not_accepted_not_on_other_states_or_currencies_or_rating_splits(self):
        d = CollabDeal.objects.get(pk=self.deal.pk)
        d.participants[1].pop("accepted_at"); d.save()
        self.assertEqual(self.c.post(self.url, {"to": "mate", "amount": "5"}, format="json").status_code, 409)
        d.participants[1]["accepted_at"] = "x"; d.split_mode = "rating"; d.save()
        self.assertEqual(self.c.post(self.url, {"to": "mate", "amount": "5"}, format="json").status_code, 409)
        d.split_mode = "worth"; d.status = "disputed"; d.save()
        self.assertEqual(self.c.post(self.url, {"to": "mate", "amount": "5"}, format="json").status_code, 409)
        d.status = "funded"; d.currency = "spinaz"; d.save()
        self.assertEqual(self.c.post(self.url, {"to": "mate", "amount": "5"}, format="json").status_code, 409)

    def test_the_deal_says_who_and_how_much_before_anything_is_pressed(self):
        adv = self.c.get(f"/api/economy/collab/{self.deal.id}/").data["advance"]
        self.assertEqual(adv["to"], [{"username": "mate", "max_cents": 19000}])
        self.assertIn("cannot be taken back", adv["note"])
        self.assertEqual(self.m.get(f"/api/economy/collab/{self.deal.id}/").data["advance"], {})   # the payee is offered nothing

    def test_two_advances_add_up_and_a_ledger_row_says_where_it_came_from(self):
        from apps.economy.models import Transaction
        self.c.post(self.url, {"to": "mate", "amount": "50"}, format="json")
        self.c.post(self.url, {"to": "mate", "amount": "25.50"}, format="json")
        self.assertEqual(wallet_for(self.mate).money_cents, 7550)
        self.assertEqual(Transaction.objects.filter(user=self.mate, amount_cents=5000).first().note[:34], "CollabZ advance from @payer: Beat"[:34])
