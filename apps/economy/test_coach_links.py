"""Coaches score reels and videos by link: a YouTube video or Short is watched at its
address; an Instagram, Facebook or TikTok link is told how to attach the reel instead,
before anything runs or is charged."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import matchref, vocalcoach
from apps.economy.models import TIER_STATZ, TakeScore, membership_for, wallet_for
from apps.economy.test_crosspost import fake_gemini

User = get_user_model()
SHORT = "https://www.youtube.com/shorts/dQw4w9WgXcQ?t=15"


class CoachLinkTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user(username="reeler", password="pw-Long-enough-1")
        m = membership_for(self.me); m.tier = TIER_STATZ; m.save()
        w = wallet_for(self.me); w.money_cents = 100000; w.energy = 1000; w.save()
        self.c = APIClient(); self.c.force_authenticate(self.me)

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.gemini.requests.post", return_value=fake_gemini())
    def test_a_youtube_short_is_watched_at_its_address_and_scored_as_my_take(self, rq, _k):
        r = self.c.post("/api/rapz/coach/", {"link": SHORT}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        part = rq.call_args.kwargs["json"]["contents"][0]["parts"][1]
        self.assertEqual(part["file_data"]["file_uri"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(part["video_metadata"]["start_offset"], "15s")
        self.assertEqual(r.data["source"], "link")
        row = TakeScore.objects.get(user=self.me)
        self.assertEqual((row.source, row.ref), ("link", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"))

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.gemini.requests.post", return_value=fake_gemini())
    def test_somebody_elses_video_by_link_is_a_reference_listen(self, _rq, _k):
        r = self.c.post("/api/singz/coach/", {"link": SHORT, "reference": "true"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["reference"])
        self.assertFalse(TakeScore.objects.filter(user=self.me).exists())

    @patch("apps.economy.gemini.requests.post")
    def test_reel_apps_say_how_to_attach_the_reel_and_nothing_runs(self, rq):
        before = wallet_for(self.me).prompts_used_today or 0
        for url, label in (("https://www.instagram.com/reel/Cabc123/", "Instagram"),
                           ("https://fb.watch/xyz/", "Facebook"),
                           ("https://www.tiktok.com/@a/video/1", "TikTok")):
            r = self.c.post("/api/singz/coach/", {"link": url}, format="json")
            self.assertEqual(r.status_code, 400, url)
            self.assertIn(label, r.data["detail"])
            self.assertIn("attach the file", r.data["detail"])
        rq.assert_not_called()
        self.assertEqual(wallet_for(self.me).prompts_used_today or 0, before)

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.gemini.requests.post", return_value=fake_gemini(status_code=403))
    def test_a_private_video_says_it_must_be_public_and_is_not_charged(self, _rq, _k):
        before = wallet_for(self.me).prompts_used_today or 0
        r = self.c.post("/api/singz/coach/", {"link": SHORT}, format="json")
        self.assertEqual(r.status_code, 502)
        self.assertIn("public", r.data["detail"])
        self.assertEqual(wallet_for(self.me).prompts_used_today or 0, before)

    def test_the_links_are_said_before_one_is_pasted_and_the_window_matches(self):
        d = self.c.get("/api/singz/coach/").json()["links"]
        ok = [a["label"] for a in d["apps"] if a["ok"]]
        self.assertEqual(ok, ["YouTube"])
        self.assertIn("Instagram", [a["label"] for a in d["apps"] if not a["ok"]])
        self.assertIn(f"first {matchref.LINK_WINDOW_SECONDS // 60} minutes", vocalcoach.LINK_TAKE_NOTE)
