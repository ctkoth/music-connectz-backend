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
        self.assertEqual([(t["username"], t["max_cents"]) for t in adv["to"]], [("mate", 19000)])
        self.assertIn("cannot be taken back", adv["note"])
        self.assertEqual(self.m.get(f"/api/economy/collab/{self.deal.id}/").data["advance"], {})   # the payee is offered nothing

    def test_two_advances_add_up_and_a_ledger_row_says_where_it_came_from(self):
        from apps.economy.models import Transaction
        self.c.post(self.url, {"to": "mate", "amount": "50"}, format="json")
        self.c.post(self.url, {"to": "mate", "amount": "25.50"}, format="json")
        self.assertEqual(wallet_for(self.mate).money_cents, 7550)
        self.assertEqual(Transaction.objects.filter(user=self.mate, amount_cents=5000).first().note[:34], "CollabZ advance from @payer: Beat"[:34])


class AdvanceSkillsAndLabelTests(TestCase):
    def setUp(self):
        from apps.economy.models import Label, LabelContract, profile_for
        self.payer = User.objects.create_user("lbl", "l@e.com", PW)
        self.mate = User.objects.create_user("prod", "p@e.com", PW)
        for u in (self.payer, self.mate):
            Membership.objects.get_or_create(user=u, defaults={"tier": TIER_PREMIUM})
        p = profile_for(self.mate)
        p.personas = [{"key": "producer", "name": "Producer", "skills": [
            {"name": "Mixing", "rate_cents": 5000, "rate_unit": "work"}, {"name": "Mastering", "rate_cents": 3000}, {"name": "Drums", "rate_cents": 900}]}]
        p.save()
        self.deal = CollabDeal.objects.create(
            initiator=self.payer, title="EP", currency="money", status="funded", held_cents=20000,
            needs=[{"slot": "mix", "skill": "Mixing"}, {"slot": "master", "skill": "Mastering"}],
            participants=[{"username": "lbl", "pays_cents": 20000, "receives_cents": 0, "funded": True, "accepted_at": "x"},
                          {"username": "prod", "pays_cents": 0, "receives_cents": 19000, "funded": True, "accepted_at": "x"}])
        self.c = APIClient(); self.c.force_authenticate(self.payer)
        self.Label, self.LabelContract = Label, LabelContract

    def _opts(self):
        return self.c.get(f"/api/economy/collab/{self.deal.id}/").data["advance"]["to"][0]

    def test_the_suggestion_is_the_payees_own_price_of_the_skills_the_deal_needs_and_only_those(self):
        o = self._opts()
        self.assertEqual(o["skill_price_cents"], 8000)                       # Mixing 5000 + Mastering 3000, not Drums
        self.assertEqual(sorted(l["skill"] for l in o["skill_lines"]), ["Mastering", "Mixing"])
        self.assertIsNone(o["label"])                                         # not on a label: works the same

    def test_no_matching_skill_means_no_suggested_amount_never_an_invented_one(self):
        self.deal.needs = [{"slot": "x", "skill": "Tuba"}]; self.deal.save()
        o = self._opts()
        self.assertIsNone(o["skill_price_cents"]); self.assertEqual(o["skill_lines"], [])

    def test_the_suggestion_never_exceeds_what_can_be_advanced(self):
        self.deal.participants[1]["receives_cents"] = 6000; self.deal.save()
        self.assertEqual(self._opts()["skill_price_cents"], 6000)

    def test_a_label_signed_artist_gets_the_advance_on_their_labelz_record_only_when_asked_and_unconfirmed(self):
        from apps.economy.models import LabelAdvance
        lab = self.Label.objects.create(owner=self.payer, name="Neon")
        self.LabelContract.objects.create(label=lab, artist=self.mate, terms_text="t", status="signed")
        self.assertEqual(self._opts()["label"]["label"], "Neon")
        url = f"/api/economy/collab/{self.deal.id}/advance/"
        self.assertEqual(self.c.post(url, {"to": "prod", "amount": "50"}, format="json").status_code, 200)
        self.assertEqual(LabelAdvance.objects.count(), 0)                     # not unless asked
        self.assertEqual(self.c.post(url, {"to": "prod", "amount": "50", "record_in_labelz": True}, format="json").status_code, 200)
        line = LabelAdvance.objects.get()
        self.assertEqual((line.amount_cents, line.confirmed_at, line.kind), (5000, None, "advance"))
        self.assertEqual(wallet_for(self.mate).money_cents, 10000)            # both really paid

    def test_asking_for_labelz_without_a_signed_contract_with_that_label_records_nothing(self):
        from apps.economy.models import LabelAdvance
        self.c.post(f"/api/economy/collab/{self.deal.id}/advance/", {"to": "prod", "amount": "5", "record_in_labelz": True}, format="json")
        self.assertEqual(LabelAdvance.objects.count(), 0)
