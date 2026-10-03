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
    def test_apple_team_id_instead_of_services_id_is_warned(self):
        d = self.client.get(URL).data
        self.assertEqual(d["apple"], "ABCDE12345")
        self.assertTrue(any("Services ID" in x for x in d["warnings"]), d["warnings"])

    @override_settings(APPLE_OAUTH_CLIENT_ID="")
    def test_unconfigured_apple_renders_no_button(self):
        self.assertEqual(self.client.get(URL).data["apple"], "")

    def test_every_provider_the_backend_can_complete_is_answered_for(self):
        # The button grid is built from this map. A provider missing from it
        # reads as "no client ID" on the client, which is indistinguishable
        # from unconfigured — so absence must not be how a provider drops out.
        from apps.accounts.oauth import OAUTH2_PROVIDERS

        r = self.client.get(URL)
        for name in ("google", "github", "apple", *OAUTH2_PROVIDERS):
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


class ProfileWithoutIdTests(TestCase):
    """A profile call that fails must never become a shared identity."""

    def test_missing_id_is_refused_not_none(self):
        from unittest import mock
        from apps.accounts import oauth

        tok = mock.Mock(status_code=200); tok.json.return_value = {"access_token": "t"}
        me = mock.Mock(status_code=403); me.json.return_value = {"error": {"status": 403, "message": "User not registered in the Developer Dashboard"}}
        with mock.patch.dict("os.environ", {"SPOTIFY_OAUTH_CLIENT_ID": "a", "SPOTIFY_OAUTH_CLIENT_SECRET": "b"}), \
             mock.patch.object(oauth.requests, "post", return_value=tok), \
             mock.patch.object(oauth.requests, "get", return_value=me):
            with self.assertRaises(oauth.OAuthError) as e:
                oauth.exchange_oauth2("spotify", "code")
        self.assertIn("Developer Dashboard", str(e.exception))

    def test_200_with_no_id_is_refused(self):
        from unittest import mock
        from apps.accounts import oauth

        tok = mock.Mock(status_code=200); tok.json.return_value = {"access_token": "t"}
        me = mock.Mock(status_code=200); me.json.return_value = {}
        with mock.patch.dict("os.environ", {"FACEBOOK_OAUTH_CLIENT_ID": "a", "FACEBOOK_OAUTH_CLIENT_SECRET": "b"}), \
             mock.patch.object(oauth.requests, "post", return_value=tok), \
             mock.patch.object(oauth.requests, "get", return_value=me):
            with self.assertRaises(oauth.OAuthError):
                oauth.exchange_oauth2("facebook", "code")
