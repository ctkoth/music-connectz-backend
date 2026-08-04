import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from django.utils import timezone

from apps.economy.catalog import ai_cost
from apps.economy.models import (PROMPT_ALLOWANCE, TIER_FREE, TIER_PREMIUM,
                                 TIER_STATZ, daily_prompt_state,
                                 membership_for, wallet_for)

User = get_user_model()
URL = "/api/singz/coach/"

GOOD = {"score": 7, "scores": {"pitch": 8, "tone": 7, "breath": 5, "range": 6, "agility": 7},
        "verdict": "A solid builder take that runs out of air in the last phrase.",
        "strengths": ["The first eight bars sit dead centre of pitch."],
        "fixes": ["You're breathing at the bar line — take it a beat earlier."],
        "next_drill": "Sustained 4-count exhale on an ee vowel."}


def fake_gemini(payload=GOOD, status_code=200):
    class R:
        status_code = 200
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}
    R.status_code = status_code
    return R()


def take(name="take.webm", ct="audio/webm", size=1000):
    return SimpleUploadedFile(name, b"0" * size, content_type=ct)


class SingZCoachTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.client.force_authenticate(self.user)
        m = membership_for(self.user); m.tier = TIER_STATZ; m.save()
        w = wallet_for(self.user); w.money_cents = 100000; w.save()

    def _tier(self, t):
        m = membership_for(self.user); m.tier = t; m.save(update_fields=["tier", "updated_at"])

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_a_take_comes_back_scored_and_coached(self, _post, _k):
        resp = self.client.post(URL, {"take": take(), "genre": "R&B",
                                      "range": "tenor", "difficulty": "builder"}, format="multipart")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["score"], 7)
        self.assertEqual(resp.data["scores"]["breath"], 5)
        self.assertIn("runs out of air", resp.data["verdict"])
        self.assertTrue(resp.data["fixes"])
        self.assertTrue(resp.data["next_drill"])

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_the_genre_and_range_reach_the_model(self, post, _k):
        self.client.post(URL, {"take": take(), "genre": "Drill", "range": "alto",
                               "difficulty": "stageboss"}, format="multipart")
        sent = post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
        self.assertIn("Drill", sent)
        self.assertIn("alto", sent)
        self.assertIn("stageboss", sent)

    def test_free_and_premium_are_refused_per_the_blueprint_gate(self):
        for tier in (TIER_FREE, TIER_PREMIUM):
            with self.subTest(tier=tier):
                self._tier(tier)
                resp = self.client.post(URL, {"take": take()}, format="multipart")
                self.assertEqual(resp.status_code, 403)
                self.assertEqual(resp.data["required_tier"], TIER_STATZ)

    def test_a_missing_or_non_audio_take_is_refused(self):
        self.assertEqual(self.client.post(URL, {}, format="multipart").status_code, 400)
        resp = self.client.post(URL, {"take": take("cv.pdf", "application/pdf")}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("isn't audio", resp.data["detail"])

    def test_an_oversized_take_is_refused(self):
        big = SimpleUploadedFile("long.webm", b"0" * (26 * 1024 * 1024), content_type="audio/webm")
        self.assertEqual(self.client.post(URL, {"take": big}, format="multipart").status_code, 413)

    @patch("apps.economy.vocalcoach._key", return_value="")
    def test_unconfigured_key_503s_cleanly(self, _k):
        resp = self.client.post(URL, {"take": take()}, format="multipart")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("GEMINI_API_KEY", resp.data["detail"])

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini({"nonsense": True}))
    @patch("apps.economy.vocalcoach._bill")
    def test_an_unusable_reply_is_not_billed(self, bill, _post, _k):
        """A take the coach couldn't read must not cost the member a prompt."""
        resp = self.client.post(URL, {"take": take()}, format="multipart")
        self.assertEqual(resp.status_code, 502)
        bill.assert_not_called()

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini({**GOOD, "score": 47}))
    def test_a_wild_score_is_clamped_to_ten(self, _post, _k):
        self.assertEqual(self.client.post(URL, {"take": take()}, format="multipart").data["score"], 10)


