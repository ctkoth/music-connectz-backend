"""A take from a link: YouTube travels as its URL, a direct file is fetched
safely, and streaming services are refused with a sentence, never charged."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import medialink
from apps.economy.vocalcoach import _media_part

User = get_user_model()


class ClassifyTests(TestCase):
    def test_each_kind_of_link(self):
        self.assertEqual(medialink.classify("https://youtu.be/abc")[0], "youtube")
        self.assertEqual(medialink.classify("https://www.youtube.com/watch?v=abc")[0], "youtube")
        self.assertEqual(medialink.classify("https://example.com/take.mp3")[0], "file")
        for url in ("https://open.spotify.com/track/x", "https://soundcloud.com/a/b",
                    "https://music.apple.com/us/album/x", "https://listen.tidal.com/track/1"):
            kind, why = medialink.classify(url)
            self.assertEqual(kind, "refused", url)
            self.assertIn("Nothing was charged", why)
        self.assertEqual(medialink.classify("ftp://x/y")[0], "bad")
        self.assertEqual(medialink.classify("not a link")[0], "bad")

    def test_youtube_goes_to_the_model_as_its_url(self):
        part, cleanup, why = _media_part(medialink.YouTubeTake("https://youtu.be/abc"), "video/mp4", 0)
        self.assertEqual(part, {"file_data": {"file_uri": "https://youtu.be/abc"}})
        self.assertIsNone(cleanup)
        self.assertIsNone(why)


class _Resp:
    def __init__(self, status=200, ctype="audio/mpeg", body=b"ID3data", length=None, location=None):
        self.status_code = status
        self.headers = {"Content-Type": ctype}
        if length is not None:
            self.headers["Content-Length"] = str(length)
        if location:
            self.headers["Location"] = location
        self.is_redirect = status in (301, 302, 303, 307, 308)
        self._body = body

    def iter_content(self, n):
        yield self._body

    def close(self):
        pass


class FetchTests(TestCase):
    def test_private_addresses_are_never_fetched(self):
        with mock.patch("apps.economy.medialink.requests.get") as get:
            f, _c, why = medialink.fetch_file("http://127.0.0.1/admin.mp3", 10_000)
        self.assertIsNone(f)
        self.assertIn("won't fetch", why)
        get.assert_not_called()

    def test_a_redirect_into_a_private_address_is_refused(self):
        hops = iter([_Resp(302, location="http://10.0.0.5/x.mp3")])
        with mock.patch("apps.economy.medialink._public", side_effect=[True, False]), \
             mock.patch("apps.economy.medialink.requests.get", side_effect=lambda *a, **k: next(hops)):
            f, _c, why = medialink.fetch_file("https://cdn.example.com/x.mp3", 10_000)
        self.assertIsNone(f)
        self.assertIn("won't fetch", why)

    def test_a_good_file_comes_back_sized_and_typed(self):
        with mock.patch("apps.economy.medialink._public", return_value=True), \
             mock.patch("apps.economy.medialink.requests.get", return_value=_Resp(body=b"x" * 500)):
            f, ctype, why = medialink.fetch_file("https://cdn.example.com/take.mp3", 10_000)
        self.assertIsNone(why)
        self.assertEqual(ctype, "audio/mpeg")
        self.assertEqual(f.size, 500)

    def test_a_web_page_and_an_oversized_file_are_refused(self):
        with mock.patch("apps.economy.medialink._public", return_value=True):
            with mock.patch("apps.economy.medialink.requests.get", return_value=_Resp(ctype="text/html")):
                self.assertIn("web page", medialink.fetch_file("https://e.com/p", 10_000)[2])
            with mock.patch("apps.economy.medialink.requests.get", return_value=_Resp(length=50_000)):
                self.assertIn("over your coach limit", medialink.fetch_file("https://e.com/a.mp3", 10_000)[2])
            with mock.patch("apps.economy.medialink.requests.get", return_value=_Resp(body=b"x" * 20_000)):
                self.assertIn("over your coach limit", medialink.fetch_file("https://e.com/a.mp3", 10_000)[2])


class CoachDoorTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("linker", "l@e.com", "pw-Long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def test_a_spotify_link_is_refused_and_says_why(self):
        r = self.c.post("/api/singz/coach/", {"media_url": "https://open.spotify.com/track/x"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.json()["link_refused"])
        self.assertIn("Spotify", r.json()["detail"])

    def test_a_youtube_link_reaches_the_coach_as_a_url(self):
        seen = {}

        def fake(app_key, f, content_type, **kw):
            seen["uri"] = getattr(f, "youtube_uri", None)
            return None, ({"detail": "stub"}, 502)

        with mock.patch("apps.economy.vocalcoach._key", return_value="k"), \
             mock.patch("apps.economy.vocalcoach.score_take", side_effect=fake):
            r = self.c.post("/api/singz/coach/", {"media_url": "https://youtu.be/abc"}, format="json")
        self.assertEqual(seen.get("uri"), "https://youtu.be/abc")
        self.assertEqual(r.status_code, 502)   # a failed run, and nothing billed
