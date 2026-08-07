"""SocialZ: match the name or the email, or send it to a person.

Corey's rule. Matching auto-confirms and the followers start counting toward
reach — which is what pays Energy. Anything the model can't confirm is FLAGGED
rather than refused, because most artists' stage names don't match their legal
names and a refusal would strand them.

The reason the queue exists at all: reach pays, so a claim on somebody else's
audience has to be somebody's decision.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import SocialReview, membership_for, profile_for

User = get_user_model()
PW = "hunter2hunter2"
VERIFY = "/api/economy/social/verify/"
REVIEWS = "/api/economy/social/reviews/"
URL = "https://instagram.com/koth"

PAGE = ("K-Oth · 12.4k followers · music", None)


def ai(verdict, followers=12400, reason="Handle matches the member's username."):
    return ({"verdict": verdict, "followers": followers, "handle": "@koth"}, reason, None)


class SocialBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="koth", password=PW,
                                             email="k@example.com")
        membership_for(self.user)
        p = profile_for(self.user)
        p.links = [{"label": "Instagram", "url": URL}]
        p.save(update_fields=["links"])
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def match(self):
        return self.client.post(VERIFY, {"action": "match", "url": URL}, format="json")

    def link(self):
        return profile_for(self.user).links[0]


class AMatchConfirmsItTests(SocialBase):
    @patch("apps.economy.social_verify._fetch_public_page", return_value=PAGE)
    @patch("apps.economy.social_verify._ai_identity", return_value=ai("yes"))
    def test_the_same_name_confirms_the_account(self, _ai, _fetch):
        r = self.match()
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["verified"])
        self.assertTrue(self.link()["verified"])

    @patch("apps.economy.social_verify._fetch_public_page", return_value=PAGE)
    @patch("apps.economy.social_verify._ai_identity", return_value=ai("yes"))
    def test_the_follower_count_is_read_not_typed(self, _ai, _fetch):
        # Nobody types their own follower count — that is the whole point.
        self.match()
        self.assertEqual(self.link()["followers"], 12400)
        self.assertEqual(self.link()["verified_count"], 12400)

    @patch("apps.economy.social_verify._fetch_public_page", return_value=PAGE)
    @patch("apps.economy.social_verify._ai_identity", return_value=ai("yes"))
    def test_a_confirmed_account_raises_the_reach_that_pays_energy(self, _ai, _fetch):
        from apps.economy.models import energy_rate_per_hour
        before = energy_rate_per_hour(self.user)
        self.match()
        # Re-fetch: social_sources reads user.mcz_profile, and this test's
        # instance cached it before the view wrote the verified link.
        fresh = User.objects.get(pk=self.user.pk)
        self.assertGreater(energy_rate_per_hour(fresh), before)

    @patch("apps.economy.social_verify._fetch_public_page", return_value=PAGE)
    @patch("apps.economy.social_verify._ai_identity", return_value=ai("yes"))
    def test_it_says_how_it_was_verified(self, _ai, _fetch):
        self.match()
        self.assertEqual(self.link()["verified_by"], "identity-match")


class WhatItCannotConfirmGoesToAPersonTests(SocialBase):
    @patch("apps.economy.social_verify._fetch_public_page", return_value=PAGE)
    @patch("apps.economy.social_verify._ai_identity",
           return_value=ai("no", reason="That profile belongs to a different artist."))
    def test_a_mismatch_is_flagged_not_refused(self, _ai, _fetch):
        r = self.match()
        self.assertEqual(r.status_code, 202)          # accepted, not rejected
        self.assertEqual(r.data["review"], "pending")
        self.assertEqual(SocialReview.objects.get().status, "pending")

    @patch("apps.economy.social_verify._fetch_public_page", return_value=PAGE)
    @patch("apps.economy.social_verify._ai_identity", return_value=ai("unsure"))
    def test_unsure_is_a_real_answer_and_also_queues(self, _ai, _fetch):
        # Forcing a binary would make the model guess about someone's identity.
        self.assertEqual(self.match().status_code, 202)
        self.assertEqual(SocialReview.objects.get().ai_verdict, "unsure")

    @patch("apps.economy.social_verify._fetch_public_page", return_value=PAGE)
    @patch("apps.economy.social_verify._ai_identity", return_value=ai("no"))
    def test_waiting_in_the_queue_does_not_pay(self, _ai, _fetch):
        self.match()
        self.assertFalse(self.link()["verified"])
        self.assertEqual(self.link()["review"], "pending")

    @patch("apps.economy.social_verify._fetch_public_page", return_value=PAGE)
    @patch("apps.economy.social_verify._ai_identity", return_value=ai("no"))
    def test_the_member_is_offered_the_instant_route(self, _ai, _fetch):
        r = self.match()
        self.assertIn("code", r.data["faster"])

    @patch("apps.economy.social_verify._fetch_public_page", return_value=PAGE)
    @patch("apps.economy.social_verify._ai_identity",
           return_value=ai("no", reason="Different person entirely."))
    def test_the_reason_is_kept_for_whoever_reviews_it(self, _ai, _fetch):
        self.match()
        self.assertEqual(SocialReview.objects.get().ai_reason, "Different person entirely.")

    @patch("apps.economy.social_verify._fetch_public_page", return_value=PAGE)
    @patch("apps.economy.social_verify._ai_identity", return_value=ai("no"))
    def test_a_member_can_see_their_own_pending_review(self, _ai, _fetch):
        self.match()
        r = self.client.get(REVIEWS)
        self.assertEqual(len(r.data["mine"]), 1)
        self.assertIsNone(r.data["queue"])       # the queue itself is owner-only


class TheQueueTests(SocialBase):
    def setUp(self):
        super().setUp()
        self.owner = User.objects.create_user(username="owner", password=PW,
                                              is_staff=True, is_superuser=True)
        membership_for(self.owner)
        self.oc = APIClient(); self.oc.force_authenticate(self.owner)
        with patch("apps.economy.social_verify._fetch_public_page", return_value=PAGE), \
             patch("apps.economy.social_verify._ai_identity", return_value=ai("unsure")):
            self.match()
        self.review = SocialReview.objects.get()

    def test_the_owner_sees_the_queue_with_the_reasoning(self):
        r = self.oc.get(REVIEWS)
        self.assertEqual(r.data["pending"], 1)
        row = r.data["queue"][0]
        self.assertEqual(row["username"], "koth")
        self.assertTrue(row["ai_reason"])

    def test_a_member_cannot_settle_their_own(self):
        r = self.client.post(REVIEWS, {"id": self.review.id, "decision": "approve"},
                             format="json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(self.link()["verified"])

    def test_approving_makes_the_followers_count(self):
        r = self.oc.post(REVIEWS, {"id": self.review.id, "decision": "approve"},
                         format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(self.link()["verified"])
        self.assertEqual(self.link()["followers"], 12400)
        self.assertEqual(self.link()["verified_by"], "manual")

    def test_rejecting_leaves_it_unverified(self):
        self.oc.post(REVIEWS, {"id": self.review.id, "decision": "reject",
                               "note": "That's someone else's account."}, format="json")
        self.assertFalse(self.link()["verified"])
        self.assertEqual(SocialReview.objects.get().status, "rejected")

    def test_either_way_the_member_is_told(self):
        self.oc.post(REVIEWS, {"id": self.review.id, "decision": "approve"}, format="json")
        note = self.user.notifications.first()
        self.assertIsNotNone(note)
        self.assertIn("verified", note.text)

    def test_a_decision_records_who_made_it(self):
        self.oc.post(REVIEWS, {"id": self.review.id, "decision": "approve"}, format="json")
        r = SocialReview.objects.get()
        self.assertEqual(r.reviewer, self.owner)
        self.assertIsNotNone(r.decided_at)

    def test_junk_decisions_are_refused(self):
        r = self.oc.post(REVIEWS, {"id": self.review.id, "decision": "maybe"}, format="json")
        self.assertEqual(r.status_code, 400)
