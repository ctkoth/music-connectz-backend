from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.economy.identity import apply_session
from apps.economy.models import IdentityCheck, profile_for

User = get_user_model()


def dob(age):
    t = date.today()
    return {"day": 1, "month": 1, "year": t.year - age - 1}


@override_settings(STRIPE_SECRET_KEY="sk_test_x", FRONTEND_URL="https://x.test")
class IdentityResultsTests(TestCase):
    """Every ID check ends in a stated SUCCESS or FAILURE; success closes the door to new scans."""

    def setUp(self):
        self.u = User.objects.create_user("idm", "i@e.com", "pw-Long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def _start(self, sid="vs_1"):
        class S:
            id = sid; url = f"https://verify.stripe.test/{sid}"; client_secret = "cs"
        with patch("stripe.identity.VerificationSession.create", return_value=S()) as m:
            r = self.c.post("/api/economy/identity/", {}, format="json")
        return r, m

    def _end(self, sid, **kw):
        s = {"id": sid, "metadata": {"user_id": str(self.u.id)}}
        s.update(kw)
        with patch("apps.economy.identity.refresh"):
            return apply_session(s)

    def test_success_says_success_and_refuses_a_new_scan(self):
        self._start()
        self._end("vs_1", status="verified", verified_outputs={"dob": dob(30)})
        g = self.c.get("/api/economy/identity/").json() if False else None
        with patch("apps.economy.identity.refresh"):
            g = self.c.get("/api/economy/identity/").json()
            self.assertTrue(g["verified_18plus"])
            self.assertEqual(g["last"]["result"], "success")
            self.assertFalse(g["can_start"])
            r, m = self._start("vs_2")
        self.assertTrue(r.json()["already"])
        m.assert_not_called()                                     # no second Stripe session was paid for

    def test_failure_says_failure_and_why(self):
        self._start()
        self._end("vs_1", status="requires_input", last_error={"code": "document_expired"})
        with patch("apps.economy.identity.refresh"):
            g = self.c.get("/api/economy/identity/").json()
        self.assertFalse(g["verified_18plus"])
        self.assertEqual(g["last"]["result"], "failure")
        self.assertEqual(g["last"]["reason"], "document_expired")
        self.assertIn("expired", g["last"]["detail"])
        self.assertEqual(g["attempts_left_today"], 2)

    def test_an_id_that_proves_under_18_is_a_stated_failure_and_grants_nothing(self):
        self._start()
        self._end("vs_1", status="verified", verified_outputs={"dob": dob(15)})
        self.assertFalse(profile_for(self.u).verified_18plus)
        self.assertEqual(IdentityCheck.objects.get().status, "under_18")
        with patch("apps.economy.identity.refresh"):
            g = self.c.get("/api/economy/identity/").json()
        self.assertEqual(g["last"]["result"], "failure")
        self.assertIn("under 18", g["last"]["detail"])

    def test_an_unreadable_dob_is_a_stated_failure_not_silence(self):
        self._start()
        with patch("apps.economy.identity._verified_dob", return_value={}):
            self._end("vs_1", status="verified")
        self.assertEqual(IdentityCheck.objects.get().status, "unreadable")

    def test_still_waiting_on_the_member_is_not_an_ending(self):
        self._start()
        self._end("vs_1", status="requires_input", last_error=None)
        self.assertEqual(IdentityCheck.objects.get().status, "started")

    def test_a_third_failure_blocks_a_fourth_scan_and_repeats_the_reason(self):
        for i in range(3):
            self._start(f"vs_{i}")
            self._end(f"vs_{i}", status="requires_input", last_error={"code": "selfie_face_mismatch"})
        with patch("apps.economy.identity.refresh"):
            r, m = self._start("vs_9")
        self.assertEqual(r.status_code, 429)
        self.assertIn("selfie did not match", r.json()["detail"])
        m.assert_not_called()

    def test_an_open_check_is_reused_not_duplicated(self):
        self._start("vs_1")
        with patch("apps.economy.identity.refresh"):
            r, m = self._start("vs_2")
        self.assertTrue(r.json()["reused"])
        m.assert_not_called()

    def test_a_final_result_is_not_overwritten_by_a_late_event(self):
        self._start()
        self._end("vs_1", status="verified", verified_outputs={"dob": dob(30)})
        self._end("vs_1", status="requires_input", last_error={"code": "document_expired"})
        self.assertEqual(IdentityCheck.objects.get().status, "verified")

    def test_a_session_cannot_be_applied_to_somebody_elses_row(self):
        self._start()
        other = User.objects.create_user("idother", "o@e.com", "pw-Long-enough-1")
        self.assertIsNone(apply_session({"id": "vs_1", "status": "verified",
                                         "metadata": {"user_id": str(other.id)},
                                         "verified_outputs": {"dob": dob(30)}}))
        self.assertFalse(profile_for(other).verified_18plus)
