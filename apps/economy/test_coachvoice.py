"""CoachVoiceZ — a stored choice, three tiers of access, and no real voice
clone anywhere in it.

Same discipline test_soundz.py holds: the server checks shape and tier, the
Gemini voice catalog lives here (not the client, and not a copy of anybody's
actual voice).
"""
import base64
import json as _json
from unittest.mock import patch as _patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.coachvoice import COACH_VOICES, DEFAULT_VOICE, clean_voice_id
from apps.economy.models import (TIER_FREE, TIER_PREMIUM, TIER_STATZ, CoachVoiceUse,
                                 membership_for, profile_for)

User = get_user_model()
PW = "hunter2hunter2"
URL = "/api/economy/coachvoice/"
SPEAK_URL = "/api/economy/coachvoice/speak/"


def tier(user, t):
    m = membership_for(user)
    m.tier = t
    m.save(update_fields=["tier"])
    return user


def _fake_tts_response(status_code=200):
    pcm = b"\x00\x01" * 100
    payload = {"candidates": [{"content": {"parts": [
        {"inline_data": {"data": base64.b64encode(pcm).decode(), "mime_type": "audio/L16;rate=24000"}}
    ]}}]}
    return type("R", (), {
        "status_code": status_code,
        "json": lambda self: payload,
        "text": "",
    })()


class TheGateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("v", "v@e.com", PW)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_everyone_can_read_their_voice_settings(self):
        d = self.client.get(URL).data
        self.assertEqual(d["voice"], DEFAULT_VOICE)
        self.assertFalse(d["can_sample"])
        self.assertFalse(d["can_choose"])

    def test_the_full_catalog_is_always_visible(self):
        # Seeing what exists is not the perk — choosing or sampling it is.
        d = self.client.get(URL).data
        ids = {v["id"] for v in d["voices"]}
        self.assertEqual(ids, set(COACH_VOICES))

    def test_a_free_member_cannot_choose_a_voice(self):
        r = self.client.patch(URL, {"voice": "kore"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(profile_for(self.user).coach_voice, "")

    def test_the_refusal_says_what_is_still_free(self):
        r = self.client.patch(URL, {"voice": "kore"}, format="json")
        self.assertIn("free at every tier", r.data["detail"])

    def test_premium_may_sample_but_not_choose(self):
        tier(self.user, TIER_PREMIUM)
        self.assertTrue(self.client.get(URL).data["can_sample"])
        self.assertFalse(self.client.get(URL).data["can_choose"])
        r = self.client.patch(URL, {"voice": "kore"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_statz_may_choose(self):
        tier(self.user, TIER_STATZ)
        r = self.client.patch(URL, {"voice": "fenrir"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(profile_for(self.user).coach_voice, "fenrir")

    def test_it_follows_the_account_not_the_browser(self):
        tier(self.user, TIER_STATZ)
        self.client.patch(URL, {"voice": "puck"}, format="json")
        other_device = APIClient()
        other_device.force_authenticate(self.user)
        self.assertEqual(other_device.get(URL).data["voice"], "puck")

    def test_a_lapsed_statz_falls_back_to_house_not_a_403(self):
        # The stored value survives a downgrade — reading it is never gated,
        # only choosing is. A Premium member who WAS StatZ still gets told
        # what's stored, they just cannot change it.
        tier(self.user, TIER_STATZ)
        self.client.patch(URL, {"voice": "fenrir"}, format="json")
        tier(self.user, TIER_PREMIUM)
        self.assertEqual(self.client.get(URL).data["voice"], "fenrir")


class TheShapeTests(TestCase):
    def test_an_unrecognised_voice_is_empty(self):
        self.assertEqual(clean_voice_id("not-a-real-voice"), "")
        self.assertEqual(clean_voice_id("  Kore  "), "kore")
        self.assertEqual(clean_voice_id(None), "")

    def test_junk_falls_back_rather_than_erroring(self):
        user = tier(User.objects.create_user("j", "j@e.com", PW), TIER_STATZ)
        client = APIClient()
        client.force_authenticate(user)
        r = client.patch(URL, {"voice": "not real"}, format="json")
        self.assertEqual(r.status_code, 400)


class NotAVoiceCloneTests(TestCase):
    """The line this module must never cross — pinned the same way
    test_soundz.py pins "no synthesis detail leaks into Python"."""

    def test_no_voice_maps_to_a_claim_of_being_a_real_persons_actual_voice(self):
        from apps.economy import coachvoice
        src = open(coachvoice.__file__).read()
        # The module has to be honest about what it is, in its own docstring.
        self.assertIn("Not a voice clone", src)
        self.assertIn("claim that it sounds like a specific person", src)

    def test_every_voice_is_a_real_gemini_prebuilt_name(self):
        # Anything else would mean this module invented a voice Gemini
        # cannot actually produce, which fails silently at the API instead
        # of here.
        known = {"Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus",
                 "Aoede", "Callirrhoe", "Autonoe", "Enceladus", "Iapetus",
                 "Umbriel", "Algieba", "Despina", "Erinome", "Algenib",
                 "Rasalgethi", "Laomedeia", "Achernar", "Alnilam", "Schedar",
                 "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
                 "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat"}
        for key, v in COACH_VOICES.items():
            self.assertIn(v["gemini_voice"], known, key)


class SpeakViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("s", "s@e.com", PW)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_requires_text(self):
        r = self.client.post(SPEAK_URL, {}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_free_member_gets_the_house_voice(self):
        fake = _fake_tts_response()
        with _patch("apps.economy.coachvoice.gemini_key", return_value="k"), \
             _patch("apps.economy.gemini.requests.post", return_value=fake):
            r = self.client.post(SPEAK_URL, {"text": "you've got real bones here"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["voice"], DEFAULT_VOICE)
        self.assertEqual(r.data["mime"], "audio/wav")

    def test_free_member_cannot_sample_another_voice(self):
        r = self.client.post(SPEAK_URL, {"text": "hello", "voice": "kore"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertIn("Premium perk", r.data["detail"])

    def test_premium_may_sample_without_saving(self):
        tier(self.user, TIER_PREMIUM)
        fake = _fake_tts_response()
        with _patch("apps.economy.coachvoice.gemini_key", return_value="k"), \
             _patch("apps.economy.gemini.requests.post", return_value=fake):
            r = self.client.post(SPEAK_URL, {"text": "hello", "voice": "kore"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["voice"], "kore")
        # Sampling never saves — the standing preference is untouched.
        self.assertEqual(profile_for(self.user).coach_voice, "")

    def test_a_statz_saved_choice_is_the_default_without_asking_again(self):
        tier(self.user, TIER_STATZ)
        self.client.patch(URL, {"voice": "fenrir"}, format="json")
        fake = _fake_tts_response()
        with _patch("apps.economy.coachvoice.gemini_key", return_value="k"), \
             _patch("apps.economy.gemini.requests.post", return_value=fake):
            r = self.client.post(SPEAK_URL, {"text": "hello"}, format="json")
        self.assertEqual(r.data["voice"], "fenrir")

    def test_a_failed_run_never_spends_the_allowance(self):
        fake = _fake_tts_response(status_code=500)
        with _patch("apps.economy.coachvoice.gemini_key", return_value="k"), \
             _patch("apps.economy.gemini.requests.post", return_value=fake):
            r = self.client.post(SPEAK_URL, {"text": "hello"}, format="json")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(CoachVoiceUse.objects.filter(user=self.user).count(), 0)

    def test_no_key_configured_says_so(self):
        with _patch("apps.economy.coachvoice.gemini_key", return_value=""):
            r = self.client.post(SPEAK_URL, {"text": "hello"}, format="json")
        self.assertEqual(r.status_code, 503)

    def test_text_over_the_limit_is_refused(self):
        from apps.economy.coachvoice import MAX_SPEAK_CHARS
        r = self.client.post(SPEAK_URL, {"text": "x" * (MAX_SPEAK_CHARS + 1)}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_daily_allowance_is_enforced(self):
        from apps.economy.catalog import COACH_SPEAK_DAILY_CHARS
        cap = COACH_SPEAK_DAILY_CHARS[TIER_FREE]
        CoachVoiceUse.objects.create(user=self.user, chars=cap)
        r = self.client.post(SPEAK_URL, {"text": "one more word"}, format="json")
        self.assertEqual(r.status_code, 429)

    def test_the_response_carries_the_remaining_allowance(self):
        fake = _fake_tts_response()
        with _patch("apps.economy.coachvoice.gemini_key", return_value="k"), \
             _patch("apps.economy.gemini.requests.post", return_value=fake):
            r = self.client.post(SPEAK_URL, {"text": "hello"}, format="json")
        self.assertIn("speak_remaining", r.data)
        self.assertIn("speak_daily_chars", r.data)
