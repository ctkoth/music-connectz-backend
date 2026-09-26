"""A member who joins through a provider is owed what a registered one gets.

`RegisterSerializer.create` paid the welcome 🍥, credited an inviter and
claimed the take scored at /try. The OAuth door did none of it — and every
brand-new OAuth account is made in exactly one place (the answer to "do you
already have an account?"), so the gap was total, not occasional. The trial
page and the signup screen both promise the welcome 🍥 up front, and the
one-tap doors were the ones that never paid it.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (SIGNUP_WELCOME_SPINAZ, Referral, TrialTake,
                                 wallet_for)

from .models import OAuthIdentity
from .views import _pending_token

User = get_user_model()


def info(uid="g-1", email="new@example.com", name="Some One"):
    return {"provider": "google", "uid": uid, "email": email,
            "email_verified": True, "name": name}


class JoiningWithAProviderIsJoining(TestCase):
    def join(self, **extra):
        """The real sequence: the pending answer is what opens the account."""
        return APIClient().post(
            "/api/auth/oauth/google/",
            {"pending": _pending_token(info()), **extra}, format="json")

    def test_the_welcome_bonus_is_paid(self):
        r = self.join()
        self.assertEqual(r.status_code, 200, r.data)
        user = User.objects.get(email="new@example.com")
        self.assertEqual(wallet_for(user).spinaz, SIGNUP_WELCOME_SPINAZ)

    def test_the_take_scored_at_the_door_is_kept(self):
        t = TrialTake.objects.create(token="tok123", app_key="singz",
                                     result={"score": 7})
        self.join(trial_token="tok123")
        t.refresh_from_db()
        self.assertEqual(t.claimed_by.email, "new@example.com")

    def test_an_invite_pays_both_sides(self):
        inviter = User.objects.create_user(username="inviter", email="i@example.com")
        self.join(ref="inviter")
        joinee = User.objects.get(email="new@example.com")
        self.assertTrue(Referral.objects.filter(referrer=inviter, joinee=joinee).exists())

    def test_a_junk_token_and_a_junk_referral_never_block_the_sign_in(self):
        r = self.join(trial_token="nonsense", ref="nobody-by-that-name")
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.data)

    def test_non_string_junk_never_blocks_the_sign_in(self):
        """These arrive from somebody who is not signed in."""
        r = self.join(trial_token={"x": 1}, ref=["a", "b"])
        self.assertEqual(r.status_code, 200)

    def test_a_failing_bonus_never_costs_the_account(self):
        with mock.patch("apps.accounts.welcome.award_signup_bonuses",
                        side_effect=RuntimeError("bonus had a bad day")):
            r = self.join()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(User.objects.filter(email="new@example.com").exists())
        self.assertIn("access", r.data)

    def test_a_returning_member_is_not_paid_again(self):
        """Signing in a second time reaches `made=False`. The welcome is a
        once-only reward, and the pending token can be replayed."""
        self.join()
        user = User.objects.get(email="new@example.com")
        before = wallet_for(user).spinaz
        self.join()
        self.assertEqual(wallet_for(user).spinaz, before)
        self.assertEqual(OAuthIdentity.objects.filter(user=user).count(), 1)
