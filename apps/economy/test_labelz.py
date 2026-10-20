"""LabelZ — public label groups and e-signed artist agreements.

The frontend has called these routes since it shipped; neither existed in
this backend until now (every load 404'd). These tests pin the contract the
frontend already assumes: `GET /api/economy/labelz/` -> {labels, can_create},
`POST` to create, `PATCH /api/economy/labelz/<id>/` to rename, and the
offer/sign/decline flow under `/api/economy/labelz/contracts/`.
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (TIER_FREE, TIER_PREMIUM, Label, LabelContract,
                                 Membership, Notification, profile_for)

User = get_user_model()


def member(name, age=30, tier=TIER_FREE):
    u = User.objects.create_user(name, f"{name}@e.com", "pw-Long-enough-1")
    Membership.objects.create(user=u, tier=tier)
    p = profile_for(u)
    today = date.today()
    p.birthday = f"{today.year - age}-{today.month:02d}-{min(today.day, 28):02d}"
    p.save()
    return u


def give_persona(user, key):
    p = profile_for(user)
    p.personas = [{"key": key, "name": key.title(), "skills": []}]
    p.save()


class LabelCreateGateTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_free_tier_with_no_persona_cannot_create(self):
        u = member("free1")
        self.client.force_authenticate(user=u)
        d = self.client.get("/api/economy/labelz/").data
        self.assertFalse(d["can_create"])
        r = self.client.post("/api/economy/labelz/", {"name": "x"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Label.objects.count(), 0)

    def test_premium_tier_can_create(self):
        u = member("prem1", tier=TIER_PREMIUM)
        self.client.force_authenticate(user=u)
        self.assertTrue(self.client.get("/api/economy/labelz/").data["can_create"])
        r = self.client.post("/api/economy/labelz/", {"name": "Prem Records"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_manager_persona_can_create_on_free_tier(self):
        u = member("mgr1")
        give_persona(u, "manager")
        self.client.force_authenticate(user=u)
        self.assertTrue(self.client.get("/api/economy/labelz/").data["can_create"])

    def test_arscout_persona_can_create_on_free_tier(self):
        u = member("ar1")
        give_persona(u, "arscout")
        self.client.force_authenticate(user=u)
        self.assertTrue(self.client.get("/api/economy/labelz/").data["can_create"])

    def test_unrelated_persona_does_not_unlock_it(self):
        u = member("sing1")
        give_persona(u, "singer")
        self.client.force_authenticate(user=u)
        self.assertFalse(self.client.get("/api/economy/labelz/").data["can_create"])

    def test_a_label_needs_a_name(self):
        u = member("prem2", tier=TIER_PREMIUM)
        self.client.force_authenticate(user=u)
        r = self.client.post("/api/economy/labelz/", {"name": "  "}, format="json")
        self.assertEqual(r.status_code, 400)


class LabelListAndEditTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = member("owner1", tier=TIER_PREMIUM)
        self.client.force_authenticate(user=self.owner)
        self.label = Label.objects.create(owner=self.owner, name="Orig Records", bio="orig bio")

    def test_i_own_is_true_only_for_the_owner(self):
        other = member("stranger1")
        d = self.client.get("/api/economy/labelz/").data
        self.assertTrue(d["labels"][0]["i_own"])
        c2 = APIClient(); c2.force_authenticate(user=other)
        self.assertFalse(c2.get("/api/economy/labelz/").data["labels"][0]["i_own"])

    def test_member_count_counts_only_signed_distinct_artists(self):
        a1, a2 = member("art1"), member("art2")
        LabelContract.objects.create(label=self.label, artist=a1, terms_text="t",
                                     status=LabelContract.STATUS_SIGNED)
        LabelContract.objects.create(label=self.label, artist=a1, terms_text="t2",
                                     status=LabelContract.STATUS_SIGNED)  # same artist twice
        LabelContract.objects.create(label=self.label, artist=a2, terms_text="t",
                                     status=LabelContract.STATUS_OFFERED)  # not signed yet
        d = self.client.get("/api/economy/labelz/").data
        self.assertEqual(d["labels"][0]["member_count"], 1)

    def test_owner_can_rename_and_change_bio(self):
        r = self.client.patch(f"/api/economy/labelz/{self.label.id}/",
                              {"name": "New Name", "bio": "new bio"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.label.refresh_from_db()
        self.assertEqual((self.label.name, self.label.bio), ("New Name", "new bio"))

    def test_someone_elses_label_is_not_found(self):
        other = member("stranger2")
        c2 = APIClient(); c2.force_authenticate(user=other)
        r = c2.patch(f"/api/economy/labelz/{self.label.id}/", {"name": "stolen"}, format="json")
        self.assertEqual(r.status_code, 404)
        self.label.refresh_from_db()
        self.assertEqual(self.label.name, "Orig Records")

    def test_renaming_to_blank_is_refused(self):
        r = self.client.patch(f"/api/economy/labelz/{self.label.id}/", {"name": "  "}, format="json")
        self.assertEqual(r.status_code, 400)
        self.label.refresh_from_db()
        self.assertEqual(self.label.name, "Orig Records")


class LabelContractOfferTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = member("owner2", tier=TIER_PREMIUM)
        self.artist = member("artist1")
        self.client.force_authenticate(user=self.owner)
        self.label = Label.objects.create(owner=self.owner, name="Offer Records")

    def _offer(self, **over):
        body = {"label_id": self.label.id, "artist": self.artist.username, "title": "Deal",
                "terms_text": "the terms", "advance_display": "$200", "signed_name": "Owner Legalname"}
        body.update(over)
        return self.client.post("/api/economy/labelz/contracts/", body, format="json")

    def test_offering_from_a_label_you_dont_own_is_refused(self):
        other_label = Label.objects.create(owner=member("owner3", tier=TIER_PREMIUM), name="Not Yours")
        r = self._offer(label_id=other_label.id)
        self.assertEqual(r.status_code, 400)

    def test_artist_must_be_a_real_username(self):
        r = self._offer(artist="nobody-here")
        self.assertEqual(r.status_code, 404)

    def test_cannot_offer_a_contract_to_yourself(self):
        r = self._offer(artist=self.owner.username)
        self.assertEqual(r.status_code, 400)

    def test_terms_and_signed_name_are_required(self):
        self.assertEqual(self._offer(terms_text="  ").status_code, 400)
        self.assertEqual(self._offer(signed_name="  ").status_code, 400)

    def test_a_minor_owner_cannot_offer_a_contract(self):
        teen = member("teen1", age=15, tier=TIER_PREMIUM)
        give_persona(teen, "manager")
        teen_label = Label.objects.create(owner=teen, name="Teen Label")
        c2 = APIClient(); c2.force_authenticate(user=teen)
        r = c2.post("/api/economy/labelz/contracts/",
                   {"label_id": teen_label.id, "artist": self.artist.username,
                    "terms_text": "t", "signed_name": "Teen Name"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(LabelContract.objects.count(), 0)

    def test_a_successful_offer_is_signed_by_the_owner_and_notifies_the_artist(self):
        r = self._offer()
        self.assertEqual(r.status_code, 201, r.data)
        c = LabelContract.objects.get(pk=r.data["id"])
        self.assertEqual(c.status, LabelContract.STATUS_OFFERED)
        self.assertEqual(c.owner_signed_name, "Owner Legalname")
        self.assertEqual(c.artist_signed_name, "")
        self.assertTrue(c.doc_sha256)
        self.assertTrue(Notification.objects.filter(user=self.artist, actor=self.owner).exists())

    def test_the_doc_hash_is_stable_and_differs_for_different_terms(self):
        r1 = self._offer()
        r2 = self._offer(artist=member("artist2").username, terms_text="different terms")
        self.assertNotEqual(r1.data["doc_sha256"], r2.data["doc_sha256"])

    def test_the_contracts_list_is_flat_not_one_query_per_row(self):
        for i in range(5):
            self._offer(artist=member(f"artbulk{i}").username)
        with self.assertNumQueries(2):    # as_artist, as_owner — each select_related, no N+1
            self.client.get("/api/economy/labelz/contracts/").data

    def test_contracts_list_splits_as_artist_and_as_owner(self):
        self._offer()
        c2 = APIClient(); c2.force_authenticate(user=self.artist)
        artist_view = c2.get("/api/economy/labelz/contracts/").data
        self.assertEqual(len(artist_view["as_artist"]), 1)
        self.assertEqual(len(artist_view["as_owner"]), 0)
        owner_view = self.client.get("/api/economy/labelz/contracts/").data
        self.assertEqual(len(owner_view["as_owner"]), 1)


class LabelContractRespondTests(TestCase):
    def setUp(self):
        self.owner = member("owner4", tier=TIER_PREMIUM)
        self.artist = member("artist3")
        self.label = Label.objects.create(owner=self.owner, name="Respond Records")
        self.contract = LabelContract.objects.create(
            label=self.label, artist=self.artist, terms_text="t", owner_signed_name="Owner")
        self.c = APIClient()
        self.c.force_authenticate(user=self.artist)

    def _url(self, action):
        return f"/api/economy/labelz/contracts/{self.contract.id}/{action}/"

    def test_only_the_named_artist_may_respond(self):
        stranger = APIClient(); stranger.force_authenticate(user=member("stranger3"))
        r = stranger.post(self._url("sign"), {"signed_name": "Fake"}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_signing_needs_a_name_and_sets_status_signed(self):
        r = self.c.post(self._url("sign"), {"signed_name": "  "}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.c.post(self._url("sign"), {"signed_name": "Artist Legalname"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.status, LabelContract.STATUS_SIGNED)
        self.assertEqual(self.contract.artist_signed_name, "Artist Legalname")
        self.assertIsNotNone(self.contract.signed_at)
        self.assertTrue(Notification.objects.filter(user=self.owner, actor=self.artist).exists())

    def test_a_minor_artist_cannot_sign(self):
        teen = member("teen2", age=16)
        contract = LabelContract.objects.create(label=self.label, artist=teen, terms_text="t")
        c2 = APIClient(); c2.force_authenticate(user=teen)
        r = c2.post(f"/api/economy/labelz/contracts/{contract.id}/sign/",
                   {"signed_name": "Teen Name"}, format="json")
        self.assertEqual(r.status_code, 403)
        contract.refresh_from_db()
        self.assertEqual(contract.status, LabelContract.STATUS_OFFERED)

    def test_declining_needs_no_signature_and_a_minor_may_decline(self):
        teen = member("teen3", age=16)
        contract = LabelContract.objects.create(label=self.label, artist=teen, terms_text="t")
        c2 = APIClient(); c2.force_authenticate(user=teen)
        r = c2.post(f"/api/economy/labelz/contracts/{contract.id}/decline/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        contract.refresh_from_db()
        self.assertEqual(contract.status, LabelContract.STATUS_DECLINED)
        self.assertIsNotNone(contract.declined_at)

    def test_a_decided_offer_cannot_be_acted_on_again(self):
        self.c.post(self._url("decline"), {}, format="json")
        r = self.c.post(self._url("sign"), {"signed_name": "Too Late"}, format="json")
        self.assertEqual(r.status_code, 409)

    def test_an_unknown_action_is_not_found(self):
        r = self.c.post(self._url("approve"), {}, format="json")
        self.assertEqual(r.status_code, 404)
