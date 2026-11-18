import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.economy import mixz_ai as M
from apps.economy.models import Transaction


class FakeResp:
    def __init__(self, text, code=200):
        self.status_code = code
        self._t = text

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": self._t}]}}]}


def clip():
    return SimpleUploadedFile("song.mp3", b"ID3" + b"\x00" * 2000, content_type="audio/mpeg")


class PresetTests(TestCase):
    def test_every_genre_states_why_and_uses_only_what_the_engine_reads(self):
        for k, g in M.GENRES.items():
            s = g["settings"]
            self.assertIn(s["style"], M.STYLES, k); self.assertIn(s["intensity"], M.INTENSITIES, k); self.assertIn(s["target"], M.TARGETS, k)
            self.assertTrue(len(g["why"]) > 30, k)
            for t in ("low", "mid", "high"):
                self.assertTrue(-4 <= s["trims"][t] <= 4, k)

    def test_moves_outside_the_closed_list_or_range_are_dropped_or_clamped(self):
        got = M.clean_moves([{"key": "punch", "value": 400, "why": "hits are soft"},
                             {"key": "rm -rf", "value": 1, "why": "x"},
                             {"key": "style", "value": "neon", "why": "x"},
                             {"key": "trims.low", "value": "-1.3", "why": "the low end is heavy"},
                             {"key": "multiband", "value": "true", "why": "kick pumps the vocal"},
                             {"key": "vocal", "value": 2, "why": ""},
                             {"key": "punch", "value": 1, "why": "twice"}])
        self.assertEqual(got, [{"key": "punch", "value": 50, "why": "hits are soft"},
                               {"key": "trims.low", "value": -1.5, "why": "the low end is heavy"},
                               {"key": "multiband", "value": True, "why": "kick pumps the vocal"}])
        s = M.apply_moves("lofi", got)
        self.assertEqual((s["punch"], s["trims"]["low"], s["multiband"]), (50, -1.5, True))
        self.assertEqual(M.GENRES["lofi"]["settings"]["punch"], -10, "the preset itself is not changed")

    def test_an_unknown_genre_is_no_answer(self):
        self.assertIsNone(M.parse(json.dumps({"genre": "polka", "moves": []})))
        self.assertIsNone(M.parse("not json"))


@override_settings(GEMINI_API_KEY="k")
class ListenTests(TestCase):
    def setUp(self):
        self.u = get_user_model().objects.create_user("mixer", password="pw-long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def test_get_states_the_price_and_the_free_presets(self):
        d = self.c.get("/api/economy/mixz/ai/").data
        self.assertEqual(len(d["genres"]), len(M.GENRES))
        self.assertIn("cost_cents", d["price"]); self.assertIn("energy", d["price"])
        self.assertIn("not charged", d["note"])

    def test_a_listen_sets_the_controls_and_is_charged_once(self):
        reply = json.dumps({"genre": "hiphop", "heard": "Big 808, vocal a little buried.",
                            "moves": [{"key": "vocal", "value": 2, "why": "the vocal sits under the 808"}]})
        with mock.patch.object(M, "generate_content", return_value=(FakeResp(reply), ["m"])):
            r = self.c.post("/api/economy/mixz/ai/", {"clip": clip()}, format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["genre"], "hiphop")
        self.assertEqual(r.data["settings"]["vocal"], 2)
        self.assertTrue(r.data["settings"]["multiband"])
        self.assertEqual(Transaction.objects.filter(user=self.u, note__startswith="Mix ConnectZ AI listen").count(), 1)

    def test_an_unreadable_answer_is_not_charged(self):
        with mock.patch.object(M, "generate_content", return_value=(FakeResp("I think it is jazz"), ["m"])):
            r = self.c.post("/api/economy/mixz/ai/", {"clip": clip()}, format="multipart")
        self.assertEqual(r.status_code, 502)
        self.assertFalse(Transaction.objects.filter(user=self.u, note__startswith="Mix ConnectZ AI listen").exists())

    def test_a_non_audio_file_is_refused_before_anything_runs(self):
        with mock.patch.object(M, "generate_content") as g:
            r = self.c.post("/api/economy/mixz/ai/", {"clip": SimpleUploadedFile("x.exe", b"MZ", content_type="application/octet-stream")}, format="multipart")
        self.assertEqual(r.status_code, 400); g.assert_not_called()
