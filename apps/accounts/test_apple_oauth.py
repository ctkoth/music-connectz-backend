"""Apple identity tokens arrive with two different audiences.

Web sign-in (the Services ID) and native iOS Sign in with Apple (the Bundle ID)
mint tokens whose `aud` differs. The backend has to accept both or one platform
can't log in at all — but it must not accept just anything, which is the whole
point of checking the audience.
"""
from unittest import mock

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import SimpleTestCase

from .oauth import OAuthError, verify_apple

SERVICES_ID = "net.musicconnectz.web"
BUNDLE_ID = "net.musicconnectz.app"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _apple_token(aud, sub="001234.abcdef", email="member@privaterelay.appleid.com"):
    """Mint a token that looks like Apple's, signed with our throwaway key."""
    return jwt.encode(
        {"iss": "https://appleid.apple.com", "aud": aud, "sub": sub,
         "email": email, "email_verified": "true"},
        _KEY, algorithm="RS256",
    )


class _FakeJWKClient:
    """Stands in for Apple's key endpoint so tests never hit the network."""

    def __init__(self, *a, **kw):
        pass

    def get_signing_key_from_jwt(self, token):
        return mock.Mock(key=_KEY.public_key())


def _verify(token, **env):
    with mock.patch("jwt.PyJWKClient", _FakeJWKClient), \
            mock.patch.dict("os.environ", env, clear=False):
        return verify_apple(token)


class AppleAudienceTests(SimpleTestCase):
    def test_web_services_id_token_is_accepted(self):
        info = _verify(_apple_token(SERVICES_ID),
                       APPLE_OAUTH_CLIENT_ID=SERVICES_ID,
                       APPLE_OAUTH_BUNDLE_ID=BUNDLE_ID)
        self.assertEqual(info["provider"], "apple")
        self.assertEqual(info["uid"], "001234.abcdef")

    def test_native_ios_bundle_id_token_is_accepted(self):
        """The case that was broken: native Sign in with Apple was rejected."""
        info = _verify(_apple_token(BUNDLE_ID),
                       APPLE_OAUTH_CLIENT_ID=SERVICES_ID,
                       APPLE_OAUTH_BUNDLE_ID=BUNDLE_ID)
        self.assertEqual(info["uid"], "001234.abcdef")

    def test_bundle_id_alone_still_works_for_a_native_only_deploy(self):
        info = _verify(_apple_token(BUNDLE_ID),
                       APPLE_OAUTH_CLIENT_ID="", APPLE_OAUTH_BUNDLE_ID=BUNDLE_ID)
        self.assertEqual(info["uid"], "001234.abcdef")

    def test_a_token_for_somebody_elses_app_is_rejected(self):
        """Accepting two audiences must not mean accepting every audience."""
        with self.assertRaises(OAuthError):
            _verify(_apple_token("com.someone.else"),
                    APPLE_OAUTH_CLIENT_ID=SERVICES_ID,
                    APPLE_OAUTH_BUNDLE_ID=BUNDLE_ID)

    def test_unconfigured_server_fails_closed(self):
        with self.assertRaises(OAuthError):
            _verify(_apple_token(BUNDLE_ID),
                    APPLE_OAUTH_CLIENT_ID="", APPLE_OAUTH_BUNDLE_ID="")

    def test_email_verified_string_true_is_normalised_to_bool(self):
        info = _verify(_apple_token(BUNDLE_ID),
                       APPLE_OAUTH_CLIENT_ID="", APPLE_OAUTH_BUNDLE_ID=BUNDLE_ID)
        self.assertIs(info["email_verified"], True)
