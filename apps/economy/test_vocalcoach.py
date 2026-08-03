import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (TIER_FREE, TIER_PREMIUM, TIER_STATZ,
                                 membership_for, wallet_for)

User = get_user_model()
URL = "/api/singz/coach/"

GOOD = {"score": 7, "scores": {"pitch": 8, "tone": 7, "breath": 5, "range": 6, "agility": 7},
        "verdict": "A solid builder take that runs out of air in the last phrase.",
        "strengths": ["The first eight bars sit dead centre of pitch."],
        "fixes": ["You're breathing at the bar line — take it a beat earlier."],
        "next_drill": "Sustained 4-count exhale on an ee vowel."}


def fake_gemini(payload=GOOD, status_code=200):
    class R:
        status_code = 200
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}
    R.status_code = status_code
    return R()


def take(name="take.webm", ct="audio/webm", size=1000):
    return SimpleUploadedFile(name, b"0" * size, content_type=ct)


class SingZCoachTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.client.force_authenticate(self.user)
        m = membership_for(self.user); m.tier = TIER_STATZ; m.save()
        w = wallet_for(self.user); w.money_cents = 100000; w.save()

    def _tier(self, t):
        m = membership_for(self.user); m.tier = t; m.save(update_fields=["tier", "updated_at"])

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_a_take_comes_back_scored_and_coached(self, _post, _k):
        resp = self.client.post(URL, {"take": take(), "genre": "R&B",
                                      "range": "tenor", "difficulty": "builder"}, format="multipart")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["score"], 7)
        self.assertEqual(resp.data["scores"]["breath"], 5)
        self.assertIn("runs out of air", resp.data["verdict"])
        self.assertTrue(resp.data["fixes"])
        self.assertTrue(resp.data["next_drill"])

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_the_genre_and_range_reach_the_model(self, post, _k):
        self.client.post(URL, {"take": take(), "genre": "Drill", "range": "alto",
                               "difficulty": "stageboss"}, format="multipart")
        sent = post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
        self.assertIn("Drill", sent)
        self.assertIn("alto", sent)
        self.assertIn("stageboss", sent)

    def test_free_and_premium_are_refused_per_the_blueprint_gate(self):
        for tier in (TIER_FREE, TIER_PREMIUM):
            with self.subTest(tier=tier):
                self._tier(tier)
                resp = self.client.post(URL, {"take": take()}, format="multipart")
                self.assertEqual(resp.status_code, 403)
                self.assertEqual(resp.data["required_tier"], TIER_STATZ)

    def test_a_missing_or_non_audio_take_is_refused(self):
        self.assertEqual(self.client.post(URL, {}, format="multipart").status_code, 400)
        resp = self.client.post(URL, {"take": take("cv.pdf", "application/pdf")}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("isn't audio", resp.data["detail"])

    def test_an_oversized_take_is_refused(self):
        big = SimpleUploadedFile("long.webm", b"0" * (26 * 1024 * 1024), content_type="audio/webm")
        self.assertEqual(self.client.post(URL, {"take": big}, format="multipart").status_code, 413)

    @patch("apps.economy.vocalcoach._key", return_value="")
    def test_unconfigured_key_503s_cleanly(self, _k):
        resp = self.client.post(URL, {"take": take()}, format="multipart")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("GEMINI_API_KEY", resp.data["detail"])

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini({"nonsense": True}))
    @patch("apps.economy.vocalcoach._bill")
    def test_an_unusable_reply_is_not_billed(self, bill, _post, _k):
        """A take the coach couldn't read must not cost the member a prompt."""
        resp = self.client.post(URL, {"take": take()}, format="multipart")
        self.assertEqual(resp.status_code, 502)
        bill.assert_not_called()

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini({**GOOD, "score": 47}))
    def test_a_wild_score_is_clamped_to_ten(self, _post, _k):
        self.assertEqual(self.client.post(URL, {"take": take()}, format="multipart").data["score"], 10)
