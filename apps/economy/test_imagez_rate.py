import base64, json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.economy import imagez_rate as M
from apps.economy.models import Transaction

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()


class FakeResp:
    status_code = 200
    def __init__(self, t): self.t = t
    def json(self): return {"candidates": [{"content": {"parts": [{"text": self.t}]}}]}


class CleanTests(TestCase):
    def test_overall_is_the_servers_mean_and_unknown_keys_drop(self):
        got = M.clean({"scores": {"composition": {"score": 8, "why": "w", "how": "h"}, "light": {"score": 6, "why": "w"},
                                  "attractiveness": {"score": 10, "why": "pretty"}}, "verdict": "ok"})
        self.assertEqual(got["overall"], 7.0)
        self.assertNotIn("attractiveness", got["scores"])

    def test_the_prompt_forbids_rating_looks(self):
        self.assertIn("NEVER comment on or score how attractive", M.prompt())
        self.assertNotIn("attractive", " ".join(d["label"] for d in M.DIMENSIONS.values()).lower())

    def test_nothing_scored_is_no_answer(self):
        self.assertIsNone(M.clean({"scores": {"light": {"score": None, "why": ""}}}))


@override_settings(GEMINI_API_KEY="k")
class ViewTests(TestCase):
    def setUp(self):
        self.u = get_user_model().objects.create_user("artist", password="pw-long-enough-1")
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def test_price_is_stated_before(self):
        d = self.c.get("/api/economy/imagez/rate/").data
        self.assertIn("cost_cents", d["price"]); self.assertEqual(len(d["dimensions"]), 6)

    def test_a_score_is_charged_once_and_an_unreadable_one_never(self):
        good = json.dumps({"scores": {"composition": {"score": 7, "why": "w", "how": "h"}}, "verdict": "v", "next": "n"})
        with mock.patch.object(M, "generate_content", return_value=(FakeResp(good), ["m"])):
            r = self.c.post("/api/economy/imagez/rate/", {"image": PNG}, format="json")
        self.assertEqual(r.status_code, 200, r.data); self.assertEqual(r.data["overall"], 7.0)
        with mock.patch.object(M, "generate_content", return_value=(FakeResp("nope"), ["m"])):
            r = self.c.post("/api/economy/imagez/rate/", {"image": PNG}, format="json")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(Transaction.objects.filter(user=self.u, note__startswith="ImageZ score").count(), 1)


class ProfilePhotoTests(TestCase):
    """A profile photo is judged as a PHOTO — framing, light, background, focus, colour — never the person, with no overall."""

    def test_the_dimensions_are_about_the_photograph_and_none_is_about_the_person(self):
        from apps.economy.imagez_rate import PROFILE_DIMENSIONS
        self.assertEqual(set(PROFILE_DIMENSIONS), {"framing", "light", "background", "sharpness", "color"})
        for bad in ("face", "attract", "body", "skin", "expression", "weight", "age"):
            self.assertFalse(any(bad in (k + d["what"]).lower() and "age" != bad for k, d in PROFILE_DIMENSIONS.items()), bad)

    def test_the_profile_prompt_forbids_judging_the_person(self):
        from apps.economy.imagez_rate import prompt
        p = prompt("profile").lower()
        for needle in ("never the person", "attractiveness", "expression", "age"):
            self.assertIn(needle, p)

    def test_there_is_no_overall_number_and_the_caveat_says_so(self):
        from apps.economy.imagez_rate import clean
        raw = {"scores": {"framing": {"score": 8, "why": "Centred", "how": "Crop tighter"},
                          "light": {"score": 6, "why": "Flat", "how": "Face the window"},
                          "face": {"score": 9, "why": "x", "how": "y"}}, "verdict": "Clear", "next": "Crop"}
        got = clean(raw, "profile")
        self.assertIsNone(got["overall"])
        self.assertEqual(set(got["scores"]), {"framing", "light"})     # an undeclared key (face) is dropped
        self.assertEqual(got["purpose"], "profile")
        self.assertIn("nothing about you", got["caveat"])

    def test_a_normal_picture_still_gets_its_overall(self):
        from apps.economy.imagez_rate import clean
        got = clean({"scores": {"composition": {"score": 8, "why": "a", "how": "b"}}}, "")
        self.assertEqual(got["overall"], 8.0)
        self.assertNotIn("purpose", got)
