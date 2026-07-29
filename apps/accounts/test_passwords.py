from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import Profile
from apps.accounts.passwords import SENT_DETAIL, reset_link_for

User = get_user_model()
OLD = "old-password-123"
NEW = "brand-new-password-456"

FORGOT = "/api/auth/password/forgot/"
RESET = "/api/auth/password/reset/"


def link_parts(user):
    link = reset_link_for(user)
    query = link.split("?", 1)[1]
    return dict(p.split("=", 1) for p in query.split("&"))


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   FRONTEND_URL="https://musicconnectz.net")
class ForgotPasswordTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("member", "member@example.com", OLD)
        Profile.objects.create(user=self.user, phone="+15550001111")

    def test_emails_a_link_pointing_at_the_frontend_reset_page(self):
        resp = self.client.post(FORGOT, {"identifier": "member@example.com"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn("https://musicconnectz.net/reset-password?uid=", body)
        self.assertIn("&token=", body)
        self.assertEqual(mail.outbox[0].to, ["member@example.com"])

    def test_username_and_phone_also_find_the_account(self):
        for ident in ("member", "+15550001111"):
            mail.outbox.clear()
            with self.subTest(identifier=ident):
                self.client.post(FORGOT, {"identifier": ident}, format="json")
                self.assertEqual(len(mail.outbox), 1)

    def test_unknown_account_is_indistinguishable_from_a_known_one(self):
        """Differing responses would let anyone test which emails are members."""
        known = self.client.post(FORGOT, {"identifier": "member@example.com"}, format="json")
        mail.outbox.clear()
        unknown = self.client.post(FORGOT, {"identifier": "nobody@example.com"}, format="json")
        self.assertEqual(unknown.status_code, known.status_code)
        self.assertEqual(unknown.data, known.data)
        self.assertEqual(unknown.data["detail"], SENT_DETAIL)
        self.assertEqual(len(mail.outbox), 0)  # but nothing was actually sent

    def test_blank_identifier_does_not_error(self):
        resp = self.client.post(FORGOT, {"identifier": ""}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)


@override_settings(FRONTEND_URL="https://musicconnectz.net")
class ResetPasswordTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("member", "member@example.com", OLD)

    def test_valid_token_sets_the_password_and_returns_a_session(self):
        parts = link_parts(self.user)
        resp = self.client.post(RESET, {**parts, "new_password": NEW}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW))
        # and the new password actually logs in
        login = self.client.post("/api/auth/login/",
                                 {"identifier": "member", "password": NEW}, format="json")
        self.assertEqual(login.status_code, 200)

    def test_a_token_cannot_be_replayed(self):
        parts = link_parts(self.user)
        self.client.post(RESET, {**parts, "new_password": NEW}, format="json")
        again = self.client.post(RESET, {**parts, "new_password": "third-password-789"},
                                 format="json")
        self.assertEqual(again.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW))  # unchanged by the replay

    def test_tampered_token_and_uid_are_rejected(self):
        parts = link_parts(self.user)
        for bad in ({**parts, "token": "not-a-token"},
                    {**parts, "uid": "zzzz"},
                    {"uid": "", "token": "", }):
            with self.subTest(payload=bad):
                resp = self.client.post(RESET, {**bad, "new_password": NEW}, format="json")
                self.assertEqual(resp.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD))

    def test_another_users_token_does_not_work_on_this_uid(self):
        other = User.objects.create_user("other", "other@example.com", OLD)
        mine = link_parts(self.user)
        theirs = link_parts(other)
        resp = self.client.post(RESET, {"uid": mine["uid"], "token": theirs["token"],
                                        "new_password": NEW}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_weak_password_is_refused_with_the_reason(self):
        parts = link_parts(self.user)
        resp = self.client.post(RESET, {**parts, "new_password": "123"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(len(resp.data["detail"]) > 10)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(OLD))

    def test_oauth_account_without_a_usable_password_can_set_one(self):
        oauth_user = User.objects.create_user("oauthy", "oauthy@example.com")
        oauth_user.set_unusable_password()
        oauth_user.save()
        parts = link_parts(oauth_user)
        resp = self.client.post(RESET, {**parts, "new_password": NEW}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        oauth_user.refresh_from_db()
        self.assertTrue(oauth_user.check_password(NEW))