class CoachPriceTests(TestCase):
    """The cost has to be knowable before the member commits to paying it.

    A price that only appears in the response is a bill. GET answers what THIS
    member pays for THIS take right now.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.client.force_authenticate(self.user)
        m = membership_for(self.user); m.tier = TIER_STATZ; m.save()

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    def test_the_price_is_readable_before_sending_anything(self, _k):
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["cost_cents"], ai_cost("standard"))
        self.assertTrue(resp.data["allowed"])
        self.assertTrue(resp.data["configured"])

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    def test_it_says_a_free_daily_prompt_covers_the_take(self, _k):
        resp = self.client.get(URL)
        self.assertTrue(resp.data["free_today"])
        self.assertEqual(resp.data["daily_remaining"], PROMPT_ALLOWANCE[TIER_STATZ])

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    def test_it_says_a_failed_take_is_not_charged(self, _k):
        # Stated, not just implemented — _bill runs only after a usable parse.
        self.assertFalse(self.client.get(URL).data["charged_on_failure"])

    @patch("apps.economy.vocalcoach._key", return_value=None)
    def test_an_unconfigured_key_is_visible_up_front(self, _k):
        self.assertFalse(self.client.get(URL).data["configured"])

    def test_a_free_member_is_told_the_gate_without_uploading(self):
        m = membership_for(self.user); m.tier = TIER_FREE; m.save(update_fields=["tier", "updated_at"])
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(resp.data["allowed"])
        self.assertEqual(resp.data["required_tier"], TIER_STATZ)


class CoachDailyAllowanceTests(TestCase):
    """A coached take is a flat text-model run, so the tier's free daily
    prompts must cover it. _bill skipped the allowance entirely and went
    straight to PromptZ and cash — charging for something the member was told
    they already had."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.client.force_authenticate(self.user)
        m = membership_for(self.user); m.tier = TIER_STATZ; m.save()

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_a_take_spends_a_free_daily_prompt_before_any_balance(self, _post, _k):
        w = wallet_for(self.user); w.money_cents = 500; w.promptz = 50; w.save()
        before = daily_prompt_state(self.user)[2]
        resp = self.client.post(URL, {"take": take()}, format="multipart")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(daily_prompt_state(self.user)[2], before - 1)
        w.refresh_from_db()
        self.assertEqual(w.money_cents, 500, "cash was touched while a free prompt remained")
        self.assertEqual(w.promptz, 50, "PromptZ was spent while a free prompt remained")

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_once_the_allowance_is_gone_it_falls_back_to_promptz(self, _post, _k):
        w = wallet_for(self.user)
        w.money_cents = 500
        w.promptz = 50
        w.prompts_used_today = PROMPT_ALLOWANCE[TIER_STATZ]
        w.prompt_day = timezone.now().date()
        w.save()
        resp = self.client.post(URL, {"take": take()}, format="multipart")
        self.assertEqual(resp.status_code, 200, resp.content)
        w.refresh_from_db()
        self.assertEqual(w.promptz, 50 - ai_cost("standard"))
        self.assertEqual(w.money_cents, 500, "cash was spent while PromptZ remained")


class InstrumentCoachTests(TestCase):
    """A take is a take, but the dimensions are not transferable. Scoring a
    guitar take on "breath" would be a number with nothing behind it — the
    exact failure the Boss Take exists to avoid."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.client.force_authenticate(self.user)
        m = membership_for(self.user); m.tier = TIER_STATZ; m.save()

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    def test_rapz_has_its_own_coach_route(self, _k):
        resp = self.client.get("/api/rapz/coach/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["app_key"], "rapz")

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    def test_rap_is_not_scored_on_vocal_range(self, _k):
        scores = self.client.get("/api/rapz/coach/").data["scores"]
        self.assertIn("flow", scores)
        self.assertNotIn("range", scores)

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    def test_only_singing_offers_a_range_picker(self, _k):
        self.assertIsNotNone(self.client.get(URL).data["range_label"])
        self.assertIsNone(self.client.get("/api/rapz/coach/").data["range_label"])
        self.assertEqual(len(self.client.get(URL).data["ranges"]), 8)
        self.assertEqual(self.client.get("/api/rapz/coach/").data["ranges"], [])

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    def test_singz_still_scores_exactly_what_it_did(self, _k):
        scores = self.client.get(URL).data["scores"]
        self.assertEqual(set(scores), {"pitch", "tone", "breath", "range", "agility"})

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    def test_the_caveat_names_this_instruments_dimensions(self, _k):
        self.assertIn("Flow", self.client.get("/api/rapz/coach/").data["caveat"])
        self.assertIn("Pitch", self.client.get(URL).data["caveat"])

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post")
    def test_the_prompt_asks_for_this_instruments_dimensions(self, post, _k):
        post.return_value = fake_gemini({**GOOD, "scores": {"flow": 7, "timing": 8, "breath": 6,
                                                            "clarity": 7, "delivery": 9}})
        resp = self.client.post("/api/rapz/coach/", {"take": take()}, format="multipart")
        self.assertEqual(resp.status_code, 200, resp.content)
        sent = post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
        self.assertIn("rap coach", sent)
        self.assertIn('"flow"', sent)
        self.assertNotIn('"range"', sent)
        self.assertEqual(set(resp.data["scores"]), {"flow", "timing", "breath", "clarity", "delivery"})

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_a_rap_take_is_gated_and_billed_the_same_way(self, _post, _k):
        m = membership_for(self.user); m.tier = TIER_FREE; m.save(update_fields=["tier", "updated_at"])
        resp = self.client.post("/api/rapz/coach/", {"take": take()}, format="multipart")
        self.assertEqual(resp.status_code, 403, resp.content)


class FreePromptCoversTheTakeTests(TestCase):
    """Billing spends the free daily allowance first, so the affordability gate
    has to know that. It didn't — a StatZ member with prompts left and an empty
    wallet was refused a take that would have cost them nothing."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", "pw12345678")
        self.client.force_authenticate(self.user)
        m = membership_for(self.user); m.tier = TIER_STATZ; m.save()
        w = wallet_for(self.user); w.money_cents = 0; w.promptz = 0; w.save()

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_an_empty_wallet_still_gets_a_take_while_free_prompts_remain(self, _post, _k):
        resp = self.client.post(URL, {"take": take()}, format="multipart")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["cost_cents"], 0)

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_once_the_allowance_is_gone_an_empty_wallet_is_refused(self, _post, _k):
        from django.utils import timezone
        w = wallet_for(self.user)
        w.prompts_used_today = PROMPT_ALLOWANCE[TIER_STATZ]
        w.prompt_day = timezone.now().date()
        w.save()
        resp = self.client.post(URL, {"take": take()}, format="multipart")
        self.assertEqual(resp.status_code, 402, resp.content)
