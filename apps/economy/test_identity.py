"""Verification has to say what happened.

The bug these cover: a member finished the Stripe flow and the API still said
`verified_18plus: false` — byte for byte what it said before they started. Pass,
fail, still-checking and under-18 all rendered as the same blank shrug.
"""
import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .identity import REASON_UNDER_18, record_session, status_payload
from .models import Profile, profile_for

User = get_user_model()


def dob_for_age(age):
    today = datetime.date.today()
    born = datetime.date(today.year - age, 1, 1)
    return {"day": born.day, "month": born.month, "year": born.year}


def session(state, user, **extra):
    return {"id": "vs_test_1", "status": state,
            "metadata": {"user_id": str(user.id)}, **extra}


class RecordSessionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="v", password="verify-pass-1")

    def test_an_adult_passes_and_is_marked_verified(self):
        record_session(session("verified", self.user,
                               verified_outputs={"dob": dob_for_age(30)}))
        p = profile_for(self.user)
        self.assertTrue(p.verified_18plus)
        self.assertEqual(p.verification_status, Profile.VERIFY_VERIFIED)
        self.assertIsNotNone(p.verified_18plus_at)

    def test_a_minor_is_recorded_as_failed_with_a_reason(self):
        """The old code returned silently here — the member was never told."""
        record_session(session("verified", self.user,
                               verified_outputs={"dob": dob_for_age(15)}))
        p = profile_for(self.user)
        self.assertFalse(p.verified_18plus)
        self.assertEqual(p.verification_status, Profile.VERIFY_FAILED)
        self.assertEqual(p.verification_reason, REASON_UNDER_18)
        self.assertIn("under 18", p.verification_detail)

    def test_a_verified_id_with_no_readable_dob_is_not_an_age_pass(self):
        record_session(session("verified", self.user, verified_outputs={}))
        p = profile_for(self.user)
        self.assertFalse(p.verified_18plus)
        self.assertEqual(p.verification_status, Profile.VERIFY_FAILED)
        self.assertEqual(p.verification_reason, "no_dob")

    def test_a_failed_document_records_the_stripe_error_in_plain_english(self):
        record_session(session("requires_input", self.user,
                               last_error={"code": "document_expired",
                                           "reason": "raw stripe text"}))
        p = profile_for(self.user)
        self.assertEqual(p.verification_status, Profile.VERIFY_FAILED)
        self.assertEqual(p.verification_reason, "document_expired")
        self.assertIn("expired", p.verification_detail)

    def test_an_unknown_error_code_still_produces_a_sentence(self):
        """Stripe adds codes. A blank box is never an acceptable answer."""
        record_session(session("requires_input", self.user,
                               last_error={"code": "brand_new_code_2027"}))
        p = profile_for(self.user)
        self.assertEqual(p.verification_status, Profile.VERIFY_FAILED)
        self.assertTrue(p.verification_detail.strip())

    def test_processing_is_its_own_state(self):
        record_session(session("processing", self.user))
        self.assertEqual(profile_for(self.user).verification_status,
                         Profile.VERIFY_PROCESSING)

    def test_cancelled_is_distinguishable_from_failed(self):
        record_session(session("canceled", self.user))
        self.assertEqual(profile_for(self.user).verification_status,
                         Profile.VERIFY_CANCELED)

    def test_recording_the_same_pass_twice_keeps_the_original_timestamp(self):
        record_session(session("verified", self.user,
                               verified_outputs={"dob": dob_for_age(40)}))
        first = profile_for(self.user).verified_18plus_at
        record_session(session("verified", self.user,
                               verified_outputs={"dob": dob_for_age(40)}))
        self.assertEqual(profile_for(self.user).verified_18plus_at, first)

    def test_a_session_with_no_user_is_ignored_rather_than_crashing(self):
        self.assertIsNone(record_session({"id": "vs_x", "status": "verified"}))


class StatusPayloadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="p", password="verify-pass-2")

    def test_unstarted_reads_as_not_started_and_offers_the_check(self):
        payload = status_payload(profile_for(self.user))
        self.assertEqual(payload["status"], Profile.VERIFY_UNSTARTED)
        self.assertEqual(payload["next_step"], "Start verification")
        self.assertTrue(payload["can_retry"])

    def test_a_pass_says_so_and_offers_nothing_further(self):
        record_session(session("verified", self.user,
                               verified_outputs={"dob": dob_for_age(25)}))
        payload = status_payload(profile_for(self.user))
        self.assertIn("Verified", payload["headline"])
        self.assertIsNone(payload["next_step"])

    def test_a_failure_says_why_and_offers_a_retry(self):
        record_session(session("requires_input", self.user,
                               last_error={"code": "selfie_face_mismatch"}))
        payload = status_payload(profile_for(self.user))
        self.assertIn("Didn't pass", payload["headline"])
        self.assertIn("didn't match", payload["detail"])
        self.assertEqual(payload["next_step"], "Try again")
        self.assertTrue(payload["can_retry"])

    def test_under_18_does_not_invite_a_pointless_retry(self):
        """Running the check again cannot change their date of birth."""
        record_session(session("verified", self.user,
                               verified_outputs={"dob": dob_for_age(14)}))
        payload = status_payload(profile_for(self.user))
        self.assertFalse(payload["can_retry"])
        self.assertIsNone(payload["next_step"])
        self.assertEqual(payload["reason"], REASON_UNDER_18)

    def test_the_failed_and_unstarted_states_are_never_identical(self):
        """The whole complaint: 'I did mine, I don't know if it passed.'"""
        blank = status_payload(profile_for(self.user))
        record_session(session("requires_input", self.user,
                               last_error={"code": "document_expired"}))
        failed = status_payload(profile_for(self.user))
        self.assertNotEqual(blank["status"], failed["status"])
        self.assertNotEqual(blank["headline"], failed["headline"])
        self.assertNotEqual(blank["detail"], failed["detail"])


class IdentityApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="api", password="verify-pass-3")
        self.client.force_authenticate(self.user)

    def test_get_returns_the_display_fields(self):
        r = self.client.get(reverse("economy-identity"))
        self.assertEqual(r.status_code, 200)
        for key in ("status", "headline", "detail", "can_retry", "verified_18plus"):
            self.assertIn(key, r.json())

    def test_get_reports_a_failure_after_the_webhook_lands(self):
        record_session(session("requires_input", self.user,
                               last_error={"code": "document_expired"}))
        body = self.client.get(reverse("economy-identity")).json()
        self.assertEqual(body["status"], Profile.VERIFY_FAILED)
        self.assertIn("expired", body["detail"])

    def test_starting_over_is_refused_for_an_under_18_result(self):
        record_session(session("verified", self.user,
                               verified_outputs={"dob": dob_for_age(12)}))
        r = self.client.post(reverse("economy-identity"), {}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_refresh_without_a_session_is_harmless(self):
        r = self.client.post(reverse("economy-identity"), {"action": "refresh"},
                             format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], Profile.VERIFY_UNSTARTED)
