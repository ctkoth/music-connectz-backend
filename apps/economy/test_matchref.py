"""Inspiration: a take heard against a reference, nothing kept, lyrics as direction only."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import matchref, models as m
from apps.economy.instruments import scores_for
from apps.economy.models import wallet_for
from apps.economy.test_vocalcoach import fake_gemini

User = get_user_model()
REPLY = {
    "unscorable": None, "closeness": 62, "closeness_why": "Cadence close, low end thin.",
    "scores": {k: {"take": 6, "reference": 8} for k in scores_for("rapz")},
    "summary": "Low end is the gap.", "keep": "Your pocket.",
    "eq": [{"region": "low", "direction": "more", "what": "thin", "how": "+3dB at 100Hz"},
           {"region": "bogus", "direction": "more"}, {"region": "air", "direction": "sideways"}],
    "how_to": [{"what": "Weight", "why": "w", "how": "h"}],
    "lyric_direction": "Short punchy bars, internal rhyme.", "invented": "x",
}


def f(name):
    return SimpleUploadedFile(name, b"RIFFxxxxWAVE" * 50, content_type="audio/wav")


class InspirationTests(TestCase):
    def setUp(self):
        self.c = APIClient()
        self.u = User.objects.create_user("i", "i@e.com", "pw12345678")
        self.c.force_authenticate(self.u)
        w = wallet_for(self.u); w.money_cents = 10000; w.save()

    def _post(self, reply=REPLY, **files):
        with patch("apps.economy.matchref._key", return_value="k"), \
             patch("apps.economy.vocalcoach._key", return_value="k"), \
             patch("apps.economy.gemini.requests.post", return_value=fake_gemini(reply)):
            return self.c.post("/api/rapz/match/", files or {"take": f("t.wav"), "reference": f("r.wav")},
                               format="multipart")

    def test_price_is_stated_before_anything_is_sent(self):
        r = self.c.get("/api/rapz/match/")
        self.assertEqual(r.json()["feature"], "Inspiration")
        self.assertFalse(r.json()["charged_on_failure"])

    def test_reply_is_whitelisted_and_nothing_is_kept(self):
        before = {n: getattr(m, n).objects.count() for n in ("TakeScore", "Upload", "Post") if hasattr(m, n)}
        r = self._post()
        self.assertEqual(r.status_code, 200, r.content)
        j = r.json()
        self.assertEqual([e["region"] for e in j["eq"]], ["low"])
        self.assertEqual(j["eq"][0]["hz"], "60-250 Hz")
        self.assertNotIn("invented", j)
        self.assertEqual(j["lyric_direction"], REPLY["lyric_direction"])
        self.assertEqual(before, {n: getattr(m, n).objects.count() for n in before})

    def test_needs_both_files(self):
        r = self._post(take=f("t.wav"))
        self.assertEqual(r.status_code, 400)

    def test_unreadable_reply_is_not_charged(self):
        w0 = wallet_for(self.u).money_cents
        r = self._post(reply={"closeness": None})
        self.assertEqual(r.status_code, 502)
        self.assertEqual(wallet_for(self.u).money_cents, w0)
