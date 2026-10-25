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


class InspirationElsewhereTests(TestCase):
    def setUp(self):
        self.c = APIClient()
        self.u = User.objects.create_user("j", "j@e.com", "pw12345678")
        self.c.force_authenticate(self.u)
        w = wallet_for(self.u); w.money_cents = 10000; w.save()

    def test_instrumental_setup_is_validated(self):
        from apps.economy.instrumentalz import clean_inspiration
        out = clean_inspiration({"bpm": 999, "key": "Zz", "instruments": ["drums", "kazoo"], "bars": 5,
                                 "brief": "b"})
        self.assertEqual((out["bpm"], out["key"], out["instruments"], out["bars"]), (200, "", ["drums"], 4))
        self.assertIsNone(clean_inspiration({"bpm": 90, "instruments": ["kazoo"]}))

    def test_instrumental_inspiration_endpoint(self):
        reply = {"unscorable": None, "genre": "trap", "bpm": 140, "key": "A minor",
                 "instruments": ["drums", "bass"], "bars": 8, "brief": "dark", "feel": "f"}
        with patch("apps.economy.instrumentalz._key", return_value="k"), \
             patch("apps.economy.vocalcoach._key", return_value="k"), \
             patch("apps.economy.gemini.requests.post", return_value=fake_gemini(reply)):
            r = self.c.post("/api/economy/instrumentalz/inspiration/",
                            {"reference": f("r.wav"), "lyrics": "my words"}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["bpm"], 140)

    def test_image_inspiration_needs_a_picture(self):
        with patch("apps.economy.gemini._key", return_value="k"):
            r = self.c.post("/api/economy/gemini/image/", {"prompt": "cover", "inspiration": "1"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("inspiration_note", self.c.get("/api/economy/gemini/image/").json())


class SentenceInspirationTests(TestCase):
    def setUp(self):
        self.c = APIClient()
        self.u = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.c.force_authenticate(self.u)
        w = wallet_for(self.u); w.money_cents = 10000; w.save()

    def test_depth_fixer_exists_and_finds_feelz(self):
        from apps.economy import sentencez
        self.assertEqual(sentencez.FIXER_FOR_DIM["feelz"], "depth")

    def test_direction_for_a_fixer(self):
        reply = {"unscorable": None, "direction": "Setup then twist; plain words.", "moves": ["reversal"]}
        with patch("apps.economy.sentencez._key", return_value="k"), \
             patch("apps.economy.vocalcoach._key", return_value="k"), \
             patch("apps.economy.gemini.requests.post", return_value=fake_gemini(reply)):
            r = self.c.post("/api/economy/sentencez/inspiration/",
                            {"reference": f("r.wav"), "kind": "punchlines"}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["moves"], ["reversal"])

    def test_refuses_a_contract_kind_and_missing_song(self):
        self.assertEqual(self.c.post("/api/economy/sentencez/inspiration/", {"kind": "punchlines"},
                                     format="multipart").status_code, 400)
        self.assertEqual(self.c.post("/api/economy/sentencez/inspiration/",
                                     {"reference": f("r.wav"), "kind": "contract"},
                                     format="multipart").status_code, 400)


class WitDepthTests(TestCase):
    def test_opt_in_only_where_there_are_words(self):
        from apps.economy.instruments import prompt_for, scores_for
        self.assertNotIn("wit", scores_for("rapz"))
        self.assertIn("wit", scores_for("rapz", extras=("wit",)))
        self.assertNotIn("wit", scores_for("drumz", extras=("wit",)))
        self.assertIn('"depth"', prompt_for("singz", "pop", "x", "builder", extras=("depth",)))
        self.assertNotIn("wit_note", prompt_for("singz", "pop", "x", "builder"))

    def test_counted_only_when_opted_in(self):
        from apps.economy import vocalcoach as vc
        from apps.economy.instruments import scores_for
        base = {k: 6 for k in scores_for("rapz")}
        good = {**GOODISH, "scores": {**base, "wit": 10, "depth": 10}, "wit_note": "n"}
        def run(counted):
            with patch("apps.economy.vocalcoach._key", return_value="k"), \
                 patch("apps.economy.gemini.requests.post", return_value=fake_gemini(good)):
                out, err = vc.score_take("rapz", f("t.wav"), "audio/wav", genre="trap", target=None,
                                         difficulty="builder", think=False,
                                         extras=("wit", "depth"), counted=counted)
            self.assertIsNone(err)
            return out
        beside, inside = run(()), run(("wit",))
        self.assertEqual(beside["scores"]["wit"], 10)
        self.assertEqual(beside["counted_extras"], [])
        self.assertEqual(inside["counted_extras"], ["wit"])
        self.assertGreater(inside["score_exact"], beside["score_exact"])


from apps.economy.test_vocalcoach import GOOD as GOODISH  # noqa: E402
