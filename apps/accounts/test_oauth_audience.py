"""Providers mint a different audience per platform.

Google issues a separate OAuth client ID for web, Android and iOS, and the
`aud` claim carries whichever one signed the user in. Accepting only the web ID
locks every native client out — the same failure Apple had, where only the
Services ID was accepted and native iOS could never sign in.
"""
from unittest import mock

from django.test import SimpleTestCase

from .oauth import OAuthError, _audiences, verify_google

WEB = "111-web.apps.googleusercontent.com"
IOS = "222-ios.apps.googleusercontent.com"
ANDROID = "333-android.apps.googleusercontent.com"


def _tokeninfo(aud):
    resp = mock.Mock(status_code=200)
    resp.json.return_value = {
        "aud": aud, "iss": "https://accounts.google.com", "sub": "google-uid-1",
        "email": "member@example.com", "email_verified": "true", "name": "A Member",
    }
    return resp


def _verify(aud, **env):
    with mock.patch("apps.accounts.oauth.requests.get", return_value=_tokeninfo(aud)), \
            mock.patch.dict("os.environ", env, clear=False):
        return verify_google("token")


class AudienceHelperTests(SimpleTestCase):
    def test_it_collects_across_vars_and_commas(self):
        with mock.patch.dict("os.environ", {"A": "one, two", "B": "three"}):
            self.assertEqual(_audiences("A", "B"), ["one", "two", "three"])

    def test_it_drops_blanks_and_duplicates(self):
        with mock.patch.dict("os.environ", {"A": "one,,one", "B": "  "}):
            self.assertEqual(_audiences("A", "B"), ["one"])

    def test_an_empty_result_is_empty_not_a_wildcard(self):
        with mock.patch.dict("os.environ", {"A": "", "B": ""}):
            self.assertEqual(_audiences("A", "B"), [])


class GoogleAudienceTests(SimpleTestCase):
    def test_the_web_client_id_is_accepted(self):
        info = _verify(WEB, GOOGLE_OAUTH_CLIENT_ID=WEB)
        self.assertEqual(info["uid"], "google-uid-1")

    def test_a_native_ios_client_id_is_accepted_when_configured(self):
        info = _verify(IOS, GOOGLE_OAUTH_CLIENT_ID=WEB, GOOGLE_OAUTH_IOS_CLIENT_ID=IOS)
        self.assertEqual(info["uid"], "google-uid-1")

    def test_a_native_android_client_id_is_accepted_when_configured(self):
        info = _verify(ANDROID, GOOGLE_OAUTH_CLIENT_ID=WEB,
                       GOOGLE_OAUTH_ANDROID_CLIENT_ID=ANDROID)
        self.assertEqual(info["uid"], "google-uid-1")

    def test_someone_elses_client_id_is_still_rejected(self):
        """Accepting several audiences must not mean accepting any audience."""
        with self.assertRaises(OAuthError):
            _verify("999-somebody-else.apps.googleusercontent.com",
                    GOOGLE_OAUTH_CLIENT_ID=WEB, GOOGLE_OAUTH_IOS_CLIENT_ID=IOS)

    def test_an_unconfigured_server_fails_closed(self):
        with self.assertRaises(OAuthError):
            _verify(WEB, GOOGLE_OAUTH_CLIENT_ID="", GOOGLE_OAUTH_ANDROID_CLIENT_ID="",
                    GOOGLE_OAUTH_IOS_CLIENT_ID="")

    def test_an_unverified_google_email_is_refused(self):
        resp = _tokeninfo(WEB)
        resp.json.return_value["email_verified"] = "false"
        with mock.patch("apps.accounts.oauth.requests.get", return_value=resp), \
                mock.patch.dict("os.environ", {"GOOGLE_OAUTH_CLIENT_ID": WEB}):
            with self.assertRaises(OAuthError):
                verify_google("token")

    def test_a_forged_issuer_is_refused(self):
        resp = _tokeninfo(WEB)
        resp.json.return_value["iss"] = "https://evil.example.com"
        with mock.patch("apps.accounts.oauth.requests.get", return_value=resp), \
                mock.patch.dict("os.environ", {"GOOGLE_OAUTH_CLIENT_ID": WEB}):
            with self.assertRaises(OAuthError):
                verify_google("token")
