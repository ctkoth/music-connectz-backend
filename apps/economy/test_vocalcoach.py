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
        # `text` is what a real requests.Response carries and what the error
        # path logs. The double didn't have it, so the first non-200 test hit
        # an AttributeError instead of the code being tested.
        text = '{"error": {"message": "fake upstream error"}}'
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

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_every_tier_can_have_a_take_scored(self, _post, _k):
        # This replaces a test that pinned the blueprint's StatZ gate. The gate
        # was removed on purpose, not by accident: the no-account trial door
        # already gives a stranger a full scored take once a day, so refusing a
        # paying Premium member had the ladder upside down.
        for tier in (TIER_FREE, TIER_PREMIUM, TIER_STATZ):
            with self.subTest(tier=tier):
                self._tier(tier)
                resp = self.client.post(URL, {"take": take()}, format="multipart")
                self.assertEqual(resp.status_code, 200, resp.data)
                self.assertEqual(resp.data["score"], GOOD["score"])

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

    def test_a_free_member_is_not_gated_out(self):
        m = membership_for(self.user); m.tier = TIER_FREE; m.save(update_fields=["tier", "updated_at"])
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(resp.data["gated"])
        self.assertIsNone(resp.data["required_tier"])
        # One free take a day, same as the anonymous trial door gives — so
        # signing up keeps what hooked them instead of taking it away.
        self.assertEqual(resp.data["daily_allowance"], PROMPT_ALLOWANCE[TIER_FREE])

    def test_the_upsell_is_frequency_and_it_is_stated(self):
        # The tier still sells something; it sells how OFTEN, and says so on the
        # screen rather than by refusing at the end.
        ladder = self.client.get(URL).data["allowance_ladder"]
        self.assertEqual([r["daily"] for r in ladder],
                         [PROMPT_ALLOWANCE[t] for t in (TIER_FREE, TIER_PREMIUM, TIER_STATZ)])
        self.assertEqual(sorted(r["daily"] for r in ladder), [r["daily"] for r in ladder])


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
    def test_a_rap_take_is_billed_the_same_way(self, _post, _k):
        # Was "gated and billed the same way" — RapZ proved it matched SingZ by
        # sharing its StatZ refusal. The gate is gone, so it proves the same
        # point the way that still holds: a Free member gets the take, and the
        # day's free prompt covers it before any balance is touched.
        m = membership_for(self.user); m.tier = TIER_FREE; m.save(update_fields=["tier", "updated_at"])
        w = wallet_for(self.user); w.money_cents = 0; w.promptz = 0
        w.save(update_fields=["money_cents", "promptz"])
        resp = self.client.post("/api/rapz/coach/", {"take": take()}, format="multipart")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["cost_cents"], 0)
        self.assertEqual(daily_prompt_state(self.user)[2], PROMPT_ALLOWANCE[TIER_FREE] - 1)


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


