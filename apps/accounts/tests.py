from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.economy.models import profile_for

User = get_user_model()

PASSWORD = "hunter2hunter2"


class AuthFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_sets_zodiac_from_birthday(self):
        resp = self.client.post(
            "/api/auth/register/",
            {"username": "tester", "email": "t@example.com", "password": PASSWORD,
             "birthday": "1990-01-20"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["user"]["zodiac"], "Aquarius")
        self.assertEqual(resp.data["user"]["birthday"], "1990-01-20")

    def test_login_by_email_then_patch_overlong_profile(self):
        self.client.post(
            "/api/auth/register/",
            {"username": "tester", "email": "t@example.com", "password": PASSWORD},
            format="json",
        )
        resp = self.client.post(
            "/api/auth/login/",
            {"identifier": "t@example.com", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

        # Short identifier columns are truncated to their own width. Slicing
        # everything to 500 raised a DataError (500) on Postgres.
        resp = self.client.patch(
            "/api/auth/me/",
            {"display_name": "D" * 400, "location": "L" * 400,
             "gender": "G" * 400, "bio": "B" * 300},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        profile = profile_for(User.objects.get(username="tester"))
        self.assertEqual(len(profile.display_name), 80)
        self.assertEqual(len(profile.location), 120)
        self.assertEqual(len(profile.gender), 24)
        # The bio is prose, so it answers to the tier's character limit rather
        # than a column width — 300 fits even on Free's 400.
        self.assertEqual(len(profile.bio), 300)

    def test_me_refuses_a_bio_over_the_tier_limit(self):
        """The bio used to be sliced to the column width here, which silently
        cut a Premium member. It is now refused with the cap named."""
        user = User.objects.create_user("bio", "bio@example.com", PASSWORD)
        self.client.force_authenticate(user)
        resp = self.client.patch("/api/auth/me/", {"bio": "B" * 900}, format="json")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.data["char_limit"], 400)   # Free
        self.assertEqual(profile_for(user).bio, "")

    def test_me_accepts_a_bio_the_tier_allows(self):
        from apps.economy.models import TIER_PREMIUM, membership_for
        user = User.objects.create_user("prem", "prem@example.com", PASSWORD)
        m = membership_for(user)
        m.tier = TIER_PREMIUM
        m.save(update_fields=["tier", "updated_at"])
        self.client.force_authenticate(user)
        resp = self.client.patch("/api/auth/me/", {"bio": "B" * 1500}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(profile_for(user).bio), 1500)

    def test_me_does_not_fan_out_queries(self):
        """The profile/wallet/membership rows behind /api/auth/me/ are read once
        each. Resolving them per-field cost 11 round-trips on every page load."""
        user = User.objects.create_user("q", "q@example.com", PASSWORD)
        self.client.force_authenticate(user)
        self.client.get("/api/auth/me/")  # create the rows first
        with CaptureQueriesContext(connection) as queries:
            resp = self.client.get("/api/auth/me/")
        self.assertEqual(resp.status_code, 200)
        # 6 for the rows above, +1 for `connections` — one SELECT for the whole
        # list, not one per link. The number is a ceiling on fan-out, so it may
        # rise when a field genuinely adds a read and must never rise because a
        # field started reading per row.
        self.assertLessEqual(len(queries), 7, [q["sql"] for q in queries])

    def test_connections_is_one_query_however_many_are_linked(self):
        """The ceiling above only means something if it holds at three links as
        well as one — a per-row read passes at one and fans out in production."""
        from apps.accounts.models import OAuthIdentity

        user = User.objects.create_user("many", "many@example.com", PASSWORD)
        for n, provider in enumerate(("google", "spotify", "soundcloud")):
            OAuthIdentity.objects.create(user=user, provider=provider,
                                         provider_uid=f"uid-{n}", email="many@example.com")
        self.client.force_authenticate(user)
        self.client.get("/api/auth/me/")
        with CaptureQueriesContext(connection) as queries:
            resp = self.client.get("/api/auth/me/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["connections"]), 3)
        self.assertLessEqual(len(queries), 7, [q["sql"] for q in queries])


class OAuthLinkingTests(TestCase):
    """Matching an OAuth sign-in to an existing account by email hands over
    that account, so it must only happen on a provider-verified address."""

    def setUp(self):
        self.existing = User.objects.create_user("owner", "owner@example.com", PASSWORD)

    def _info(self, **over):
        info = {"provider": "spotify", "uid": "uid-1", "email": "owner@example.com",
                "email_verified": False, "name": "Owner", "avatar_url": ""}
        info.update(over)
        return info

    def test_verified_email_links_to_the_existing_account(self):
        from apps.accounts.views import _user_from_oauth
        user = _user_from_oauth(self._info(provider="google", email_verified=True))
        self.assertEqual(user.pk, self.existing.pk)

    def test_unverified_email_is_refused_not_silently_linked(self):
        from apps.accounts.oauth import OAuthError
        from apps.accounts.views import _user_from_oauth
        with self.assertRaises(OAuthError):
            _user_from_oauth(self._info())
        # and no shadow account was opened on that address either
        self.assertEqual(User.objects.filter(email__iexact="owner@example.com").count(), 1)

    def test_unverified_email_with_no_clash_still_creates_an_account(self):
        from apps.accounts.views import _user_from_oauth
        user = _user_from_oauth(self._info(email="nobody@example.com"))
        self.assertNotEqual(user.pk, self.existing.pk)
        self.assertEqual(user.email, "nobody@example.com")

    def test_known_identity_short_circuits_before_any_email_check(self):
        from apps.accounts.models import OAuthIdentity
        from apps.accounts.views import _user_from_oauth
        OAuthIdentity.objects.create(provider="spotify", provider_uid="uid-1", user=self.existing)
        # Same unverified payload that is refused above — a linked identity wins.
        self.assertEqual(_user_from_oauth(self._info()).pk, self.existing.pk)


class OAuthVerifierShapeTests(TestCase):
    """Every verifier must declare email_verified — a missing key is falsy and
    would quietly disable linking for a provider that does verify."""

    def test_generic_code_flow_never_claims_verification(self):
        import apps.accounts.oauth as oauth_mod
        captured = {}

        class FakeResp:
            status_code = 200
            def json(self):
                return captured["payload"]

        captured["payload"] = {"access_token": "t"}
        orig_post, orig_get = oauth_mod.requests.post, oauth_mod.requests.get
        oauth_mod.requests.post = lambda *a, **k: FakeResp()
        oauth_mod.requests.get = lambda *a, **k: type(
            "R", (), {"json": lambda self: {"id": "42", "email": "x@example.com",
                                            "display_name": "X", "images": []}}
        )()
        try:
            import os
            os.environ["SPOTIFY_OAUTH_CLIENT_ID"] = "id"
            os.environ["SPOTIFY_OAUTH_CLIENT_SECRET"] = "secret"
            info = oauth_mod.exchange_oauth2("spotify", "code", "https://x/cb")
        finally:
            oauth_mod.requests.post, oauth_mod.requests.get = orig_post, orig_get
            os.environ.pop("SPOTIFY_OAUTH_CLIENT_ID", None)
            os.environ.pop("SPOTIFY_OAUTH_CLIENT_SECRET", None)
        self.assertIn("email_verified", info)
        self.assertIs(info["email_verified"], False)


class DisconnectTests(TestCase):
    """Linking shipped without an unlink, so a provider attached to the wrong
    account could only be moved with a database shell — and `_user_from_oauth`
    matches a known uid before anything else, so the member was returned to
    that account on every sign-in with no way out on any screen."""

    def setUp(self):
        from apps.accounts.models import OAuthIdentity

        self.client = APIClient()
        self.user = User.objects.create_user("dis", "dis@example.com", PASSWORD)
        OAuthIdentity.objects.create(user=self.user, provider="soundcloud",
                                     provider_uid="sc-1", email="dis@example.com")
        self.client.force_authenticate(self.user)

    def test_disconnect_removes_the_link(self):
        r = self.client.delete("/api/auth/oauth/soundcloud/link/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.user.oauth_identities.count(), 0)

    def test_disconnecting_what_is_not_linked_says_so(self):
        r = self.client.delete("/api/auth/oauth/spotify/link/")
        self.assertEqual(r.status_code, 404)

    def test_it_never_removes_the_only_way_in(self):
        """An OAuth signup gets set_unusable_password(), so for that member the
        provider IS the password. Removing the last one locks them out of an
        account nobody can then prove is theirs."""
        self.user.set_unusable_password()
        self.user.save()
        r = self.client.delete("/api/auth/oauth/soundcloud/link/")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(self.user.oauth_identities.count(), 1)

    def test_a_second_link_makes_the_first_removable_again(self):
        from apps.accounts.models import OAuthIdentity

        self.user.set_unusable_password()
        self.user.save()
        OAuthIdentity.objects.create(user=self.user, provider="spotify",
                                     provider_uid="sp-1", email="dis@example.com")
        r = self.client.delete("/api/auth/oauth/soundcloud/link/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.user.oauth_identities.count(), 1)

    def test_it_only_ever_removes_your_own(self):
        """The provider comes from the URL and the row from request.user, so
        there is nowhere to name somebody else's link."""
        from apps.accounts.models import OAuthIdentity

        other = User.objects.create_user("other", "other@example.com", PASSWORD)
        OAuthIdentity.objects.create(user=other, provider="spotify",
                                     provider_uid="sp-other", email="other@example.com")
        r = self.client.delete("/api/auth/oauth/spotify/link/")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(other.oauth_identities.count(), 1)

    def test_signed_out_cannot_disconnect(self):
        self.client.force_authenticate(None)
        r = self.client.delete("/api/auth/oauth/soundcloud/link/")
        self.assertEqual(r.status_code, 401)


class RealNameTests(TestCase):
    """A real name is stored and shown. It is never matched on: a provider's
    display name is typed by its owner and verified by nobody, so linking an
    account on one would hand it to whoever typed it."""

    def setUp(self):
        self.client = APIClient()

    def _info(self, **over):
        info = {"provider": "spotify", "uid": "sp-1", "email": "new@example.com",
                "email_verified": False, "name": "Corey Knap", "avatar_url": ""}
        info.update(over)
        return info

    def test_a_new_account_is_prefilled_from_the_provider(self):
        from apps.accounts.views import _user_from_oauth
        user = _user_from_oauth(self._info())
        self.assertEqual(user.first_name, "Corey")
        self.assertEqual(user.last_name, "Knap")

    def test_a_multi_word_surname_stays_whole(self):
        from apps.accounts.views import _user_from_oauth
        user = _user_from_oauth(self._info(name="Ana de la Cruz"))
        self.assertEqual(user.first_name, "Ana")
        self.assertEqual(user.last_name, "de la Cruz")

    def test_one_word_name_leaves_the_surname_blank(self):
        from apps.accounts.views import _user_from_oauth
        user = _user_from_oauth(self._info(name="Prince"))
        self.assertEqual(user.first_name, "Prince")
        self.assertEqual(user.last_name, "")

    def test_a_returning_member_keeps_the_name_they_typed(self):
        """The prefill is on the create branch only. A provider that changes
        somebody's display name must not rewrite what they corrected here."""
        from apps.accounts.models import OAuthIdentity
        from apps.accounts.views import _user_from_oauth

        mine = User.objects.create_user("mine", "mine@example.com", PASSWORD)
        mine.first_name, mine.last_name = "Kay", "Oth"
        mine.save()
        OAuthIdentity.objects.create(user=mine, provider="spotify", provider_uid="sp-1")

        again = _user_from_oauth(self._info(name="Somebody Else"))
        self.assertEqual(again.pk, mine.pk)
        again.refresh_from_db()
        self.assertEqual((again.first_name, again.last_name), ("Kay", "Oth"))

    def test_a_shared_name_never_matches_an_account(self):
        """The whole reason this is display-only. Two members called the same
        thing stay two members."""
        from apps.accounts.views import _user_from_oauth

        first = User.objects.create_user("real", "real@example.com", PASSWORD)
        first.first_name, first.last_name = "Corey", "Knap"
        first.save()

        impostor = _user_from_oauth(self._info(uid="sp-2", email="other@example.com"))
        self.assertNotEqual(impostor.pk, first.pk)

    def test_the_name_is_private_until_the_member_says_otherwise(self):
        from apps.economy.models import profile_for, public_name

        user = User.objects.create_user("priv", "priv@example.com", PASSWORD)
        user.first_name, user.last_name = "Corey", "Knap"
        user.save()
        p = profile_for(user)
        self.assertEqual(public_name(p), "")

        p.visibility = {"first_name": "public", "last_name": "public"}
        p.save()
        self.assertEqual(public_name(p), "Corey Knap")

    def test_the_member_can_set_and_publish_their_name(self):
        from apps.economy.models import profile_for

        user = User.objects.create_user("edit", "edit@example.com", PASSWORD)
        self.client.force_authenticate(user)
        r = self.client.patch(
            "/api/auth/me/",
            {"first_name": "Corey", "last_name": "Knap",
             "visibility": {"first_name": "public"}}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.last_name), ("Corey", "Knap"))
        self.assertEqual(profile_for(user).visibility["first_name"], ["public"])
        self.assertEqual(r.data["first_name"], "Corey")
        levels = {row["field"]: row["level"] for row in r.data["visibility"]}
        self.assertEqual(levels["first_name"], ["public"])
