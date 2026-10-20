"""CollabZ: a deal's own starter can withdraw a draft and fix a typo in it.

Two gaps an editable/shareable/rateable/karma-able audit found: the only
"cancel" door (`CollabRefundView`) was payer-gated, so a starter who is not a
payer on their own deal (they're the one being PAID) had no way to withdraw
it before anyone responded. And there was no PATCH at all — a typo'd title
or a fat-fingered worth figure was permanent the moment the deal existed.

Both are scoped tight: only the starter, only while the deal is still a
DRAFT, and only before anyone else has put real consent (accepted) or real
money (funded) behind the numbers as they stand.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import CollabDeal

User = get_user_model()
PW = "hunter2hunter2"


class CollabEditCancelTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.me = User.objects.create_user("starter1", "s1@e.com", PW)
        self.mate = User.objects.create_user("mate1", "m1@e.com", PW)
        self.client.force_authenticate(self.me)

    def create(self, **over):
        # `collab_settlement` pays TOWARD the OTHER person's worth: a
        # participant's own worth_cents is what OTHERS fund, not what they
        # fund themselves. So starter1's worth here (1000) is what mate1
        # pays, and mate1's worth (0) is what starter1 pays — starter1 is
        # the one being paid, mate1 is the payer.
        return self.client.post("/api/economy/collab/", {
            "title": "EP", "currency": "spinaz",
            "participants": [{"username": "starter1", "worth_cents": 1000},
                             {"username": "mate1", "worth_cents": 0}],
            **over,
        }, format="json")

    # ---- Cancel: the starter can withdraw their own draft ----

    def test_a_non_paying_starter_can_cancel_their_own_draft(self):
        deal_id = self.create().data["id"]
        deal = CollabDeal.objects.get(pk=deal_id)
        # starter1 is being paid here (mate1 funds starter1's worth), so
        # starter1 is NOT a payer on their own deal.
        self.assertEqual(int(next(p for p in deal.participants if p["username"] == "starter1")["pays_cents"]), 0)
        r = self.client.post(f"/api/economy/collab/{deal_id}/refund/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        deal.refresh_from_db()
        self.assertEqual(deal.status, CollabDeal.STATUS_CANCELLED)

    def test_a_stranger_still_cannot_refund(self):
        deal_id = self.create().data["id"]
        stranger = APIClient(); stranger.force_authenticate(User.objects.create_user("rando1", "r1@e.com", PW))
        r = stranger.post(f"/api/economy/collab/{deal_id}/refund/", {}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_the_initiator_cannot_self_refund_once_funded_unless_also_a_payer(self):
        deal = CollabDeal.objects.create(
            initiator=self.me, title="x", currency=CollabDeal.CURRENCY_SPINAZ,
            status=CollabDeal.STATUS_FUNDED, held_spinaz=1000,
            participants=[
                {"username": "starter1", "worth_cents": 0, "pays_cents": 0, "receives_cents": 1000, "funded": True},
                {"username": "mate1", "worth_cents": 1000, "pays_cents": 1000, "receives_cents": 0, "funded": True},
            ])
        r = self.client.post(f"/api/economy/collab/{deal.id}/refund/", {}, format="json")
        self.assertEqual(r.status_code, 403)
        deal.refresh_from_db()
        self.assertEqual(deal.status, CollabDeal.STATUS_FUNDED)

    def test_a_paying_participant_can_still_self_refund_a_draft_as_before(self):
        # Regression: the existing payer-cancel path is untouched.
        mate_client = APIClient(); mate_client.force_authenticate(self.mate)
        deal_id = self.create().data["id"]
        r = mate_client.post(f"/api/economy/collab/{deal_id}/refund/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)

    # ---- PATCH: fix a typo in a draft nobody has responded to yet ----

    def test_the_starter_can_rename_and_redescribe_their_draft(self):
        deal_id = self.create().data["id"]
        r = self.client.patch(f"/api/economy/collab/{deal_id}/",
                              {"title": "Fixed Title", "description": "fixed brief"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        deal = CollabDeal.objects.get(pk=deal_id)
        self.assertEqual((deal.title, deal.description), ("Fixed Title", "fixed brief"))

    def test_editing_the_worth_recomputes_the_split(self):
        deal_id = self.create().data["id"]
        before = CollabDeal.objects.get(pk=deal_id).participants
        mate_before = next(p for p in before if p["username"] == "mate1")
        # Raising starter1's OWN worth raises what mate1 funds toward it.
        r = self.client.patch(f"/api/economy/collab/{deal_id}/",
                              {"worths": {"starter1": 2000}}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        deal = CollabDeal.objects.get(pk=deal_id)
        starter_after = next(p for p in deal.participants if p["username"] == "starter1")
        mate_after = next(p for p in deal.participants if p["username"] == "mate1")
        self.assertEqual(starter_after["worth_cents"], 2000)
        self.assertGreater(mate_after["pays_cents"], mate_before["pays_cents"])

    def test_someone_elses_username_in_worths_is_harmlessly_ignored(self):
        deal_id = self.create().data["id"]
        r = self.client.patch(f"/api/economy/collab/{deal_id}/",
                              {"worths": {"not-on-this-deal": 500}}, format="json")
        # No recognised participant changed, so there's nothing to save.
        self.assertEqual(r.status_code, 400)

    def test_only_the_starter_may_edit(self):
        deal_id = self.create().data["id"]
        mate_client = APIClient(); mate_client.force_authenticate(self.mate)
        r = mate_client.patch(f"/api/economy/collab/{deal_id}/", {"title": "stolen"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(CollabDeal.objects.get(pk=deal_id).title, "EP")

    def test_a_funded_deal_cannot_be_edited(self):
        deal = CollabDeal.objects.create(
            initiator=self.me, title="x", currency=CollabDeal.CURRENCY_SPINAZ,
            status=CollabDeal.STATUS_FUNDED,
            participants=[{"username": "starter1", "worth_cents": 0},
                         {"username": "mate1", "worth_cents": 1000}])
        r = self.client.patch(f"/api/economy/collab/{deal.id}/", {"title": "late"}, format="json")
        self.assertEqual(r.status_code, 409)

    def test_cannot_edit_once_another_participant_has_accepted(self):
        deal_id = self.create().data["id"]
        mate_client = APIClient(); mate_client.force_authenticate(self.mate)
        self.assertEqual(mate_client.post(f"/api/economy/collab/{deal_id}/accept/",
                                          {"accept": True}, format="json").status_code, 200)
        r = self.client.patch(f"/api/economy/collab/{deal_id}/", {"title": "late"}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(CollabDeal.objects.get(pk=deal_id).title, "EP")

    def test_cannot_edit_once_anyone_has_funded(self):
        deal = CollabDeal.objects.create(
            initiator=self.me, title="x", currency=CollabDeal.CURRENCY_SPINAZ,
            status=CollabDeal.STATUS_DRAFT,
            participants=[{"username": "starter1", "worth_cents": 0, "funded": False},
                         {"username": "mate1", "worth_cents": 1000, "pays_cents": 1000, "funded": True}])
        r = self.client.patch(f"/api/economy/collab/{deal.id}/", {"title": "late"}, format="json")
        self.assertEqual(r.status_code, 409)

    def test_patching_nothing_recognised_says_so(self):
        deal_id = self.create().data["id"]
        r = self.client.patch(f"/api/economy/collab/{deal_id}/", {}, format="json")
        self.assertEqual(r.status_code, 400)
