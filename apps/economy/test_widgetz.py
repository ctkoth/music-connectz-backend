"""WidgetZ — three ways a link opens, and who decides which.

The split under test is the one the module exists to hold: a PLAYER frames a
URL this codebase built out of an id, so it is safe at every tier; a PAGE
frames whatever the member pasted, so it is StatZ AND scan-cleared; and a link
that gets neither still opens, in a tab, exactly as it does today. The tier
buys where a link opens, never whether — a test that let `outside` become a
refusal would be letting the ladder rule quietly break.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.economy.models import (
    TIER_FREE,
    TIER_PREMIUM,
    TIER_STATZ,
    LinkCounter,
    membership_for,
)
from apps.economy import widgetz

User = get_user_model()
PW = "hunter2hunter2"
KEYED = dict(SAFE_BROWSING_API_KEY="test-key")


def as_tier(user, tier):
    m = membership_for(user)
    m.tier = tier
    m.save(update_fields=["tier", "updated_at"])
    return user


class PlayerTests(TestCase):
    """A player is built from an id we read, not from the link we were handed."""

    def test_youtube_shapes_all_reach_the_same_embed(self):
        for url in (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=42",
        ):
            w = widgetz.widget_for(url, TIER_FREE)
            self.assertEqual(w["mode"], "player", url)
            self.assertEqual(w["src"], "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ", url)

    def test_a_shorts_link_is_a_tall_frame(self):
        w = widgetz.widget_for("https://www.youtube.com/shorts/dQw4w9WgXcQ", TIER_FREE)
        self.assertEqual(w["aspect"], "9/16")

    def test_the_framed_url_never_carries_what_the_member_typed(self):
        # The whole reason players need no tier gate: an id is extracted and a
        # URL is built. Anything smuggled into the link is dropped, not framed.
        w = widgetz.widget_for(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&onload=alert(1)#x", TIER_FREE)
        self.assertEqual(w["src"], "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ")

    def test_a_youtube_channel_is_not_a_player(self):
        # No video id, so nothing to play. It opens outside rather than
        # framing an empty box.
        w = widgetz.widget_for("https://www.youtube.com/@someartist", TIER_FREE)
        self.assertEqual(w["mode"], "outside")

    def test_spotify_track_album_and_localised_links(self):
        t = widgetz.widget_for("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT", TIER_FREE)
        self.assertEqual(t["mode"], "player")
        self.assertTrue(t["src"].endswith("/embed/track/4cOdK2wGLETKBW3PvgPWqT"))
        self.assertEqual(t["height"], 152)
        a = widgetz.widget_for("https://open.spotify.com/intl-de/album/4cOdK2wGLETKBW3PvgPWqT", TIER_FREE)
        self.assertTrue(a["src"].endswith("/embed/album/4cOdK2wGLETKBW3PvgPWqT"))
        self.assertEqual(a["height"], 380)

    def test_soundcloud_player_origin_is_ours_and_the_link_is_a_parameter(self):
        w = widgetz.widget_for("https://soundcloud.com/artist/track-name", TIER_FREE)
        self.assertEqual(w["mode"], "player")
        self.assertTrue(w["src"].startswith("https://w.soundcloud.com/player/?url="))

    def test_the_other_players_resolve(self):
        for url, provider in (
            ("https://music.apple.com/us/album/thriller/1234", "apple"),
            ("https://www.deezer.com/en/track/3135556", "deezer"),
            ("https://vimeo.com/123456789", "vimeo"),
            ("https://www.mixcloud.com/someone/a-set/", "mixcloud"),
            ("https://www.tiktok.com/@someone/video/7000000000000000000", "tiktok"),
            ("https://www.instagram.com/reel/CabcdEF1234/", "instagram"),
        ):
            w = widgetz.widget_for(url, TIER_FREE)
            self.assertEqual(w["mode"], "player", url)
            self.assertEqual(w["provider"], provider, url)

    def test_a_player_never_gets_the_sandbox_escape_pair(self):
        # allow-scripts + allow-same-origin together lets a frame lift its own
        # sandbox. Neither mode may carry both.
        self.assertNotIn("allow-same-origin", widgetz.SANDBOX)


class OurOwnLinksTests(TestCase):
    def test_our_permalinks_open_as_the_real_screen(self):
        for path, kind, key in (("/p/abc", "post", "abc"),
                                ("/u/someone", "member", "someone"),
                                ("/pl/12", "playlist", "12")):
            w = widgetz.widget_for("https://musicconnectz.net" + path, TIER_FREE)
            self.assertEqual(w["mode"], "internal", path)
            self.assertEqual(w["target"], {"kind": kind, "key": key}, path)

    def test_our_own_link_is_never_a_page_widget_even_for_statz(self):
        # Framing ourselves inside ourselves is strictly worse than opening the
        # screen we already have, so the tier does not change this answer.
        w = widgetz.widget_for("https://musicconnectz.net/u/someone", TIER_STATZ)
        self.assertEqual(w["mode"], "internal")


@override_settings(**KEYED)
class PageGateTests(TestCase):
    """An arbitrary page is StatZ, and only once the scan has cleared it."""

    def setUp(self):
        self.free = User.objects.create_user("freebie", password=PW)
        self.statz = as_tier(User.objects.create_user("statty", password=PW), TIER_STATZ)

    def _clean(self):
        return patch("apps.economy.widgetz.safe_browsing_check", return_value=(True, ""))

    def test_free_and_premium_get_the_link_in_a_tab_not_a_refusal(self):
        for tier in (TIER_FREE, TIER_PREMIUM):
            w = widgetz.widget_for("https://example.com/press", tier)
            self.assertEqual(w["mode"], "outside", tier)
            self.assertEqual(w["gate"], "tier", tier)
            # The link itself survives — the tier decided WHERE it opens.
            self.assertEqual(w["url"], "https://example.com/press", tier)

    def test_statz_frames_a_scanned_clean_page(self):
        with self._clean():
            w = widgetz.widget_for("https://example.com/press", TIER_STATZ)
        self.assertEqual(w["mode"], "page")
        self.assertEqual(w["src"], "https://example.com/press")
        # A site can still refuse to be framed and we cannot know in advance,
        # so the client is told to keep the way out on screen.
        self.assertTrue(w["may_refuse"])

    def test_a_flagged_page_is_refused_at_every_tier(self):
        with patch("apps.economy.widgetz.safe_browsing_check", return_value=(False, "MALWARE")):
            w = widgetz.widget_for("https://bad.example/x", TIER_STATZ)
        self.assertEqual(w["mode"], "outside")
        self.assertEqual(w["gate"], "unsafe")
        self.assertIn("MALWARE", w["reason"])

    def test_the_verdict_is_scanned_once_and_remembered(self):
        with self._clean() as scan:
            widgetz.widget_for("https://example.com/press", TIER_STATZ)
            widgetz.widget_for("https://example.com/press", TIER_STATZ)
        self.assertEqual(scan.call_count, 1)
        self.assertTrue(LinkCounter.objects.get(url="https://example.com/press").scanned)

    def test_a_bare_host_is_completed_before_anything_else_looks_at_it(self):
        with self._clean():
            w = widgetz.widget_for("example.com/press", TIER_STATZ)
        self.assertEqual(w["url"], "https://example.com/press")

    def test_a_javascript_url_is_refused_outright(self):
        w = widgetz.widget_for("javascript:alert(1)", TIER_STATZ)
        self.assertEqual(w["mode"], "refused")


class UnscannedTests(TestCase):
    """No key, no verdict, no frame — including for StatZ."""

    @override_settings(SAFE_BROWSING_API_KEY="")
    def test_without_a_scanner_a_page_widget_is_refused_and_says_so(self):
        w = widgetz.widget_for("https://example.com/press", TIER_STATZ)
        self.assertEqual(w["mode"], "outside")
        self.assertEqual(w["gate"], "unscanned")

    @override_settings(SAFE_BROWSING_API_KEY="")
    def test_a_player_still_works_with_no_scanner(self):
        # Players do not depend on the scan: the URL is one this file wrote.
        w = widgetz.widget_for("https://youtu.be/dQw4w9WgXcQ", TIER_FREE)
        self.assertEqual(w["mode"], "player")

    @override_settings(SAFE_BROWSING_API_KEY="")
    def test_an_unscannable_link_is_never_recorded_as_scanned(self):
        # The flag means "we looked". A deploy with no key used to set it
        # anyway, which turned "never checked" into "checked and clean" for
        # every link on the platform.
        widgetz.scan_verdict("https://example.com/press")
        self.assertFalse(LinkCounter.objects.get(url="https://example.com/press").scanned)


@override_settings(**KEYED)
class EndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("opener", password=PW)
        self.c = APIClient()
        self.c.force_authenticate(self.user)

    def test_get_publishes_the_ladder_and_the_gain_before_anything_opens(self):
        r = self.c.get("/api/economy/widgetz/")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["page_widgets"]["allowed"])
        self.assertEqual(r.data["page_widgets"]["needs_tier"], TIER_STATZ)
        self.assertTrue(r.data["page_widgets"]["scan_available"])
        # The gain a genuine visit pays, stated up front rather than discovered.
        self.assertEqual(r.data["reward"]["energy"], 5)
        self.assertEqual(r.data["reward"]["after_seconds"], 30)
        self.assertTrue(r.data["players"])

    def test_open_resolves_a_link(self):
        r = self.c.post("/api/economy/widgetz/open/",
                        {"url": "https://youtu.be/dQw4w9WgXcQ"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["mode"], "player")

    def test_open_needs_a_url(self):
        r = self.c.post("/api/economy/widgetz/open/", {}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_both_endpoints_need_a_login(self):
        anon = APIClient()
        self.assertIn(anon.get("/api/economy/widgetz/").status_code, (401, 403))
        self.assertIn(anon.post("/api/economy/widgetz/open/", {}, format="json").status_code, (401, 403))
