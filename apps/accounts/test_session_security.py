"""Refresh-token rotation, revocation on reset, and the OAuth link route.

Two gaps this closes:

* A refresh token was valid for its full fourteen days and a password reset did
  nothing to it — the single action somebody takes when they think they've been
  compromised had no effect at all.
* The OAuth collision error told people to "link it from your account settings",
  and that route did not exist. Their options were a second account, which
  splits their wallet, or giving up.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import OAuthIdentity
from .serializers import issue_tokens, revoke_all_refresh_tokens

User = get_user_model()


def member(name, password="session-pass-1!"):
    return User.objects.create_user(username=name, email=f"{name}@example.com",
                                    password=password)


class RefreshRotationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = member("rotator")

    def test_refreshing_returns_a_new_refresh_token(self):
        tokens = issue_tokens(self.user)
        r = self.client.post(reverse("auth-refresh"),
                             {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("refresh", r.json(), "rotation is not switched on")
        self.assertNotEqual(r.json()["refresh"], tokens["refresh"])

    def test_the_old_refresh_token_stops_working(self):
        """Rotation without blacklisting isn't rotation — it just hands out
        more tokens while the old ones keep going."""
        tokens = issue_tokens(self.user)
        self.client.post(reverse("auth-refresh"), {"refresh": tokens["refresh"]},
                         format="json")
        again = self.client.post(reverse("auth-refresh"),
                                 {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(again.status_code, 401)

    def test_the_new_token_does_work(self):
        tokens = issue_tokens(self.user)
        rotated = self.client.post(reverse("auth-refresh"),
                                   {"refresh": tokens["refresh"]},
                                   format="json").json()["refresh"]
        r = self.client.post(reverse("auth-refresh"), {"refresh": rotated},
                             format="json")
        self.assertEqual(r.status_code, 200)


class RevokeOnPasswordResetTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = member("resetter")

    def test_revoking_kills_every_outstanding_token(self):
        stolen = issue_tokens(self.user)["refresh"]
        revoke_all_refresh_tokens(self.user)
        r = self.client.post(reverse("auth-refresh"), {"refresh": stolen},
                             format="json")
        self.assertEqual(r.status_code, 401)

    def test_it_only_touches_the_one_user(self):
        other = member("bystander")
        theirs = issue_tokens(other)["refresh"]
        issue_tokens(self.user)
        revoke_all_refresh_tokens(self.user)
        r = self.client.post(reverse("auth-refresh"), {"refresh": theirs},
                             format="json")
        self.assertEqual(r.status_code, 200)

    def test_a_password_reset_signs_other_sessions_out(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        stolen = issue_tokens(self.user)["refresh"]
        r = self.client.post(reverse("auth-password-reset"), {
            "uid": urlsafe_base64_encode(force_bytes(self.user.pk)),
            "token": default_token_generator.make_token(self.user),
            "new_password": "a-brand-new-password-9!",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.content)

        dead = self.client.post(reverse("auth-refresh"), {"refresh": stolen},
                                format="json")
        self.assertEqual(dead.status_code, 401,
                         "the attacker's session survived the reset")

    def test_the_person_resetting_stays_signed_in(self):
        """Revocation runs before the new pair is issued, so the reset doesn't
        immediately lock out the person doing it."""
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        r = self.client.post(reverse("auth-password-reset"), {
            "uid": urlsafe_base64_encode(force_bytes(self.user.pk)),
            "token": default_token_generator.make_token(self.user),
            "new_password": "another-brand-new-one-9!",
        }, format="json")
        fresh = r.json()["refresh"]
        ok = self.client.post(reverse("auth-refresh"), {"refresh": fresh},
                              format="json")
        self.assertEqual(ok.status_code, 200)


GOOGLE_INFO = {"provider": "google", "uid": "g-123",
               "email": "linker@example.com", "email_verified": True,
               "name": "Linker"}


class OAuthLinkTests(TestCase):
    def setUp(self):
        self.user = member("linker")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def link(self, client=None, info=None):
        with patch("apps.accounts.views.verify_google",
                   return_value=dict(info or GOOGLE_INFO)):
            return (client or self.client).post(
                reverse("auth-oauth-link", args=["google"]),
                {"credential": "tok"}, format="json")

    def test_linking_attaches_the_provider_to_this_account(self):
        r = self.link()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["providers"], ["google"])
        self.assertTrue(OAuthIdentity.objects.filter(
            user=self.user, provider="google").exists())

    def test_linking_twice_is_not_an_error(self):
        self.link()
        r = self.link()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["already_linked"])
        self.assertEqual(OAuthIdentity.objects.filter(user=self.user).count(), 1)

    def test_you_cannot_steal_a_provider_account_already_linked_elsewhere(self):
        """Re-pointing it would move somebody else's sign-in onto this
        account — an account takeover with extra steps."""
        theirs = member("someone_else")
        OAuthIdentity.objects.create(provider="google", provider_uid="g-123",
                                     user=theirs, email="x@example.com")
        r = self.link()
        self.assertEqual(r.status_code, 409)
        self.assertEqual(
            OAuthIdentity.objects.get(provider_uid="g-123").user_id, theirs.id)

    def test_it_needs_you_to_be_signed_in(self):
        """The safety of this route is the ordering: prove who you are with an
        existing session first, then prove you own the provider account."""
        r = self.link(client=APIClient())
        self.assertIn(r.status_code, (401, 403))

    def test_an_unknown_provider_is_a_400_not_a_500(self):
        r = self.client.post(reverse("auth-oauth-link", args=["myspace"]),
                             {"credential": "tok"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_the_link_route_does_not_shadow_the_login_route(self):
        self.assertNotEqual(reverse("auth-oauth-link", args=["google"]),
                            reverse("auth-oauth", args=["google"]))

    def test_after_linking_you_can_sign_in_with_that_provider(self):
        """The whole point — the collision the error message was about."""
        self.link()
        anon = APIClient()
        with patch("apps.accounts.views.verify_google",
                   return_value=dict(GOOGLE_INFO)):
            r = anon.post(reverse("auth-oauth", args=["google"]),
                          {"credential": "tok"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["user"]["username"], "linker")


class OAuthUnlinkTests(TestCase):
    def setUp(self):
        self.user = member("unlinker")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        OAuthIdentity.objects.create(provider="google", provider_uid="g-1",
                                     user=self.user, email="a@example.com")

    def test_unlinking_works_when_a_password_still_gets_you_in(self):
        r = self.client.delete(reverse("auth-oauth-link", args=["google"]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["providers"], [])

    def test_you_cannot_unlink_your_only_way_in(self):
        self.user.set_unusable_password()
        self.user.save(update_fields=["password"])
        r = self.client.delete(reverse("auth-oauth-link", args=["google"]))
        self.assertEqual(r.status_code, 409)
        self.assertIn("only way", r.json()["detail"])

    def test_unlinking_something_that_was_never_linked_is_a_404(self):
        r = self.client.delete(reverse("auth-oauth-link", args=["github"]))
        self.assertEqual(r.status_code, 404)
