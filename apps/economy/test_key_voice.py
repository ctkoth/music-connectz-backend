"""The keyboard's voice — and the rule about what a tier may be sold.

`keyconnectz.py` set the line in its own first paragraph: the wallpaper is
Premium because it is DECORATION, and nobody loses a capability by not having
it; translate is free at every tier because being understood is not a luxury.

Voice sits on the capability side of that line, twice over. Read-aloud is the
second half of translate — hand somebody the Portuguese and charge them to hear
how to SAY it and you have sold half a capability and given away the bait.
Speech input is how you type when typing is the hard part, so an access gate
lands hardest on exactly the members it should be helping.

So what a tier buys here is HOW OFTEN, the same answer BossTake's ladder gives.
These pin that, and pin the two places it would quietly rot: a failed run must
never spend the allowance, and the device's own voice must never be metered.
"""
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.catalog import KEY_SPEAK_DAILY_CHARS, KEY_TRANSCRIBE_DAILY_CLIPS
from apps.economy.models import (TIER_FREE, TIER_PREMIUM, TIER_STATZ, KeyVoiceUse,
                                 membership_for)

User = get_user_model()
PW = "pw12345!"
KEYZ, TRANSCRIBE, SPEAK = ("/api/economy/keyz/", "/api/economy/keyz/transcribe/",
                           "/api/economy/keyz/speak/")


def clip(name="v.webm", ct="audio/webm;codecs=opus"):
    return SimpleUploadedFile(name, b"0" * 2048, content_type=ct)


def gemini_text(text="hey, where's the studio", detected="en"):
    m = Mock(); m.status_code = 200
    m.json.return_value = {"candidates": [{"content": {"parts": [
        {"text": '{"text": "%s", "detected": "%s"}' % (text, detected)}]}}]}
    return m


def gemini_audio(pcm=b"\x01\x02" * 400):
    import base64
    m = Mock(); m.status_code = 200
    m.json.return_value = {"candidates": [{"content": {"parts": [
        {"inline_data": {"mime_type": "audio/L16;codec=pcm;rate=24000",
                         "data": base64.b64encode(pcm).decode()}}]}}]}
    return m


class Base(TestCase):
    tier = TIER_FREE

    def setUp(self):
        self.me = User.objects.create_user(username="talker", password=PW)
        m = membership_for(self.me); m.tier = self.tier; m.save()
        self.c = APIClient(); self.c.force_authenticate(self.me)


class NeitherIsSoldAsAnAbilityTests(Base):

    def test_a_free_member_may_transcribe(self):
        """The gate this deliberately does NOT have. Speech input is how you
        type when typing is the hard part."""
        self.assertTrue(self.c.get(KEYZ).json()["voice"]["transcribe_allowed"])

    def test_a_free_member_may_be_read_to(self):
        """Read-aloud is the second half of translate, which is free."""
        self.assertTrue(self.c.get(KEYZ).json()["voice"]["speak_allowed"])

    def test_neither_costs_promptz(self):
        v = self.c.get(KEYZ).json()["voice"]
        self.assertEqual(v["cost_cents"], 0)

    def test_the_wallpaper_is_still_premium(self):
        """The line has not moved — decoration is still fair to sell."""
        self.assertFalse(self.c.get(KEYZ).json()["wallpaper_allowed"])

    def test_the_allowance_is_published_before_either_button(self):
        """A limit you find out about by hitting it is not a limit, it's an
        ambush — the file's own words about translate."""
        v = self.c.get(KEYZ).json()["voice"]
        for field in ("clips_daily", "clips_remaining", "clip_max_seconds",
                      "speak_daily_chars", "speak_remaining", "ladder"):
            self.assertIn(field, v)

    def test_the_ladder_says_what_a_tier_up_would_buy(self):
        """A member who has spent today's clips gets an offer, not a wall."""
        ladder = self.c.get(KEYZ).json()["voice"]["ladder"]
        self.assertEqual([r["tier"] for r in ladder],
                         [TIER_FREE, TIER_PREMIUM, TIER_STATZ])
        self.assertLess(ladder[0]["clips"], ladder[1]["clips"])
        self.assertLess(ladder[1]["clips"], ladder[2]["clips"])

    def test_the_device_voice_is_free_and_unmetered(self):
        """It costs us nothing, so there is no bill to justify a gate — and
        metering it would be counting something we don't pay for."""
        self.assertTrue(self.c.get(KEYZ).json()["voice"]["device_voice_free"])


