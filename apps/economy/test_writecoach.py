"""Written lyrics scored on the voice coach's lyric dimensions; under 6 opens the fixer."""
import json
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import WriteScore, wallet_for
from apps.economy.writecoach import parse

User = get_user_model()


def reply(score=6.5, dims=None):
    dims = dims or {"rhyme": 7, "punchlines": 4, "story": 6, "imagery": 8, "freshness": 5}
    body = {"score": score, "verdict": "Real bones.", "scores": dims,
            "reasons": {k: f"why {k}" for k in dims}, "fixes": {k: f"fix {k}" for k in dims}, "strengths": ["imagery"]}
    r = MagicMock(status_code=200)
    r.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps(body)}]}}]}
    return r


class WriteCoachTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("w", "w@e.com", "pw12345678")
        self.c = APIClient(); self.c.force_authenticate(self.u)
        w = wallet_for(self.u); w.promptz = 100; w.save()

    def test_under_six_is_handed_to_its_fixer(self):
        out = parse(json.dumps({"score": 6, "verdict": "", "scores": {"rhyme": 7, "punchlines": 4, "story": 6, "imagery": 8, "freshness": 5}}))
        fixers = {d["key"]: d.get("fixer") for d in out["dimensions"]}
        self.assertEqual(fixers, {"rhyme": None, "punchlines": "punchlines", "story": None, "imagery": None, "freshness": "freshangles"})

    def test_a_missing_dimension_is_unreadable_not_a_zero(self):
        self.assertIsNone(parse(json.dumps({"score": 6, "scores": {"rhyme": 7}})))

    @patch("apps.economy.writecoach._key", return_value="k")
    @patch("apps.economy.gemini.requests.post", return_value=reply())
    def test_scored_saved_and_xp(self, _p, _k):
        r = self.c.post("/api/economy/writecoach/", {"text": "my bars\nmore bars"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(WriteScore.objects.get().scores["punchlines"], 4)
        self.assertEqual(r.data["xp_awarded"], 25)
        self.assertEqual(len(self.c.get("/api/economy/writecoach/").data["history"]), 1)

    @patch("apps.economy.writecoach._key", return_value="k")
    @patch("apps.economy.gemini.requests.post", return_value=reply(score=None))
    def test_unreadable_is_not_charged(self, _p, _k):
        before = wallet_for(self.u).promptz
        r = self.c.post("/api/economy/writecoach/", {"text": "hmm"}, format="json")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(wallet_for(self.u).promptz, before)
        self.assertEqual(WriteScore.objects.count(), 0)
