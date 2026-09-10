"""One person, one account — at the two places OAuth could open a second one.

The rule is in `apps/economy/rulez.py` and DupeZ enforces it after the fact.
These are the two things that stop one being MADE:

  * a database-level unique index on LOWER(email), because the application's
    own `email__iexact` check is a check-then-insert with a gap in the middle;
  * a question, on the one path where neither the identity nor a verified
    address can say who this is.

Twitter is why the second exists. Its API returns no email at all, so before
this every Twitter sign-in by an existing member opened a second account —
not occasionally, every single time.
"""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import OAuthIdentity
from .views import _user_from_oauth, _pending_token

User = get_user_model()


def info(provider="twitter", uid="t-1", email="", verified=False, name="Some One"):
    return {"provider": provider, "uid": uid, "email": email,
            "email_verified": verified, "name": name}


class TheDatabaseRefusesASecondAddress(TestCase):
    """The app check is racy; this one is not."""

    def test_the_same_address_in_another_case_is_refused(self):
        User.objects.create_user(username="a", email="Corey@Example.com")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(username="b", email="corey@example.com")

    def test_members_with_no_address_do_not_collide(self):
        """Every account made through a provider that gives no email holds ''.

        A unique index without the partial clause would let the first one in
        and refuse everybody after — the constraint meant to stop duplicates
        would instead stop signups.
        """
        with transaction.atomic():
            User.objects.create_user(username="t1", email="")
            User.objects.create_user(username="t2", email="")
            User.objects.create_user(username="t3", email="")
        self.assertEqual(User.objects.filter(email="").count(), 3)

    def test_different_addresses_are_unaffected(self):
        User.objects.create_user(username="c", email="one@example.com")
        User.objects.create_user(username="d", email="two@example.com")
        self.assertEqual(User.objects.count(), 2)


class TheQuestionIsOnlyAskedWhenWeCannotTell(TestCase):
    def setUp(self):
        self.existing = User.objects.create_user(
            username="member", email="member@example.com")

    def test_a_known_identity_never_asks(self):
        """The common path. A returning member is decided by a unique
        constraint, so asking them would be friction on top of certainty."""
        OAuthIdentity.objects.create(
            user=self.existing, provider="twitter", provider_uid="t-1")
        user, made = _user_from_oauth(info(), with_created=True, create=False)
        self.assertEqual(user, self.existing)
        self.assertFalse(made)

    def test_a_verified_email_match_links_silently(self):
        user, made = _user_from_oauth(
            info(provider="google", uid="g-1",
                 email="member@example.com", verified=True),
            with_created=True, create=False)
        self.assertEqual(user, self.existing)
        self.assertFalse(made)
        self.assertTrue(OAuthIdentity.objects.filter(
            user=self.existing, provider="google").exists())

    def test_an_unknown_identity_with_no_email_asks_instead_of_creating(self):
        """The Twitter case, and the whole point."""
        before = User.objects.count()
        user, made = _user_from_oauth(info(), with_created=True, create=False)
        self.assertIsNone(user)
        self.assertFalse(made)
        self.assertEqual(User.objects.count(), before)   # nothing was opened

    def test_an_unverified_email_match_is_still_refused_not_asked(self):
        """Refusing here protects the ACCOUNT, not just the count — a provider
        that lets somebody claim an arbitrary address would otherwise be a way
        in to anybody's."""
        from .oauth import OAuthError
        with self.assertRaises(OAuthError):
            _user_from_oauth(
                info(provider="spotify", uid="s-1",
                     email="member@example.com", verified=False),
                with_created=True, create=False)


class AnsweringTheQuestion(TestCase):
    """The answer travels on a token we signed, because the authorization code
    was spent on the first exchange and cannot be replayed."""

    def test_saying_i_am_new_opens_the_account(self):
        before = User.objects.count()
        r = self.client.post(
            "/api/auth/oauth/twitter/",
            {"pending": _pending_token(info())}, "application/json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.json())
        self.assertEqual(User.objects.count(), before + 1)

    def test_the_new_account_is_linked_so_the_next_sign_in_never_asks(self):
        self.client.post("/api/auth/oauth/twitter/",
                         {"pending": _pending_token(info())}, "application/json")
        user, made = _user_from_oauth(info(), with_created=True, create=False)
        self.assertIsNotNone(user)
        self.assertFalse(made)

    def test_a_token_for_another_provider_is_refused(self):
        r = self.client.post(
            "/api/auth/oauth/google/",
            {"pending": _pending_token(info(provider="twitter"))},
            "application/json")
        self.assertEqual(r.status_code, 400)

    def test_a_forged_token_is_refused(self):
        r = self.client.post("/api/auth/oauth/twitter/",
                             {"pending": "not.a.real.token"}, "application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_a_tampered_token_is_refused(self):
        """The uid decides which account this becomes, so it must be ours."""
        tok = _pending_token(info())
        r = self.client.post("/api/auth/oauth/twitter/",
                             {"pending": tok[:-4] + "AAAA"}, "application/json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_saying_i_am_new_twice_does_not_open_two(self):
        """A double-submitted answer is one account, because the second pass
        finds the identity the first one wrote."""
        tok = _pending_token(info())
        self.client.post("/api/auth/oauth/twitter/", {"pending": tok}, "application/json")
        self.client.post("/api/auth/oauth/twitter/", {"pending": tok}, "application/json")
        self.assertEqual(User.objects.count(), 1)
