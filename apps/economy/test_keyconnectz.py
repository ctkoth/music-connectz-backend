"""KeyConnectZ — Premium buys the wallpaper, everybody gets to be understood.

The split is deliberate. The wallpaper is decoration: nobody loses a capability
by not having it, which is what makes it fair to sell. Translate is the thing
the keyboard is FOR, and charging a Free member to talk to somebody in another
language would price the app out of the rooms it exists to open.
"""
import io
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (
    KEY_TRANSLATE_DAILY_CHARS,
    KEY_TRANSLATE_MAX_CHARS,
    TIER_FREE,
    TIER_PREMIUM,
    TIER_STATZ,
    KeyTranslation,
    keyboard_skin_for,
    membership_for,
)

User = get_user_model()
PW = "hunter2hunter2"


def as_tier(user, tier):
    m = membership_for(user)
    m.tier = tier
    m.save(update_fields=["tier", "updated_at"])
    return user


def an_image(name="wall.png"):
    # A 1x1 PNG — enough for content-type and size checks.
    png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
           b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
           b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
    return SimpleUploadedFile(name, png, content_type="image/png")


class KeyboardStateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", PW)
        self.client.force_authenticate(self.user)

    def test_one_get_answers_everything_the_keyboard_needs(self):
        resp = self.client.get("/api/economy/keyz/")
        self.assertEqual(resp.status_code, 200, resp.content)
        for key in ("skin", "wallpaper_allowed", "wallpaper_required_tier",
                    "translate_free", "translate_remaining", "languages"):
            self.assertIn(key, resp.data)

    def test_the_price_of_each_half_is_stated_before_anyone_reaches_for_it(self):
        resp = self.client.get("/api/economy/keyz/")
        self.assertFalse(resp.data["wallpaper_allowed"])          # Free member
        self.assertEqual(resp.data["wallpaper_required_tier"], TIER_PREMIUM)
        self.assertTrue(resp.data["translate_free"])
        self.assertEqual(resp.data["translate_cost_cents"], 0)
        self.assertEqual(resp.data["translate_daily_chars"], KEY_TRANSLATE_DAILY_CHARS)

    def test_detect_is_offered_so_nobody_declares_what_they_are_typing(self):
        langs = {l["key"] for l in self.client.get("/api/economy/keyz/").data["languages"]}
        self.assertIn("auto", langs)
        self.assertGreater(len(langs), 30)

    def test_colours_are_free_at_every_tier(self):
        # Charging for a colour would be pricing the paint and giving away the wall.
        resp = self.client.patch("/api/economy/keyz/",
                                 {"accent": "#7c3aed", "key_opacity": 40, "dark_keys": False},
                                 format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["accent"], "#7c3aed")
        self.assertEqual(resp.data["key_opacity"], 40)
        self.assertFalse(resp.data["dark_keys"])

    def test_a_junk_colour_is_refused_not_stored(self):
        self.assertEqual(self.client.patch("/api/economy/keyz/",
                                           {"accent": "purple"}, format="json").status_code, 400)

    def test_opacity_is_clamped_not_rejected(self):
        self.assertEqual(self.client.patch("/api/economy/keyz/",
                                           {"key_opacity": 900}, format="json").data["key_opacity"], 100)

    def test_an_unknown_language_is_refused(self):
        self.assertEqual(self.client.patch("/api/economy/keyz/",
                                           {"target_lang": "klingon"}, format="json").status_code, 400)


class WallpaperTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", PW)
        self.client.force_authenticate(self.user)

    def upload(self, **kw):
        return self.client.post("/api/economy/keyz/", {"wallpaper": an_image(), **kw},
                                format="multipart")

    def test_a_free_member_is_refused_and_told_translate_is_still_free(self):
        resp = self.upload()
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.data["required_tier"], TIER_PREMIUM)
        self.assertIn("Translate stays free", resp.data["detail"])

    def test_premium_can_upload(self):
        as_tier(self.user, TIER_PREMIUM)
        resp = self.upload()
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(resp.data["wallpaper_url"])

    def test_statz_can_too(self):
        as_tier(self.user, TIER_STATZ)
        self.assertEqual(self.upload().status_code, 201)

    def test_a_non_image_is_refused(self):
        as_tier(self.user, TIER_PREMIUM)
        bad = SimpleUploadedFile("x.txt", b"hi", content_type="text/plain")
        resp = self.client.post("/api/economy/keyz/", {"wallpaper": bad}, format="multipart")
        self.assertEqual(resp.status_code, 400)

    def test_uploading_again_replaces_rather_than_accumulates(self):
        # Keeping the old file would silently eat the member's storage quota.
        as_tier(self.user, TIER_PREMIUM)
        self.upload()
        first = keyboard_skin_for(self.user).wallpaper.name
        self.upload()
        self.assertNotEqual(keyboard_skin_for(self.user).wallpaper.name, first)

    def test_a_lapsed_member_can_still_take_their_own_picture_off(self):
        as_tier(self.user, TIER_PREMIUM)
        self.upload()
        as_tier(self.user, TIER_FREE)
        resp = self.client.delete("/api/economy/keyz/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["wallpaper_url"], "")

    def test_the_get_flips_to_allowed_on_upgrade(self):
        self.assertFalse(self.client.get("/api/economy/keyz/").data["wallpaper_allowed"])
        as_tier(self.user, TIER_PREMIUM)
        self.assertTrue(self.client.get("/api/economy/keyz/").data["wallpaper_allowed"])


class FakeBlock:
    type = "text"
    def __init__(self, text): self.text = text


class FakeResp:
    def __init__(self, payload): self.content = [FakeBlock(json.dumps(payload))]


def fake_client(payload):
    class C:
        class messages:
            @staticmethod
            def create(**kw): return FakeResp(payload)
    return C


class TranslateTests(TestCase):
    """Any language to any language, free, at every tier."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", PW)
        self.client.force_authenticate(self.user)

    def translate(self, text="hello", target="es", **over):
        payload = {"text": text, "target_lang": target, **over}
        mod = __import__("apps.economy.keyconnectz", fromlist=["x"])
        fake = type("anthropic", (), {"Anthropic": fake_client({"text": "hola", "detected": "en"})})
        with patch.dict("sys.modules", {"anthropic": fake}):
            return self.client.post("/api/economy/keyz/translate/", payload, format="json")

    def test_a_free_member_can_translate(self):
        resp = self.translate()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["text"], "hola")
        self.assertEqual(resp.data["cost_cents"], 0)

    def test_it_reports_what_is_left_without_being_asked_again(self):
        resp = self.translate("hello")
        self.assertEqual(resp.data["translate_used_today"], 5)
        self.assertEqual(resp.data["translate_remaining"], KEY_TRANSLATE_DAILY_CHARS - 5)

    def test_the_source_can_be_named_or_detected(self):
        self.assertEqual(self.translate(source_lang="fr").status_code, 200)
        self.assertEqual(self.translate(source_lang="auto").status_code, 200)
        # Junk falls back to auto rather than refusing.
        self.assertEqual(self.translate(source_lang="zzz").status_code, 200)

    def test_any_pair_works_not_just_out_of_english(self):
        for pair in (("es", "ja"), ("ar", "pt"), ("zh", "sw")):
            resp = self.translate(source_lang=pair[0], target=pair[1])
            self.assertEqual(resp.status_code, 200, f"{pair}: {resp.content}")

    def test_a_missing_target_is_refused(self):
        self.assertEqual(self.translate(target="").status_code, 400)
        self.assertEqual(self.translate(target="auto").status_code, 400)

    def test_empty_text_is_refused_before_any_model_run(self):
        self.assertEqual(self.translate(text="   ").status_code, 400)
        self.assertFalse(KeyTranslation.objects.exists())

    def test_the_same_language_both_ways_is_a_free_no_op(self):
        # Charging the allowance for doing nothing would be taking something
        # for nothing.
        resp = self.translate(text="hola", source_lang="es", target="es")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(resp.data["translated"])
        self.assertFalse(KeyTranslation.objects.exists())

    def test_one_message_has_a_ceiling(self):
        resp = self.translate(text="x" * (KEY_TRANSLATE_MAX_CHARS + 1))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["max_chars"], KEY_TRANSLATE_MAX_CHARS)

    def test_the_daily_allowance_is_enforced_and_explained(self):
        KeyTranslation.objects.create(user=self.user, chars=KEY_TRANSLATE_DAILY_CHARS)
        resp = self.translate()
        self.assertEqual(resp.status_code, 429, resp.content)
        self.assertEqual(resp.data["translate_remaining"], 0)
        self.assertIn("resets", resp.data["detail"])

    def test_a_failed_run_does_not_eat_the_members_day(self):
        # Same rule as a Boss Take the coach couldn't read.
        broken = type("anthropic", (), {"Anthropic": fake_client({"nope": True})})
        with patch.dict("sys.modules", {"anthropic": broken}):
            resp = self.client.post("/api/economy/keyz/translate/",
                                    {"text": "hello", "target_lang": "es"}, format="json")
        self.assertEqual(resp.status_code, 503)
        self.assertFalse(KeyTranslation.objects.exists())

    def test_the_keyboard_remembers_the_pair(self):
        self.translate(source_lang="fr", target="ja")
        skin = keyboard_skin_for(self.user)
        self.assertEqual(skin.source_lang, "fr")
        self.assertEqual(skin.target_lang, "ja")

    def test_premium_gets_no_bigger_allowance_than_free(self):
        # The wallpaper is the upsell. Being understood is not.
        free_cap = self.client.get("/api/economy/keyz/").data["translate_daily_chars"]
        as_tier(self.user, TIER_STATZ)
        self.assertEqual(self.client.get("/api/economy/keyz/").data["translate_daily_chars"], free_cap)