class WhatTheTierActuallyBuysTests(TestCase):

    def state_for(self, tier):
        u = User.objects.create_user(username=f"m{tier}", password=PW)
        m = membership_for(u); m.tier = tier; m.save()
        c = APIClient(); c.force_authenticate(u)
        return c.get(KEYZ).json()["voice"]

    def test_a_tier_buys_frequency_not_access(self):
        free, premium, statz = (self.state_for(t) for t in
                                (TIER_FREE, TIER_PREMIUM, TIER_STATZ))
        # Everyone can. Only the number differs.
        for v in (free, premium, statz):
            self.assertTrue(v["transcribe_allowed"] and v["speak_allowed"])
        self.assertEqual(free["clips_daily"], KEY_TRANSCRIBE_DAILY_CLIPS[TIER_FREE])
        self.assertEqual(statz["clips_daily"], KEY_TRANSCRIBE_DAILY_CLIPS[TIER_STATZ])
        self.assertGreater(premium["speak_daily_chars"], free["speak_daily_chars"])
        self.assertGreater(statz["speak_daily_chars"], premium["speak_daily_chars"])


class TranscribingTests(Base):

    @patch("apps.economy.keyconnectz.gemini_key", return_value="k")
    @patch("apps.economy.gemini.requests.post", return_value=gemini_text())
    def test_a_clip_comes_back_as_words(self, _rq, _k):
        r = self.c.post(TRANSCRIBE, {"clip": clip()}, format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["text"], "hey, where's the studio")
        self.assertEqual(r.data["clips_used_today"], 1)
        self.assertEqual(r.data["cost_cents"], 0)

    @patch("apps.economy.keyconnectz.gemini_key", return_value="k")
    @patch("apps.economy.gemini.requests.post", return_value=gemini_text())
    def test_chrome_parameters_are_stripped_before_the_model_sees_them(self, rq, _k):
        """`audio/webm;codecs=opus` is what a browser records. The model
        rejects the whole string rather than ignoring the part it doesn't
        need — the same trap the coach fell into."""
        self.c.post(TRANSCRIBE, {"clip": clip()}, format="multipart")
        parts = rq.call_args.kwargs["json"]["contents"][0]["parts"]
        sent = [p for p in parts if "inline_data" in p][0]["inline_data"]["mime_type"]
        self.assertEqual(sent, "audio/webm")
        self.assertNotIn(";", sent)

    @patch("apps.economy.keyconnectz.gemini_key", return_value="k")
    def test_a_container_the_model_cannot_read_never_reaches_it(self, _k):
        with patch("apps.economy.gemini.requests.post") as post:
            r = self.c.post(TRANSCRIBE, {"clip": clip("v.xyz", "audio/x-weird")},
                            format="multipart")
        self.assertEqual(r.status_code, 400)
        self.assertIn("x-weird", r.data["detail"])
        post.assert_not_called()

    @patch("apps.economy.keyconnectz.gemini_key", return_value="k")
    @patch("apps.economy.gemini.requests.post", return_value=gemini_text(text=""))
    def test_a_clip_that_came_back_empty_is_not_counted(self, _rq, _k):
        """A failed run must never eat the member's day — the same rule that
        keeps a failed Boss Take unbilled and a failed translation free."""
        r = self.c.post(TRANSCRIBE, {"clip": clip()}, format="multipart")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(KeyVoiceUse.objects.count(), 0)
        self.assertIn("hasn't cost you one", r.data["detail"])

    @patch("apps.economy.keyconnectz.gemini_key", return_value="k")
    def test_running_out_says_what_lifts_it_and_what_stays_free(self, _k):
        for _ in range(KEY_TRANSCRIBE_DAILY_CLIPS[TIER_FREE]):
            KeyVoiceUse.objects.create(user=self.me, kind=KeyVoiceUse.KIND_TRANSCRIBE, units=1)
        r = self.c.post(TRANSCRIBE, {"clip": clip()}, format="multipart")
        self.assertEqual(r.status_code, 429)
        self.assertIn("a tier up raises it", r.data["detail"])
        self.assertIn("translating stay free", r.data["detail"])
        self.assertIn("ladder", r.data)

    def test_an_oversize_clip_says_what_one_clip_is(self):
        big = SimpleUploadedFile("v.webm", b"0" * (9 * 1024 * 1024),
                                 content_type="audio/webm")
        r = self.c.post(TRANSCRIBE, {"clip": big}, format="multipart")
        self.assertEqual(r.status_code, 413)
        self.assertIn("one thing said", r.data["detail"])