class VideoTakesTests(TestCase):
    """The coach watches as well as listens.

    Video has always been accepted server-side — the model marks delivery,
    posture and breath from it, which sound alone can't show. The refusal copy
    said "isn't audio" and the file picker was `accept="audio/*"`, so a feature
    the backend supported was unreachable from the app.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("v", "v@e.com", "pw12345678")
        self.client.force_authenticate(self.user)
        m = membership_for(self.user); m.tier = TIER_STATZ; m.save()
        w = wallet_for(self.user); w.money_cents = 100000; w.save()

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_a_video_take_is_scored_like_an_audio_one(self, _post, _k):
        resp = self.client.post(
            URL, {"take": take("take.mp4", "video/mp4"), "genre": "Rap"}, format="multipart")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["score"], GOOD["score"])

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_the_video_goes_up_with_its_own_mime_type(self, post, _k):
        # Sent as-is, not relabelled as audio — the model needs to know it can
        # look at the picture.
        self.client.post(URL, {"take": take("t.webm", "video/webm")}, format="multipart")
        parts = post.call_args.kwargs["json"]["contents"][0]["parts"]
        inline = [p for p in parts if "inline_data" in p][0]["inline_data"]
        self.assertEqual(inline["mime_type"], "video/webm")

    def test_the_refusal_names_both_kinds(self):
        resp = self.client.post(URL, {"take": take("notes.txt", "text/plain")}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        # It used to say "isn't audio" while accepting video — copy that
        # contradicts the check is how the picker ended up audio-only.
        self.assertIn("video", resp.data["detail"].lower())


class TheSizeCapIsOneWeCanHonourTests(TestCase):
    """A limit the app states has to be a limit the app can actually serve.

    The take rides to Gemini as base64 inside the request body, and that path
    caps the whole request at 20MB. Base64 inflates by 4/3, so a file cap above
    ~15MB is a promise the upstream breaks — and it broke it as "The coach
    couldn't process that take", which blames the take rather than the size.
    """

    GEMINI_INLINE_LIMIT_MB = 20

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("s", "s@e.com", "pw12345678")
        self.client.force_authenticate(self.user)
        m = membership_for(self.user); m.tier = TIER_STATZ; m.save()
        w = wallet_for(self.user); w.money_cents = 100000; w.save()

    def test_a_take_at_the_cap_still_fits_the_request(self):
        from apps.economy.vocalcoach import MAX_MB
        self.assertLess(MAX_MB * 4 / 3, self.GEMINI_INLINE_LIMIT_MB,
                        f"{MAX_MB}MB base64-encodes to "
                        f"{MAX_MB * 4 / 3:.1f}MB and the inline path caps at "
                        f"{self.GEMINI_INLINE_LIMIT_MB}MB — the app is advertising "
                        "a size it cannot send")

    def test_the_trial_cap_fits_too(self):
        from apps.economy.models import TRIAL_MAX_MB
        self.assertLess(TRIAL_MAX_MB * 4 / 3, self.GEMINI_INLINE_LIMIT_MB)

    def test_the_cap_is_published_so_the_client_can_stop_it_early(self):
        # The client checks against this before uploading, so an oversize take
        # is refused in the browser rather than after a slow upload.
        from apps.economy.vocalcoach import MAX_MB
        with patch("apps.economy.vocalcoach._key", return_value="test-key"):
            self.assertEqual(self.client.get(URL).data["max_mb"], MAX_MB)

    def test_over_the_cap_is_refused_before_any_model_run(self):
        from apps.economy.vocalcoach import MAX_MB
        big = SimpleUploadedFile(
            "long.webm", b"0" * int((MAX_MB + 1) * 1024 * 1024), content_type="video/webm")
        with patch("apps.economy.vocalcoach.requests.post") as post:
            resp = self.client.post(URL, {"take": big}, format="multipart")
        self.assertEqual(resp.status_code, 413)
        post.assert_not_called()


class TheContainerTheBrowserActuallyRecordsTests(TestCase):
    """The bug behind "The coach couldn't process that take."

    A real 1:07 RapZ take failed on a perfectly good performance. Two things
    were wrong and both were in the mime type:

    * `MediaRecorder.mimeType` is a full media type — Chrome hands back
      `audio/webm;codecs=opus`. That parameter rode all the way to Gemini's
      `mime_type` field, which takes a bare type, and the request was refused.
    * `audio/webm` is not on Gemini's audio list at all. `video/webm` is —
      same container, different label — so a browser-recorded take was
      unscoreable on Chrome, Edge and Android.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("m", "m@e.com", "pw12345678")
        self.client.force_authenticate(self.user)
        m = membership_for(self.user); m.tier = TIER_STATZ; m.save()
        w = wallet_for(self.user); w.money_cents = 100000; w.save()

    def test_codec_parameters_are_stripped(self):
        from apps.economy.vocalcoach import gemini_mime
        # The exact string Chrome produces.
        self.assertEqual(gemini_mime("audio/webm;codecs=opus"), "video/webm")
        self.assertEqual(gemini_mime("video/webm;codecs=vp8,opus"), "video/webm")
        self.assertEqual(gemini_mime("audio/ogg; codecs=opus"), "audio/ogg")

    def test_the_containers_browsers_record_are_all_accepted(self):
        from apps.economy.vocalcoach import gemini_mime
        for browser_type in ("audio/webm;codecs=opus",    # Chrome, Edge, Android
                             "audio/mp4",                  # Safari, iOS
                             "audio/ogg;codecs=opus",      # Firefox
                             "video/webm;codecs=vp8,opus",
                             "video/mp4"):
            with self.subTest(browser_type):
                self.assertIsNotNone(gemini_mime(browser_type),
                                     f"{browser_type} is a container a browser records into")

    def test_something_genuinely_unreadable_is_refused_and_explained(self):
        from apps.economy.vocalcoach import gemini_mime
        self.assertIsNone(gemini_mime("audio/x-weird"))
        self.assertIsNone(gemini_mime(""))

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    @patch("apps.economy.vocalcoach.requests.post", return_value=fake_gemini())
    def test_a_chrome_recording_reaches_gemini_with_a_type_it_takes(self, post, _k):
        resp = self.client.post(
            URL, {"take": take("take.webm", "audio/webm;codecs=opus")}, format="multipart")
        self.assertEqual(resp.status_code, 200, resp.data)
        parts = post.call_args.kwargs["json"]["contents"][0]["parts"]
        sent = [p for p in parts if "inline_data" in p][0]["inline_data"]["mime_type"]
        self.assertEqual(sent, "video/webm")
        self.assertNotIn(";", sent)

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    def test_an_unreadable_container_never_reaches_the_model(self, _k):
        # Refused here, instantly, and named — rather than a round trip that
        # comes back as a generic failure the member reads as "my take was bad".
        with patch("apps.economy.vocalcoach.requests.post") as post:
            resp = self.client.post(
                URL, {"take": take("take.xyz", "audio/x-weird")}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("x-weird", resp.data["detail"])
        post.assert_not_called()

    @patch("apps.economy.vocalcoach._key", return_value="test-key")
    def test_an_unreadable_container_is_not_billed(self, _k):
        before = daily_prompt_state(self.user)[2]
        with patch("apps.economy.vocalcoach.requests.post"):
            self.client.post(URL, {"take": take("t.xyz", "audio/x-weird")}, format="multipart")
        self.assertEqual(daily_prompt_state(self.user)[2], before)


class TheFailureSaysWhichFailureItWasTests(TestCase):
    """One sentence for four different problems is not an error message.

    "The coach couldn't process that take" was returned for a refused API key,
    a retired model, a spent quota and an unreadable container alike — none of
    them the member's fault, all of them reading like the take was bad. It also
    left me guessing from a screenshot.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("d", "d@e.com", "pw12345678")
        self.client.force_authenticate(self.user)
        m = membership_for(self.user); m.tier = TIER_STATZ; m.save()
        w = wallet_for(self.user); w.money_cents = 100000; w.save()

    def send(self, status_code):
        with patch("apps.economy.vocalcoach._key", return_value="k"), \
             patch("apps.economy.vocalcoach.requests.post",
                   return_value=fake_gemini(status_code=status_code)):
            return self.client.post(URL, {"take": take()}, format="multipart")

    def test_each_upstream_status_gets_its_own_reason(self):
        for code, phrase in ((400, "format"), (403, "key"),
                             (404, "model"), (429, "limit")):
            with self.subTest(code=code):
                resp = self.send(code)
                self.assertEqual(resp.status_code, 502)
                self.assertIn(phrase, resp.data["detail"].lower())

    def test_the_status_and_what_we_sent_come_back_for_diagnosis(self):
        resp = self.send(429)
        self.assertEqual(resp.data["upstream_status"], 429)
        self.assertEqual(resp.data["sent_mime"], "video/webm")
        self.assertIn("model", resp.data)

    def test_a_server_side_wobble_does_not_blame_the_take(self):
        self.assertIn("moment", self.send(503).data["detail"].lower())

    def test_the_upstream_body_is_never_forwarded(self):
        # It is a third party's error text and not ours to put in front of a
        # member — the status plus our own reading of it is the useful part.
        resp = self.send(400)
        self.assertNotIn("candidates", str(resp.data))

    def test_a_failed_take_is_still_not_billed(self):
        before = daily_prompt_state(self.user)[2]
        self.send(429)
        self.assertEqual(daily_prompt_state(self.user)[2], before)


class CoachVoiceTests(TestCase):
    """The coach talks like the app, and the voice never buys off the score.

    Corey's ask: RapZ and SingZ feedback in the paradigm the InstrumentZ lab
    already speaks — emoji-led, second person, top-two-and-a-drill. The risk
    that comes with it is the reason these assertions exist: a warm voice is
    one step from flattery, and a 3/10 with a 🔥 on it costs somebody a month
    of practising the wrong thing.
    """

    def test_both_coaches_are_asked_for_the_voice(self):
        from apps.economy.instruments import prompt_for
        for app_key in ("rapz", "singz"):
            p = prompt_for(app_key, "Trap", "tenor", "builder")
            self.assertIn("Music ConnectZ voice", p, app_key)
            self.assertIn("Contractions", p, app_key)
            self.assertIn("emoji", p.lower(), app_key)
            self.assertIn("second person", p, app_key)

    def test_the_voice_never_softens_the_score(self):
        # The guard that makes the emoji safe to ask for at all.
        from apps.economy.instruments import prompt_for
        for app_key in ("rapz", "singz", "drumz"):
            p = prompt_for(app_key, "Trap", "tenor", "builder")
            self.assertIn("never soften", p, app_key)
            self.assertIn("no flattery", p, app_key)

    def test_it_still_refuses_to_invent_what_it_could_not_hear(self):
        # Substance before the game layer: a livelier voice must not become a
        # licence to describe detail the model never heard.
        from apps.economy.instruments import prompt_for
        p = prompt_for("rapz", "Trap", None, "builder")
        self.assertIn("Never invent detail you cannot hear", p)
        self.assertIn("don't score it", p)

    def test_each_coach_still_speaks_its_own_dimensions(self):
        # A rapper isn't scored on breath support the way a singer is, and the
        # voice change must not have flattened the profiles into one coach.
        from apps.economy.instruments import prompt_for
        rap = prompt_for("rapz", "Trap", None, "builder")
        sing = prompt_for("singz", "R&B", "tenor", "builder")
        self.assertIn("rap coach", rap)
        self.assertIn('"flow"', rap)
        self.assertNotIn('"agility"', rap)
        self.assertIn("vocal coach", sing)
        self.assertIn('"agility"', sing)
        self.assertNotIn('"flow"', sing)
        # Only the singer gets asked about a target range.
        self.assertIn("Target range", sing)
        self.assertNotIn("Target range", rap)
