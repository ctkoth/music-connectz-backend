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
