"""Inspiration at the free door: spends the free take, takes a file + a file/YouTube link,
saves nothing, issues no claim token, and fails without charging the visitor's take."""
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import models as m
from apps.economy.test_matchref import REPLY, f
from apps.economy.test_vocalcoach import fake_gemini

URL = "/api/rapz/trial/inspiration/"
VID = "dQw4w9WgXcQ"


class TrialInspirationTests(TestCase):
    def setUp(self):
        self.c = APIClient()
        p = patch("apps.economy.trial.TRIAL_PER_BROWSER", 1)
        p.start()
        self.addCleanup(p.stop)

    def post(self, data, anon="anon-1", reply=REPLY, status=200):
        resp = fake_gemini(reply)
        resp.status_code = status
        data = {**data, "anon_id": anon}
        with patch("apps.economy.trial_inspiration._key", return_value="k"), \
             patch("apps.economy.trial._key", return_value="k"), \
             patch("apps.economy.matchref._key", return_value="k"), \
             patch("apps.economy.vocalcoach._key", return_value="k"), \
             patch("apps.economy.gemini.requests.post", return_value=resp) as call:
            r = self.c.post(URL, data, format="multipart")
        self.call = call
        return r

    def test_file_against_file_is_rated_and_spends_the_free_take(self):
        r = self.post({"take": f("t.wav"), "reference": f("r.wav")})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["closeness"], 62)
        self.assertTrue(r.data["uses_free_take"])
        self.assertTrue(r.data["trial"])
        self.assertFalse(r.data["saved"])
        self.assertNotIn("token", r.data)
        row = m.TrialTake.objects.get()
        self.assertTrue(row.scored)
        self.assertEqual(row.anon_id, "anon-1")
        self.assertTrue(row.result["inspiration"])
        # The same browser has nothing left: a scored take now is refused.
        again = self.post({"take": f("t2.wav"), "reference": f("r2.wav")})
        self.assertEqual(again.status_code, 429)
        self.assertEqual(m.TrialTake.objects.count(), 1)

    def test_a_youtube_reference_is_read_by_the_coach(self):
        r = self.post({"take": f("t.wav"), "reference_url": f"https://youtu.be/{VID}"})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["sources"]["reference"]["kind"], "link")

    def test_spotify_reference_is_refused_with_the_reason_and_uses_nothing(self):
        r = self.post({"take": f("t.wav"), "reference_url": "https://open.spotify.com/track/abc"})
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.data["link_unsupported"])
        self.assertEqual(m.TrialTake.objects.count(), 0)

    def test_take_must_be_a_file_and_reference_is_required(self):
        self.assertEqual(self.post({"reference": f("r.wav")}).status_code, 400)
        self.assertEqual(self.post({"take": f("t.wav")}).status_code, 400)
        # A link on the take side is never read: that would be scoring someone else's video.
        r = self.post({"reference": f("r.wav"), "take_url": f"https://youtu.be/{VID}"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(m.TrialTake.objects.count(), 0)

    def test_member_doors_are_ignored(self):
        r = self.post({"take": f("t.wav"), "reference_post_id": "1"})
        self.assertEqual(r.status_code, 400)

    def test_non_media_is_refused(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        junk = SimpleUploadedFile("x.txt", b"hello", content_type="text/plain")
        r = self.post({"take": junk, "reference": f("r.wav")})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(m.TrialTake.objects.count(), 0)

    def test_a_failed_comparison_spends_nothing(self):
        r = self.post({"take": f("t.wav"), "reference": f("r.wav")}, status=500)
        self.assertGreaterEqual(r.status_code, 400)
        self.assertEqual(m.TrialTake.objects.count(), 0)
        ok = self.post({"take": f("t.wav"), "reference": f("r.wav")})
        self.assertEqual(ok.status_code, 201)

    def test_unscorable_is_logged_but_keeps_the_visitors_take(self):
        r = self.post({"take": f("t.wav"), "reference": f("r.wav")},
                      reply={"unscorable": "Silence."})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["unscorable"], "Silence.")
        row = m.TrialTake.objects.get()
        self.assertFalse(row.scored)
        ok = self.post({"take": f("t.wav"), "reference": f("r.wav")})
        self.assertEqual(ok.status_code, 201)

    def test_get_publishes_the_offer_before_the_press(self):
        with patch("apps.economy.trial._key", return_value="k"), \
             patch("apps.economy.trial_inspiration._key", return_value="k"):
            r = self.c.get("/api/rapz/trial/", {"anon_id": "anon-1"})
        ins = r.data["inspiration"]
        self.assertTrue(ins["offered"])
        self.assertTrue(ins["uses_free_take"])
        self.assertIn("free take", ins["note"])
        self.assertEqual(ins["reference_sources"], ["file", "link"])
        self.assertFalse(any(s["ok"] for s in ins["link_sources"] if s["provider"] == "spotify"))

    def test_scored_trial_still_refuses_reference_listening(self):
        r = self.c.post("/api/rapz/trial/", {"reference": "true", "take": f("t.wav")}, format="multipart")
        self.assertEqual(r.status_code, 403)
