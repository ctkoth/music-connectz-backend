"""Video ConnectZ Develop mode: StatZ plans each shot by hearing the member's own
track, on the server's own slot clock, and a failed plan is not charged."""
import json
import tempfile
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy import videodevelop
from apps.economy.models import Membership, StatzTrial, Transaction, Upload, wallet_for

User = get_user_model()
URL = "/api/economy/videoz/develop/"


def reply(obj, code=200):
    r = MagicMock(status_code=code, text="")
    r.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}]}
    return r


def plan(n, **slot):
    return {"overall": "a slow build to a big chorus", "look": "neon rain, 35mm grain",
            "slots": [{"heard": f"line {i}", "mood": "aching", "options": [
                {"shot": f"shot {i}a", "ties_to": "lyric", "why": "it is the line sung", **slot},
                {"shot": f"shot {i}b", "ties_to": "beat", "why": "the drop"},
                {"shot": f"shot {i}c", "ties_to": "nonsense", "why": "?"},
                {"shot": "a fourth one", "ties_to": "mood", "why": "too many"}],
            "pick": 1 if i == 0 else 7, "pick_why": "the drop lands here"} for i in range(n)]}


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class DevelopTests(TestCase):
    def setUp(self):
        k = patch("apps.economy.videodevelop._key", return_value="K"); k.start(); self.addCleanup(k.stop)
        self.u = User.objects.create_user("director", "d@e.com", "pw-Long-enough-1")
        Membership.objects.update_or_create(user=self.u, defaults={"tier": "statz"})
        w = wallet_for(self.u); w.promptz = 100; w.money_cents = 1000; w.save()
        self.c = APIClient(); self.c.force_authenticate(self.u)
        self.track = Upload.objects.create(user=self.u, name="song.mp3", content_type="audio/mpeg")
        self.track.file.save("song.mp3", ContentFile(b"ID3 fake audio"), save=True)

    def post(self, model_reply, **kw):
        with patch("apps.economy.videodevelop.generate_content", return_value=(model_reply, [])) as g:
            r = self.c.post(URL, {"track_id": self.track.id, "shots": 3, "track_start": 60, **kw}, format="json")
        return r, g

    def test_the_price_and_the_gate_are_said_before_the_button(self):
        d = self.c.get(URL).json()
        self.assertTrue(d["allowed"])
        self.assertFalse(d["charged_on_failure"])
        self.assertGreater(d["cost_cents"], 0)
        self.assertIn("listens", d["what_it_does"])

    def test_the_slots_are_the_stitchs_own_clock_not_the_models(self):
        r, g = self.post(reply(plan(3)), lyrics="my own words", mood="lonely")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([(s["start"], s["end"]) for s in r.data["slots"]], [(60, 68), (68, 76), (76, 84)])
        self.assertEqual(r.data["slots"][0]["at"], "1:00–1:08")
        sent = g.call_args.args[1]["contents"][0]["parts"]
        self.assertIn("slot 2: 1:08–1:16", sent[0]["text"])
        self.assertIn("my own words", sent[0]["text"])
        self.assertIn("inline_data", sent[1])                      # it HEARS the track

    def test_options_are_capped_whitelisted_and_carry_why(self):
        r, _ = self.post(reply(plan(3)))
        opts = r.data["slots"][0]["options"]
        self.assertEqual(len(opts), videodevelop.OPTIONS)
        self.assertEqual(opts[2]["ties_to"], "mood")               # an invented tie becomes mood
        self.assertEqual(opts[0]["why"], "it is the line sung")
        self.assertEqual(r.data["look"], "neon rain, 35mm grain")

    def test_direct_mode_carries_the_coachs_pick_and_an_invented_one_falls_back_without_its_reason(self):
        r, _ = self.post(reply(plan(3)))
        self.assertEqual((r.data["slots"][0]["pick"], r.data["slots"][0]["pick_why"]), (1, "the drop lands here"))
        self.assertEqual((r.data["slots"][1]["pick"], r.data["slots"][1]["pick_why"]), (0, ""))
        self.assertIn("direct", self.c.get(URL).json()["modes"])

    def test_a_plan_is_charged_once_and_a_failed_one_is_not(self):
        before = Transaction.objects.count()
        r, _ = self.post(reply({"slots": [{"options": []}]}))
        self.assertEqual(r.status_code, 502)
        r, _ = self.post(reply({}, code=500))
        self.assertEqual(r.status_code, 502)
        r, _ = self.post(reply({"unplannable": "That file is silent."}))
        self.assertEqual(r.data["unplannable"], "That file is silent.")
        self.assertEqual(Transaction.objects.count(), before)
        r, _ = self.post(reply(plan(3)))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Transaction.objects.count(), before + 1)

    def test_free_and_premium_are_refused_before_anything_runs_and_the_sample_opens_it(self):
        Membership.objects.filter(user=self.u).update(tier="premium")
        self.assertFalse(self.c.get(URL).json()["allowed"])
        r, g = self.post(reply(plan(3)))
        self.assertEqual(r.status_code, 403)
        self.assertIn("StatZ", r.data["detail"])
        g.assert_not_called()
        StatzTrial.objects.create(user=self.u, ends_at=timezone.now() + timedelta(minutes=10))
        r, _ = self.post(reply(plan(3)))
        self.assertEqual(r.status_code, 200)

    def test_only_your_own_track_and_a_shot_count_the_stitch_can_render(self):
        other = User.objects.create_user("other", "o@e.com", "pw-Long-enough-1")
        theirs = Upload.objects.create(user=other, name="t.mp3", content_type="audio/mpeg")
        r, g = self.post(reply(plan(3)), track_id=theirs.id)
        self.assertEqual(r.status_code, 400)
        r, g = self.post(reply(plan(9)), shots=9)
        self.assertEqual(r.status_code, 400)
        g.assert_not_called()
