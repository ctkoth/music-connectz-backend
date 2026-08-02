"""Throttling is disabled for the suite — so prove it here, with it switched on.

`settings.TESTING` blanks the throttle rates so hundreds of legitimate logins
across the suite don't throttle each other. That would leave the feature
completely untested, which is how a throttle quietly stops working. These tests
switch it back on and clear the cache around each one.

Note the rates are patched onto `SimpleRateThrottle.THROTTLE_RATES` rather than
through `override_settings`: DRF binds that dict to the class at import, so a
settings override alone changes nothing and the test would pass while measuring
nothing at all.
"""
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

RATES = {"auth-login": "3/min", "auth-oauth": "3/min",
         "auth-register": "3/min", "auth-password": "3/min"}


class AuthThrottleTests(TestCase):
    def setUp(self):
        cache.clear()          # a leftover count would make these lie
        self.client = APIClient()
        patcher = mock.patch.object(SimpleRateThrottle, "THROTTLE_RATES", RATES)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(cache.clear)

    def _hammer(self, url, body, times=6, method="post"):
        call = getattr(self.client, method)
        return [
            (call(url, body, format="json") if body is not None else call(url)).status_code
            for _ in range(times)
        ]

    def test_repeated_bad_logins_are_eventually_throttled(self):
        """Unlimited guesses against a password field is the whole problem."""
        codes = self._hammer(reverse("auth-login"),
                             {"identifier": "nobody", "password": "wrong"})
        self.assertIn(429, codes, f"never throttled: {codes}")

    def test_oauth_is_throttled_before_it_can_be_used_as_a_proxy(self):
        """Each call reaches out to a provider — uncapped, this server is a free
        amplifier for hammering Google or GitHub."""
        codes = self._hammer(reverse("auth-oauth", args=["google"]),
                             {"credential": "junk"})
        self.assertIn(429, codes, f"never throttled: {codes}")

    def test_password_reset_requests_are_throttled(self):
        codes = self._hammer(reverse("auth-password-forgot"),
                             {"identifier": "someone@example.com"})
        self.assertIn(429, codes, f"never throttled: {codes}")

    def test_registration_is_throttled(self):
        codes = self._hammer(reverse("auth-register"),
                             {"username": "x", "email": "x@example.com",
                              "password": "not-a-real-password-1"})
        self.assertIn(429, codes, f"never throttled: {codes}")

    def test_the_public_catalogs_are_not_throttled(self):
        """Only the unauthenticated doors are scoped. A tab list is not one."""
        codes = self._hammer(reverse("tabz"), None, times=10, method="get")
        self.assertNotIn(429, codes)

    def test_the_throttle_is_actually_wired_to_the_view(self):
        """Guards the test itself: if the scope were removed from the view, the
        checks above would still pass by never reaching a limit."""
        from .views import LoginView, OAuthLoginView, RegisterView

        self.assertEqual(LoginView.throttle_scope, "auth-login")
        self.assertEqual(OAuthLoginView.throttle_scope, "auth-oauth")
        self.assertEqual(RegisterView.throttle_scope, "auth-register")
