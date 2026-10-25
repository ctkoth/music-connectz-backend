from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .streamlink import classify, describe

U = get_user_model()


class StreamLinkTests(TestCase):
    def test_exact_hosts_only(self):
        self.assertEqual(classify("https://open.spotify.com/track/1")[0], "spotify")
        self.assertEqual(classify("https://soundcloud.com/a/b")[0], "soundcloud")
        for bad in ("http://open.spotify.com/t", "https://open.spotify.com.evil.com/t",
                    "https://evil.com/?u=open.spotify.com", "https://u:p@soundcloud.com/a",
                    "https://soundcloud.com:8080/a", "javascript:alert(1)", ""):
            self.assertEqual(classify(bad), (None, None), bad)

    def test_apple_title_from_slug_no_network(self):
        with patch("apps.economy.streamlink.requests.get") as g:
            d = describe("https://music.apple.com/us/album/my-first-song/123")
        g.assert_not_called()
        self.assertEqual(d["title"], "My First Song")
        self.assertIn("can't hear", d["audio_note"])

    def test_oembed_failure_still_answers(self):
        import requests
        with patch("apps.economy.streamlink.requests.get", side_effect=requests.ConnectionError):
            d = describe("https://open.spotify.com/track/1")
        self.assertEqual(d["title"], "")
        self.assertEqual(d["service"], "spotify")

    def test_view_requires_auth_and_refuses_other_hosts(self):
        c = APIClient()
        self.assertEqual(c.get("/api/economy/streamlink/?url=x").status_code, 401)
        c.force_authenticate(U.objects.create_user("s", password="pw"))
        self.assertEqual(c.get("/api/economy/streamlink/?url=https://evil.com").status_code, 400)