class ReadingAloudTests(Base):

    @patch("apps.economy.keyconnectz.gemini_key", return_value="k")
    @patch("apps.economy.gemini.requests.post", return_value=gemini_audio())
    def test_text_comes_back_as_playable_audio(self, _rq, _k):
        import base64
        r = self.c.post(SPEAK, {"text": "hola", "lang": "es"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["mime"], "audio/wav")
        # A browser will not play raw PCM. The header goes on here rather than
        # in three clients that would each get it slightly wrong.
        self.assertTrue(base64.b64decode(r.data["audio_b64"]).startswith(b"RIFF"))

    @patch("apps.economy.keyconnectz.gemini_key", return_value="k")
    @patch("apps.economy.gemini.requests.post", return_value=gemini_audio())
    def test_it_asks_a_tts_model_not_a_text_one(self, rq, _k):
        """responseModalities:["AUDIO"] against gemini-2.5-flash is a 400, not
        a fallback — so the chain has to be its own."""
        self.c.post(SPEAK, {"text": "hola", "lang": "es"}, format="json")
        self.assertIn("tts", rq.call_args.args[0])
        self.assertEqual(rq.call_args.kwargs["json"]["generationConfig"]
                         ["responseModalities"], ["AUDIO"])

    @patch("apps.economy.keyconnectz.gemini_key", return_value="k")
    @patch("apps.economy.gemini.requests.post", return_value=gemini_audio(pcm=b""))
    def test_an_empty_voice_is_not_counted(self, _rq, _k):
        r = self.c.post(SPEAK, {"text": "hola", "lang": "es"}, format="json")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(KeyVoiceUse.objects.count(), 0)
        self.assertIn("Nothing was counted", r.data["detail"])

    @patch("apps.economy.keyconnectz.gemini_key", return_value="k")
    def test_running_out_points_at_the_free_voice_that_still_works(self, _k):
        KeyVoiceUse.objects.create(user=self.me, kind=KeyVoiceUse.KIND_SPEAK,
                                   units=KEY_SPEAK_DAILY_CHARS[TIER_FREE])
        r = self.c.post(SPEAK, {"text": "hola", "lang": "es"}, format="json")
        self.assertEqual(r.status_code, 429)
        self.assertIn("phone's own voice is unlimited and free", r.data["detail"])

    @patch("apps.economy.keyconnectz.gemini_key", return_value="")
    def test_no_key_still_leaves_the_member_a_voice(self, _k):
        r = self.c.post(SPEAK, {"text": "hola", "lang": "es"}, format="json")
        self.assertEqual(r.status_code, 503)
        self.assertIn("phone's own voice still works", r.data["detail"])

    @patch("apps.economy.keyconnectz.gemini_key", return_value="k")
    @patch("apps.economy.gemini.requests.post", return_value=gemini_audio())
    def test_the_two_allowances_are_kept_apart(self, _rq, _k):
        """Reading and listening are different actions in different units.
        Spending one must not spend the other."""
        self.c.post(SPEAK, {"text": "hola", "lang": "es"}, format="json")
        v = self.c.get(KEYZ).json()["voice"]
        self.assertEqual(v["clips_used_today"], 0)
        self.assertEqual(v["speak_used_today"], 4)
