"""LabelZ — founding a label, and the agreements it offers.

The assertions worth keeping are the ones about the document: that the terms
are frozen at the offer, that a changed document refuses a signature rather
than recording one against text nobody agreed to, and that no money moves.
Each of those would still look right on screen if it broke.
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from .labelz import _doc_hash
from .models import (TIER_PREMIUM, Label, LabelContract, membership_for,
                     profile_for)

User = get_user_model()


def _adult(user, years=30):
    p = profile_for(user)
    p.birthday = date.today().replace(year=date.today().year - years).isoformat()
    p.save()
    return user


class LabelZTests(APITestCase):
    def setUp(self):
        self.owner = _adult(User.objects.create_user("owner", password="x"))
        self.artist = _adult(User.objects.create_user("artist", password="x"))
        m = membership_for(self.owner)
        m.tier = TIER_PREMIUM
        m.save()
        self.client.force_authenticate(self.owner)

    def _make_label(self, name="Night Shift"):
        r = self.client.post(reverse("labelz"), {"name": name, "bio": "b"}, format="json")
        self.assertEqual(201, r.status_code, r.data)
        return r.data["id"]

    def _offer(self, label_id, **over):
        body = {"label_id": label_id, "artist": "artist", "title": "Artist Agreement",
                "terms_text": "50/50 splits, 2 year term.", "advance_display": "$200",
                "signed_name": "Owner O'Owner"}
        body.update(over)
        return self.client.post(reverse("labelz-contracts"), body, format="json")

    # ---- founding ----

    def test_premium_can_found_a_label(self):
        r = self.client.get(reverse("labelz"))
        self.assertTrue(r.data["can_create"])
        self._make_label()
        self.assertEqual(1, Label.objects.count())

    def test_free_member_cannot_found_but_is_told_why(self):
        self.client.force_authenticate(self.artist)       # free, no persona
        r = self.client.get(reverse("labelz"))
        self.assertFalse(r.data["can_create"])
        self.assertTrue(r.data["why_not"], "a refusal has to say what opens it")
        self.assertEqual(403, self.client.post(reverse("labelz"), {"name": "X"},
                                               format="json").status_code)

    def test_ar_scout_persona_opens_it_without_a_subscription(self):
        """The ladder rule: a tier says how much, never whether."""
        p = profile_for(self.artist)
        p.personas = [{"key": "arscout", "name": "A&R Scout", "skills": []}]
        p.save()
        self.client.force_authenticate(self.artist)
        self.assertTrue(self.client.get(reverse("labelz")).data["can_create"])

    def test_label_names_are_unique(self):
        self._make_label("Night Shift")
        r = self.client.post(reverse("labelz"), {"name": "night shift"}, format="json")
        self.assertEqual(400, r.status_code)

    def test_member_count_is_owner_plus_signed_artists(self):
        lid = self._make_label()
        r = self.client.get(reverse("labelz"))
        self.assertEqual(1, r.data["labels"][0]["member_count"])   # just the owner
        cid = self._offer(lid).data["id"]
        self.client.force_authenticate(self.artist)
        self.client.post(reverse("labelz-contract-respond", args=[cid, "sign"]),
                         {"signed_name": "Artist A"}, format="json")
        self.client.force_authenticate(self.owner)
        r = self.client.get(reverse("labelz"))
        self.assertEqual(2, r.data["labels"][0]["member_count"])

    # ---- the document ----

    def test_offer_is_signed_and_hashed_by_the_label(self):
        cid = self._offer(self._make_label()).data["id"]
        c = LabelContract.objects.get(id=cid)
        self.assertEqual("offered", c.status)
        self.assertEqual("Owner O'Owner", c.owner_signed_name)
        self.assertIsNotNone(c.owner_signed_at)
        self.assertEqual(64, len(c.doc_sha256))
        self.assertEqual("", c.artist_signed_name)

    def test_artist_signs_and_both_names_stand(self):
        cid = self._offer(self._make_label()).data["id"]
        self.client.force_authenticate(self.artist)
        r = self.client.post(reverse("labelz-contract-respond", args=[cid, "sign"]),
                             {"signed_name": "Artist A"}, format="json")
        self.assertEqual(200, r.status_code)
        c = LabelContract.objects.get(id=cid)
        self.assertEqual("signed", c.status)
        self.assertEqual("Artist A", c.artist_signed_name)
        self.assertIsNotNone(c.artist_signed_at)
        self.assertEqual("Owner O'Owner", c.owner_signed_name)

    def test_terms_changed_after_the_offer_refuse_the_signature(self):
        """The whole reason the hash exists. A signature against text that
        moved is not a signature."""
        cid = self._offer(self._make_label()).data["id"]
        c = LabelContract.objects.get(id=cid)
        c.terms_text = "100/0 splits, 10 year term."     # edited underneath
        c.save(update_fields=["terms_text"])

        self.client.force_authenticate(self.artist)
        r = self.client.post(reverse("labelz-contract-respond", args=[cid, "sign"]),
                             {"signed_name": "Artist A"}, format="json")
        self.assertEqual(409, r.status_code)
        self.assertEqual("offered", LabelContract.objects.get(id=cid).status)

    def test_hash_covers_every_field_not_just_the_terms(self):
        base = _doc_hash("L", "a", "T", "terms", "$1")
        self.assertNotEqual(base, _doc_hash("L2", "a", "T", "terms", "$1"))
        self.assertNotEqual(base, _doc_hash("L", "a", "T2", "terms", "$1"))
        self.assertNotEqual(base, _doc_hash("L", "a", "T", "terms", "$2"))

    def test_signature_needs_a_typed_name(self):
        cid = self._offer(self._make_label()).data["id"]
        self.client.force_authenticate(self.artist)
        r = self.client.post(reverse("labelz-contract-respond", args=[cid, "sign"]),
                             {"signed_name": "  "}, format="json")
        self.assertEqual(400, r.status_code)

    def test_decline_and_then_no_second_answer(self):
        cid = self._offer(self._make_label()).data["id"]
        self.client.force_authenticate(self.artist)
        self.client.post(reverse("labelz-contract-respond", args=[cid, "decline"]),
                         {}, format="json")
        self.assertEqual("declined", LabelContract.objects.get(id=cid).status)
        again = self.client.post(reverse("labelz-contract-respond", args=[cid, "sign"]),
                                 {"signed_name": "Artist A"}, format="json")
        self.assertEqual(400, again.status_code)

    def test_only_the_named_artist_can_answer(self):
        cid = self._offer(self._make_label()).data["id"]
        other = _adult(User.objects.create_user("other", password="x"))
        self.client.force_authenticate(other)
        r = self.client.post(reverse("labelz-contract-respond", args=[cid, "sign"]),
                             {"signed_name": "Other"}, format="json")
        self.assertEqual(404, r.status_code)

    # ---- age, money, ownership ----

    def test_no_birthday_cannot_be_offered_or_sign(self):
        """Unknown age fails, same as a physical door."""
        minor = User.objects.create_user("nobday", password="x")   # no birthday
        lid = self._make_label()
        r = self._offer(lid, artist="nobday")
        self.assertEqual(400, r.status_code)

        self.client.force_authenticate(minor)
        self.assertEqual(403, self.client.post(
            reverse("labelz-contracts"), {"label_id": lid}, format="json").status_code)

    def test_under_18_cannot_be_offered(self):
        kid = _adult(User.objects.create_user("kid", password="x"), years=15)
        r = self._offer(self._make_label(), artist="kid")
        self.assertEqual(400, r.status_code)

    def test_advance_is_recorded_text_and_moves_no_money(self):
        from .models import wallet_for
        before = wallet_for(self.artist).spinaz
        cid = self._offer(self._make_label(), advance_display="$5000").data["id"]
        self.client.force_authenticate(self.artist)
        self.client.post(reverse("labelz-contract-respond", args=[cid, "sign"]),
                         {"signed_name": "Artist A"}, format="json")
        self.assertEqual("$5000", LabelContract.objects.get(id=cid).advance_display)
        self.assertEqual(before, wallet_for(self.artist).spinaz)

    def test_cannot_offer_from_a_label_you_dont_own(self):
        lid = self._make_label()
        rogue = _adult(User.objects.create_user("rogue", password="x"))
        self.client.force_authenticate(rogue)
        r = self._offer(lid)
        self.assertEqual(404, r.status_code)

    def test_cannot_contract_with_yourself(self):
        r = self._offer(self._make_label(), artist="owner")
        self.assertEqual(400, r.status_code)

    def test_terms_are_required(self):
        r = self._offer(self._make_label(), terms_text="   ")
        self.assertEqual(400, r.status_code)

    def test_oversized_terms_are_refused_not_truncated(self):
        """Truncating would hash and store a document neither party wrote."""
        from .labelz import MAX_TERMS
        r = self._offer(self._make_label(), terms_text="x" * (MAX_TERMS + 1))
        self.assertEqual(400, r.status_code)
        self.assertEqual(0, LabelContract.objects.count())

    def test_contracts_list_shows_both_sides(self):
        self._offer(self._make_label())
        r = self.client.get(reverse("labelz-contracts"))
        self.assertEqual(1, len(r.data["as_owner"]))
        self.assertEqual(0, len(r.data["as_artist"]))
        self.client.force_authenticate(self.artist)
        r = self.client.get(reverse("labelz-contracts"))
        self.assertEqual(1, len(r.data["as_artist"]))

    def test_requires_auth(self):
        self.client.force_authenticate(None)
        self.assertEqual(401, self.client.get(reverse("labelz")).status_code)
