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
        self.assertLessEqual(len(queries), 6, [q["sql"] for q in queries])


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

    def test_discord_trusts_its_own_verified_flag(self):
        # Discord is the one provider here whose profile response actually
        # says whether the address was confirmed — the generic default of
        # False must not stomp on that.
        import apps.accounts.oauth as oauth_mod

        class FakeResp:
            status_code = 200
            def json(self):
                return {"access_token": "t"}

        orig_post, orig_get = oauth_mod.requests.post, oauth_mod.requests.get
        oauth_mod.requests.post = lambda *a, **k: FakeResp()
        oauth_mod.requests.get = lambda *a, **k: type(
            "R", (), {"json": lambda self: {
                "id": "99", "email": "d@example.com", "verified": True,
                "username": "dee", "global_name": "Dee", "avatar": "abc123",
            }}
        )()
        try:
            import os
            os.environ["DISCORD_OAUTH_CLIENT_ID"] = "id"
            os.environ["DISCORD_OAUTH_CLIENT_SECRET"] = "secret"
            info = oauth_mod.exchange_oauth2("discord", "code", "https://x/cb")
        finally:
            oauth_mod.requests.post, oauth_mod.requests.get = orig_post, orig_get
            os.environ.pop("DISCORD_OAUTH_CLIENT_ID", None)
            os.environ.pop("DISCORD_OAUTH_CLIENT_SECRET", None)
        self.assertIs(info["email_verified"], True)
        self.assertEqual(info["name"], "Dee")
        self.assertEqual(info["avatar_url"], "https://cdn.discordapp.com/avatars/99/abc123.png")

    def test_discord_unverified_email_does_not_claim_verification(self):
        import apps.accounts.oauth as oauth_mod

        class FakeResp:
            status_code = 200
            def json(self):
                return {"access_token": "t"}

        orig_post, orig_get = oauth_mod.requests.post, oauth_mod.requests.get
        oauth_mod.requests.post = lambda *a, **k: FakeResp()
        oauth_mod.requests.get = lambda *a, **k: type(
            "R", (), {"json": lambda self: {
                "id": "99", "email": "d@example.com", "verified": False,
                "username": "dee", "avatar": None,
            }}
        )()
        try:
            import os
            os.environ["DISCORD_OAUTH_CLIENT_ID"] = "id"
            os.environ["DISCORD_OAUTH_CLIENT_SECRET"] = "secret"
            info = oauth_mod.exchange_oauth2("discord", "code", "https://x/cb")
        finally:
            oauth_mod.requests.post, oauth_mod.requests.get = orig_post, orig_get
            os.environ.pop("DISCORD_OAUTH_CLIENT_ID", None)
            os.environ.pop("DISCORD_OAUTH_CLIENT_SECRET", None)
        self.assertIs(info["email_verified"], False)
        self.assertEqual(info["avatar_url"], "")

    def test_reddit_sends_its_mandatory_user_agent_on_both_requests(self):
        # Reddit blocks the default requests User-Agent outright, and does it
        # identically on the token exchange and the userinfo call — a header
        # set on only one would fail silently on the other.
        import apps.accounts.oauth as oauth_mod

        seen_headers = []

        class FakeResp:
            status_code = 200
            def json(self):
                return {"access_token": "t"}

        def fake_post(url, data=None, headers=None, auth=None, timeout=None):
            seen_headers.append(("post", headers, auth))
            return FakeResp()

        def fake_get(url, headers=None, timeout=None):
            seen_headers.append(("get", headers, None))
            return type("R", (), {"json": lambda self: {"id": "t2_abc", "name": "u"}})()

        orig_post, orig_get = oauth_mod.requests.post, oauth_mod.requests.get
        oauth_mod.requests.post, oauth_mod.requests.get = fake_post, fake_get
        try:
            import os
            os.environ["REDDIT_OAUTH_CLIENT_ID"] = "id"
            os.environ["REDDIT_OAUTH_CLIENT_SECRET"] = "secret"
            info = oauth_mod.exchange_oauth2("reddit", "code", "https://x/cb")
        finally:
            oauth_mod.requests.post, oauth_mod.requests.get = orig_post, orig_get
            os.environ.pop("REDDIT_OAUTH_CLIENT_ID", None)
            os.environ.pop("REDDIT_OAUTH_CLIENT_SECRET", None)
        self.assertEqual(info["uid"], "t2_abc")
        self.assertEqual(info["email"], "")
        for method, headers, auth in seen_headers:
            self.assertIn("User-Agent", headers, method)
            self.assertEqual(headers["User-Agent"], "web:musicconnectz:v1.0 (by /u/musicconnectz)")
        # Reddit requires Basic auth for the client credentials, not a body field.
        post_auth = seen_headers[0][2]
        self.assertEqual(post_auth, ("id", "secret"))
