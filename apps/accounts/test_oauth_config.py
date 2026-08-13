"""The OAuth config the login buttons read.

Google's sign-in button does not error on a bad client ID — it just never
renders, and every screen stays silent about why. So the two things that make
that happen are tested here: whitespace, and a key that isn't a client ID.
"""
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

URL = "/api/auth/oauth-config/"
GOOD = "1234567890-abcdefg.apps.googleusercontent.com"


class OAuthConfigTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @override_settings(GOOGLE_OAUTH_CLIENT_ID=GOOD)
    def test_a_good_key_is_served_with_no_warnings(self):
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["google"], GOOD)
        self.assertEqual(r.data["warnings"], [])

    @override_settings(GOOGLE_OAUTH_CLIENT_ID=f"  {GOOD}\n")
    def test_whitespace_is_stripped_before_it_reaches_the_button(self):
        # This is the failure it was written for: a key copied out of the
        # Google console on a phone arrives with a trailing newline. The
        # verifier stripped it and would have accepted the token; the button
        # got the untrimmed string and Google silently refused to render.
        self.assertEqual(self.client.get(URL).data["google"], GOOD)

    @override_settings(GOOGLE_OAUTH_CLIENT_ID="GOCSPX-thisIsASecretNotAnId")
    def test_a_secret_pasted_into_the_id_field_is_called_out(self):
        w = self.client.get(URL).data["warnings"]
        self.assertTrue(any("apps.googleusercontent.com" in x for x in w), w)
        self.assertTrue(any("client secret" in x for x in w), w)

    @override_settings(GOOGLE_OAUTH_CLIENT_ID="")
    def test_an_unconfigured_provider_is_not_a_warning(self):
        # Not having Google set up is a choice, not a mistake.
        r = self.client.get(URL)
        self.assertEqual(r.data["google"], "")
        self.assertEqual(r.data["warnings"], [])

    @override_settings(APPLE_OAUTH_CLIENT_ID="ABCDE12345")
    def test_an_apple_team_id_in_the_services_id_field_is_called_out(self):
        w = self.client.get(URL).data["warnings"]
        self.assertTrue(any("Services ID" in x for x in w), w)

    @override_settings(GOOGLE_OAUTH_CLIENT_ID=GOOD)
    def test_it_needs_no_login(self):
        # The buttons are on the signed-out screen, so this cannot require auth.
        self.assertEqual(APIClient().get(URL).status_code, 200)


class HalfConfiguredTests(TestCase):
    """A client ID without its secret.

    This is the state that produced "all of them say they are unavailable":
    the screen enabled a button on the ID alone, and the exchange refused
    without the secret. The refusal landed AFTER the member had been sent to
    the provider and consented — the worst possible moment to learn a thing
    isn't set up. The config endpoint now reports what a sign-in needs to
    finish, not what it needs to start.
    """

    def setUp(self):
        self.client = APIClient()

    @override_settings(GITHUB_OAUTH_CLIENT_ID="Iv1.abc123", GITHUB_OAUTH_CLIENT_SECRET="")
    def test_a_client_id_with_no_secret_is_not_advertised(self):
        r = self.client.get(URL)
        self.assertEqual(r.data["github"], "")
        self.assertEqual(r.data["needs"]["github"], ["GITHUB_OAUTH_CLIENT_SECRET"])

    @override_settings(GITHUB_OAUTH_CLIENT_ID="Iv1.abc123", GITHUB_OAUTH_CLIENT_SECRET="")
    def test_half_configured_says_which_var_is_missing(self):
        # Naming the env var is the whole value: without it the only way to
        # learn what's missing is to read the source.
        w = self.client.get(URL).data["warnings"]
        self.assertTrue(any("GITHUB_OAUTH_CLIENT_SECRET" in x for x in w), w)

    @override_settings(GITHUB_OAUTH_CLIENT_ID="Iv1.abc123", GITHUB_OAUTH_CLIENT_SECRET="s3cret")
    def test_both_halves_present_serves_the_id_with_no_complaint(self):
        r = self.client.get(URL)
        self.assertEqual(r.data["github"], "Iv1.abc123")
        self.assertEqual(r.data["warnings"], [])
        self.assertNotIn("github", r.data["needs"])

    @override_settings(GITHUB_OAUTH_CLIENT_ID="", GITHUB_OAUTH_CLIENT_SECRET="")
    def test_nothing_set_is_listed_under_needs_but_is_not_a_warning(self):
        r = self.client.get(URL)
        self.assertEqual(r.data["warnings"], [])
        self.assertEqual(
            r.data["needs"]["github"],
            ["GITHUB_OAUTH_CLIENT_ID", "GITHUB_OAUTH_CLIENT_SECRET"],
        )

    def test_every_provider_the_backend_can_complete_is_answered_for(self):
        # The button grid is built from this map. A provider missing from it
        # reads as "no client ID" on the client, which is indistinguishable
        # from unconfigured — so absence must not be how a provider drops out.
        from apps.accounts.oauth import OAUTH2_PROVIDERS

        r = self.client.get(URL)
        for name in ("google", "apple", "github", *OAUTH2_PROVIDERS):
            self.assertIn(name, r.data, name)

    def test_a_code_flow_provider_configured_only_in_env_is_served(self):
        # spotify/microsoft/facebook/soundcloud/twitter have no settings entry
        # — they are read straight off the environment, same as the exchange
        # reads them.
        import os
        from unittest import mock

        env = {"SPOTIFY_OAUTH_CLIENT_ID": " spot-id ",
               "SPOTIFY_OAUTH_CLIENT_SECRET": "spot-secret"}
        with mock.patch.dict(os.environ, env):
            r = self.client.get(URL)
        self.assertEqual(r.data["spotify"], "spot-id")
        self.assertNotIn("spotify", r.data["needs"])


class SettingsStripTests(TestCase):
    def test_settings_strips_what_render_hands_it(self):
        # Both paths have to agree. oauth.py has always stripped; settings did
        # not, and the mismatch was invisible from either side.
        import importlib
        import os

        os.environ["GOOGLE_OAUTH_CLIENT_ID"] = f" {GOOD} "
        try:
            from music_connectz import settings as s
            importlib.reload(s)
            self.assertEqual(s.GOOGLE_OAUTH_CLIENT_ID, GOOD)
        finally:
            os.environ.pop("GOOGLE_OAUTH_CLIENT_ID", None)
            importlib.reload(s)
