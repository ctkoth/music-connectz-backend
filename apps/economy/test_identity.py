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


@override_settings(STRIPE_SECRET_KEY="sk_test_x")
class DobIsExpandedTests(TestCase):
    """Stripe leaves `verified_outputs.dob` out unless it is expanded by name, so expanding only
    `verified_outputs` read every passed check as "date of birth could not be read"."""

    def setUp(self):
        self.u = User.objects.create_user("dobm", "d@e.com", "pw-Long-enough-1")

    def test_the_retrieve_expands_the_dob_itself(self):
        full = {"id": "vs_9", "status": "verified", "metadata": {"user_id": str(self.u.id)},
                "verified_outputs": {"dob": dob(34)}}
        with patch("stripe.identity.VerificationSession.retrieve", return_value=full) as m:
            row = apply_session({"id": "vs_9", "status": "verified", "metadata": {"user_id": str(self.u.id)}})
        self.assertIn("verified_outputs.dob", m.call_args.kwargs["expand"])
        self.assertEqual(row.status, IdentityCheck.VERIFIED)
        self.assertTrue(profile_for(self.u).verified_18plus)

    def test_an_unreadable_check_is_read_again_without_a_new_scan(self):
        IdentityCheck.objects.create(user=self.u, session_id="vs_8", status=IdentityCheck.UNREADABLE, reason="unreadable")
        full = {"id": "vs_8", "status": "verified", "metadata": {"user_id": str(self.u.id)},
                "verified_outputs": {"dob": dob(34)}}
        from apps.economy.identity import refresh
        with patch("stripe.identity.VerificationSession.retrieve", return_value=full):
            refresh(self.u)
        self.assertEqual(IdentityCheck.objects.get(session_id="vs_8").status, IdentityCheck.VERIFIED)
        self.assertTrue(profile_for(self.u).verified_18plus)

    def test_other_endings_stay_final(self):
        IdentityCheck.objects.create(user=self.u, session_id="vs_7", status=IdentityCheck.FAILED, reason="document_expired")
        row = apply_session({"id": "vs_7", "status": "verified", "metadata": {"user_id": str(self.u.id)},
                             "verified_outputs": {"dob": dob(34)}})
        self.assertEqual(row.status, IdentityCheck.FAILED)


@override_settings(STRIPE_SECRET_KEY="sk_test_x", FRONTEND_URL="https://x.test")
class StuckChecksTests(TestCase):
    """A member's ID check read 'still checking' for weeks. The cause: only checks younger than two days were ever
    re-asked of Stripe, so one that ended while no webhook was listening stayed open for ever."""

    def setUp(self):
        from datetime import timedelta
        from django.utils import timezone
        self.u = User.objects.create_user("stuck", "s@e.com", "pw-Long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.u)
        self.ago = lambda **kw: timezone.now() - timedelta(**kw)

    def _row(self, sid, status, age):
        r = IdentityCheck.objects.create(user=self.u, session_id=sid, status=status)
        IdentityCheck.objects.filter(pk=r.pk).update(created_at=age)
        return r

    def test_a_check_weeks_old_is_asked_of_stripe_and_a_pass_is_recorded(self):
        self._row("vs_old", IdentityCheck.PROCESSING, self.ago(days=21))
        full = {"id": "vs_old", "status": "verified", "metadata": {"user_id": str(self.u.id)}, "verified_outputs": {"dob": dob(30)}}
        with patch("stripe.identity.VerificationSession.retrieve", return_value=full):
            g = self.c.get("/api/economy/identity/").json()
        self.assertTrue(g["verified_18plus"])
        self.assertEqual(g["last"]["result"], "success")

    def test_a_check_stripe_no_longer_knows_is_closed_not_pending_for_ever(self):
        self._row("vs_gone", IdentityCheck.PROCESSING, self.ago(days=10))

        class Gone(Exception):
            code = "resource_missing"
        with patch("stripe.identity.VerificationSession.retrieve", side_effect=Gone()):
            g = self.c.get("/api/economy/identity/").json()
        self.assertEqual(g["last"]["result"], "failure")
        self.assertTrue(g["can_start"])

    def test_a_link_nobody_finished_in_two_days_is_over(self):
        self._row("vs_abn", IdentityCheck.STARTED, self.ago(days=5))
        full = {"id": "vs_abn", "status": "requires_input", "metadata": {"user_id": str(self.u.id)}}
        with patch("stripe.identity.VerificationSession.retrieve", return_value=full):
            g = self.c.get("/api/economy/identity/").json()
        self.assertEqual(g["last"]["result"], "failure")
        self.assertEqual(g["last"]["reason"], "abandoned")

    def test_an_unfinished_check_says_it_is_waiting_on_you_not_on_stripe(self):
        self._row("vs_new", IdentityCheck.STARTED, self.ago(minutes=5))
        full = {"id": "vs_new", "status": "requires_input", "metadata": {"user_id": str(self.u.id)}}
        with patch("stripe.identity.VerificationSession.retrieve", return_value=full):
            g = self.c.get("/api/economy/identity/").json()
        self.assertTrue(g["last"]["needs_you"])
        self.assertNotIn("Stripe is still checking", g["last"]["detail"])

    def test_a_stuck_processing_check_says_so_and_does_not_block_a_new_one(self):
        self._row("vs_stuck", IdentityCheck.PROCESSING, self.ago(days=9))
        still = {"id": "vs_stuck", "status": "processing", "metadata": {"user_id": str(self.u.id)}}

        class S:
            id = "vs_fresh"; url = "https://verify.stripe.test/vs_fresh"; client_secret = "cs"
        with patch("stripe.identity.VerificationSession.retrieve", return_value=still):
            g = self.c.get("/api/economy/identity/").json()
            self.assertTrue(g["last"]["stale"])
            self.assertIn("9 days", g["last"]["detail"])
            with patch("stripe.identity.VerificationSession.create", return_value=S()) as m:
                r = self.c.post("/api/economy/identity/", {}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["id"], "vs_fresh")
        m.assert_called_once()

    def test_a_recent_processing_check_still_holds_the_door(self):
        self._row("vs_wait", IdentityCheck.PROCESSING, self.ago(minutes=10))
        still = {"id": "vs_wait", "status": "processing", "metadata": {"user_id": str(self.u.id)}}
        with patch("stripe.identity.VerificationSession.retrieve", return_value=still), \
                patch("stripe.identity.VerificationSession.create") as m:
            r = self.c.post("/api/economy/identity/", {}, format="json")
        self.assertTrue(r.json()["pending"])
        m.assert_not_called()
