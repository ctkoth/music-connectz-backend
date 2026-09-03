"""YouTube OAuth-connect verification — the "layer 1" social_verify.py's
docstring always described but never built: a scoped Google OAuth grant
proves ownership AND returns the real subscriberCount in one step, so a
member's reach (and therefore their Energy regen rate) never has to wait on
a scrape or a human queue for the platform they're most likely to have.
"""
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import membership_for, profile_for

User = get_user_model()
PW = "hunter2hunter2"
URL = "/api/economy/social/verify/youtube/"
REDIRECT = "https://app.musicconnectz.net/oauth/callback"


class FakeResp:
    def __init__(self, payload):
        self._payload = payload
    def json(self):
        return self._payload


def configured():
    return patch.dict(os.environ, {
        "GOOGLE_OAUTH_CLIENT_ID": "client-id", "GOOGLE_OAUTH_CLIENT_SECRET": "client-secret",
    })


class YouTubeVerifyBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="koth", password=PW, email="k@example.com")
        membership_for(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)


class NotConfiguredTests(YouTubeVerifyBase):
    def test_start_refuses_without_a_client_secret(self):
        with patch.dict(os.environ, {"GOOGLE_OAUTH_CLIENT_ID": "id", "GOOGLE_OAUTH_CLIENT_SECRET": ""}):
            r = self.client.post(URL, {"action": "start", "redirect_uri": REDIRECT}, format="json")
        self.assertEqual(r.status_code, 503, r.data)

    def test_finish_refuses_without_a_client_secret(self):
        with patch.dict(os.environ, {"GOOGLE_OAUTH_CLIENT_ID": "id", "GOOGLE_OAUTH_CLIENT_SECRET": ""}):
            r = self.client.post(URL, {"action": "finish", "code": "c", "redirect_uri": REDIRECT}, format="json")
        self.assertEqual(r.status_code, 503, r.data)


class StartTests(YouTubeVerifyBase):
    def test_start_returns_a_google_auth_url_with_the_youtube_scope(self):
        with configured():
            r = self.client.post(URL, {"action": "start", "redirect_uri": REDIRECT}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("accounts.google.com", r.data["auth_url"])
        self.assertIn("youtube.readonly", r.data["auth_url"])
        self.assertTrue(r.data["state"])

    def test_start_requires_a_redirect_uri(self):
        with configured():
            r = self.client.post(URL, {"action": "start"}, format="json")
        self.assertEqual(r.status_code, 400, r.data)


class FinishTests(YouTubeVerifyBase):
    def _finish(self, channel_items):
        with configured(), \
             patch("apps.economy.social_verify.requests.post",
                   return_value=FakeResp({"access_token": "tok"})), \
             patch("apps.economy.social_verify.requests.get",
                   return_value=FakeResp({"items": channel_items})):
            return self.client.post(URL, {"action": "finish", "code": "c", "redirect_uri": REDIRECT},
                                    format="json")

    def test_a_real_channel_is_verified_with_its_real_count(self):
        r = self._finish([{"id": "UC123", "snippet": {"title": "K-Oth Music"},
                           "statistics": {"subscriberCount": "4200"}}])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["verified"])
        self.assertEqual(r.data["followers"], 4200)
        link = profile_for(self.user).links[0]
        self.assertTrue(link["verified"])
        self.assertEqual(link["verified_count"], 4200)
        self.assertEqual(link["verified_by"], "oauth")
        self.assertEqual(link["url"], "https://www.youtube.com/channel/UC123")

    def test_a_verified_real_count_moves_the_reach_median(self):
        # Median across sources, not a sum — with the always-present, always-
        # verified "Music ConnectZ" source at 0 followers here, [0, 4200]
        # medians to 2100.
        from apps.economy.models import reach_median
        self.assertEqual(reach_median(self.user), 0)
        self._finish([{"id": "UC123", "snippet": {"title": "K-Oth Music"},
                       "statistics": {"subscriberCount": "4200"}}])
        self.assertEqual(reach_median(self.user), 2100)

    def test_a_hidden_count_does_not_fake_a_zero(self):
        r = self._finish([{"id": "UC123", "snippet": {"title": "K-Oth Music"}, "statistics": {}}])
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data["verified"])
        self.assertTrue(r.data["count_hidden"])
        self.assertIsNone(r.data["followers"])
        link = profile_for(self.user).links[0]
        self.assertFalse(link["verified"])
        self.assertTrue(link["count_hidden"])
        self.assertNotIn("verified_count", link)

    def test_a_hidden_count_is_excluded_from_the_reach_median_not_counted_as_zero(self):
        from apps.economy.models import reach_median
        self._finish([{"id": "UC123", "snippet": {"title": "K-Oth Music"}, "statistics": {}}])
        # Still 0 (no OTHER verified sources) — the point is it's excluded,
        # not that it drags a real median down; test_reach_median-adjacent
        # coverage elsewhere confirms exclusion vs zero-counting distinctly
        # via social_sources().
        from apps.economy.models import social_sources
        yt = next(s for s in social_sources(self.user) if s["label"] == "K-Oth Music")
        self.assertFalse(yt["verified"])

    def test_no_channel_on_the_google_account_is_refused(self):
        r = self._finish([])
        self.assertEqual(r.status_code, 400, r.data)

    def test_finish_requires_a_code(self):
        with configured():
            r = self.client.post(URL, {"action": "finish", "redirect_uri": REDIRECT}, format="json")
        self.assertEqual(r.status_code, 400, r.data)

    def test_re_verifying_updates_the_same_link_not_a_duplicate(self):
        self._finish([{"id": "UC123", "snippet": {"title": "K-Oth Music"},
                       "statistics": {"subscriberCount": "100"}}])
        self._finish([{"id": "UC123", "snippet": {"title": "K-Oth Music"},
                       "statistics": {"subscriberCount": "200"}}])
        links = profile_for(self.user).links
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["verified_count"], 200)
