import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.economy import mixz_stage as M
from apps.economy.models import Membership, Transaction
from apps.economy.catalog import TIER_STATZ


class FakeResp:
    status_code = 200

    def __init__(self, text):
        self._t = text

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": self._t}]}}]}


TRACKS = [{"name": "vox", "role": "lead", "lufs": -18, "bright": 0.5, "width_db": -30},
          {"name": "808", "role": "bass", "lufs": -14, "bright": 0.1, "width_db": -40},
          {"name": "pads", "role": "instrument", "lufs": -20, "bright": 0.7, "width_db": -30}]


class CleanTests(TestCase):
    def test_ranges_are_closed_and_the_low_end_stays_centred(self):
        t = M.clean_tracks(TRACKS)
        got = M.clean_answer({"field": "wide pads", "tracks": [
            {"i": 0, "gain_db": 99, "pan": 0.2, "why": "lead up"},
            {"i": 1, "gain_db": -3, "pan": -0.8, "why": "808 left"},
            {"i": 2, "gain_db": -6, "pan": 5, "why": "pads wide"},
            {"i": 9, "gain_db": 0, "pan": 0, "why": "no such track"},
            {"i": 2, "gain_db": 0, "pan": 0, "why": "twice"}]}, t)
        by = {m["i"]: m for m in got["moves"]}
        self.assertEqual(by[0]["gain_db"], 12); self.assertEqual(by[2]["pan"], 1)
        self.assertEqual(by[1]["pan"], 0); self.assertIn("centre", by[1]["why"])
        self.assertEqual(len(got["moves"]), 3)

    def test_unreadable_is_none(self):
        self.assertIsNone(M.parse("jazz", M.clean_tracks(TRACKS)))
        self.assertIsNone(M.clean_answer({"tracks": [{"i": 0, "gain_db": 1, "pan": 0, "why": ""}]}, M.clean_tracks(TRACKS)))


@override_settings(GEMINI_API_KEY="k")
class ViewTests(TestCase):
    def setUp(self):
        self.u = get_user_model().objects.create_user("stager", password="pw-long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def statz(self):
        m = Membership.objects.get_or_create(user=self.u)[0]; m.tier = TIER_STATZ; m.save()

    def test_free_members_are_told_and_nothing_runs(self):
        self.assertFalse(self.c.get("/api/economy/mixz/stage/").data["allowed"])
        with mock.patch.object(M, "generate_content") as g:
            r = self.c.post("/api/economy/mixz/stage/", {"tracks": TRACKS}, format="json")
        self.assertEqual(r.status_code, 403); g.assert_not_called()

    def test_statz_gets_moves_and_is_charged_once(self):
        self.statz()
        reply = json.dumps({"field": "Pads wide, vocal centre.", "tracks": [{"i": 2, "gain_db": -4, "pan": -0.4, "why": "give the lead the middle"}]})
        with mock.patch.object(M, "generate_content", return_value=(FakeResp(reply), ["m"])):
            r = self.c.post("/api/economy/mixz/stage/", {"tracks": TRACKS, "brief": "wide pads"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["moves"][0]["pan"], -0.4)
        self.assertEqual(Transaction.objects.filter(user=self.u, note__startswith="Mix ConnectZ gain staging").count(), 1)

    def test_an_unreadable_answer_is_not_charged(self):
        self.statz()
        with mock.patch.object(M, "generate_content", return_value=(FakeResp("nope"), ["m"])):
            r = self.c.post("/api/economy/mixz/stage/", {"tracks": TRACKS}, format="json")
        self.assertEqual(r.status_code, 502)
        self.assertFalse(Transaction.objects.filter(user=self.u, note__startswith="Mix ConnectZ gain staging").exists())

    def test_silence_is_refused_before_anything_runs(self):
        self.statz()
        r = self.c.post("/api/economy/mixz/stage/", {"tracks": [{"name": "x", "lufs": None}]}, format="json")
        self.assertEqual(r.status_code, 400)
