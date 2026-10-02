from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.omviardz import tour as spec
from apps.omviardz.models import TourProgress
from apps.omviardz.voice import SOURCE_BUILTIN, SOURCE_LLM, builtin_reply, explain
from apps.omviardz.wellknown import assetlinks_payload

User = get_user_model()


class TourSpecTests(TestCase):
    """The spec is data, so guard the invariants the client renders against."""

    def test_every_track_is_walkable_end_to_end(self):
        for track, keys in spec.TRACKS.items():
            self.assertTrue(keys, track)
            for key in keys:
                self.assertIsNotNone(spec.get_step(key), f"{track} -> missing step {key}")
            # walking with next_step_key visits the track in order and stops
            walked, cur = [], keys[0]
            while cur:
                walked.append(cur)
                cur = spec.next_step_key(track, cur)
            self.assertEqual(walked, keys, track)

    def test_every_step_is_reachable_from_some_track(self):
        reachable = {k for keys in spec.TRACKS.values() for k in keys}
        self.assertEqual(set(spec.STEPS), reachable)

    def test_every_option_has_a_reply_key_and_an_offline_answer(self):
        for key, step in spec.STEPS.items():
            self.assertTrue(step.get("options"), key)
            seen = set()
            for opt in step["options"]:
                self.assertNotIn(opt["key"], seen, f"{key}: duplicate reply key {opt['key']}")
                seen.add(opt["key"])
                self.assertEqual(len(opt["key"]), 1, f"{key}: reply must be one character")
                self.assertTrue(opt.get("label"), key)
                # The written explanation is what a member with no LLM key reads.
                self.assertTrue(opt.get("explain", "").strip(), f"{key}/{opt['key']}: no explain")

    def test_options_that_jump_point_at_real_steps(self):
        for key, step in spec.STEPS.items():
            for opt in step["options"]:
                if opt.get("goto"):
                    self.assertIsNotNone(spec.get_step(opt["goto"]), f"{key} -> {opt['goto']}")
                if opt.get("sets_track"):
                    self.assertIn(opt["sets_track"], spec.TRACKS, key)

    def test_highlights_name_a_target_and_a_label(self):
        marks = [s["highlight"] for s in spec.STEPS.values()]
        marks += [o["highlight"] for s in spec.STEPS.values()
                  for o in s["options"] if o.get("highlight")]
        for mark in marks:
            self.assertTrue(mark["target"].startswith("["), mark)
            self.assertTrue(mark["label"])
            self.assertIn(mark["shape"], ("rect", "circle", "pill"))
            self.assertIn(mark["placement"], ("below", "above", "over"))

    def test_step_one_branches_into_every_track(self):
        offered = {o["sets_track"] for o in spec.STEPS["welcome"]["options"] if o.get("sets_track")}
        self.assertEqual(offered, set(spec.TRACKS))

    def test_option_lookup_accepts_a_char_a_hash_or_the_label(self):
        opt = spec.get_option("welcome", "1")
        self.assertEqual(spec.get_option("welcome", "#1"), opt)
        self.assertEqual(spec.get_option("welcome", " #1 "), opt)
        self.assertEqual(spec.get_option("welcome", opt["label"]), opt)
        self.assertIsNone(spec.get_option("welcome", "9"))
        self.assertIsNone(spec.get_option("welcome", ""))

    def test_mobile_design_tokens_are_phone_sized(self):
        d = spec.DESIGN
        self.assertEqual(d["viewport"], "mobile-first")
        self.assertEqual(d["card"]["placement"], "bottom-sheet")
        self.assertTrue(d["card"]["safe_area_inset"])
        # 48dp is the Android minimum touch target; 16px the minimum body size
        # that doesn't trigger iOS zoom-on-focus.
        self.assertGreaterEqual(d["options"]["min_tap_target"], 48)
        self.assertGreaterEqual(d["typography"]["min_body"], 16)
        self.assertTrue(d["motion"]["respect_reduced_motion"])

    def test_facts_come_from_the_live_economy_catalog(self):
        from apps.economy.catalog import TIER_LIMITS
        from apps.economy.models import TIER_FREE, TIER_STATZ

        facts = spec.tier_facts()
        self.assertEqual(
            facts["tiers"][TIER_FREE]["char_limit"], TIER_LIMITS[TIER_FREE]["char_limit"]
        )
        # StatZ writes without a cap, so the tour must not print the sentinel.
        self.assertIsNone(facts["tiers"][TIER_STATZ]["char_limit"])
        self.assertTrue(facts["tiers"][TIER_STATZ]["char_limit_unlimited"])


class TourEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("member", "m@e.com", "pw12345678")

    def test_anyone_can_read_the_tour_with_the_written_answers(self):
        resp = self.client.get("/api/omviardz/tour/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["track"], spec.TRACK_DEFAULT)
        self.assertIsNone(resp.data["progress"])
        self.assertEqual(resp.data["design"]["viewport"], "mobile-first")
        first = resp.data["steps"][0]
        self.assertEqual(first["key"], "welcome")
        self.assertEqual(first["index"], 1)
        # explanations ship with the payload so an offline client still teaches
        self.assertTrue(all(o["explain"] for o in first["options"]))
        self.assertEqual(first["options"][0]["reply"], "#1")

    def test_track_query_previews_another_route(self):
        resp = self.client.get("/api/omviardz/tour/?track=money")
        self.assertEqual(resp.data["track"], "money")
        self.assertIn("royaltiez", [s["key"] for s in resp.data["steps"]])
        # unknown track falls back rather than 400ing the app's first screen
        self.assertEqual(self.client.get("/api/omviardz/tour/?track=nope").data["track"],
                         spec.TRACK_DEFAULT)

    def test_step_deep_link(self):
        resp = self.client.get("/api/omviardz/step/walletz/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["step"]["screen"], "walletz")
        self.assertEqual(self.client.get("/api/omviardz/step/nope/").status_code, 404)

    def test_answering_needs_a_login(self):
        resp = self.client.post("/api/omviardz/answer/", {"step": "welcome", "choice": "1"},
                                format="json")
        self.assertEqual(resp.status_code, 401)


class AnswerFlowTests(TestCase):
    """The guided part: an answer highlights a control, explains it, advances."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("member", "m@e.com", "pw12345678")
        self.client.force_authenticate(self.user)

    def _answer(self, step, choice=None, text=None, **extra):
        body = {"step": step}
        if choice is not None:
            body["choice"] = choice
        if text is not None:
            body["text"] = text
        body.update(extra)
        return self.client.post("/api/omviardz/answer/", body, format="json")

    def test_an_answer_highlights_that_option_and_advances(self):
        resp = self._answer("profilez", "2")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["highlight"]["label"], "Birthday")
        self.assertIn("birthday", resp.data["explain"]["text"].lower())
        self.assertEqual(resp.data["explain"]["cost_cents"], 0)
        self.assertEqual(resp.data["next"]["key"],
                         spec.next_step_key(spec.TRACK_DEFAULT, "profilez"))
        self.assertEqual(resp.data["progress"]["step"], resp.data["next"]["key"])

    def test_step_one_picks_the_track_and_the_route_follows(self):
        resp = self._answer("welcome", "3")
        self.assertEqual(resp.data["progress"]["track"], spec.TRACK_MONEY)
        # next step is the money route's second stop, not the default track's
        self.assertEqual(resp.data["next"]["key"], spec.TRACKS[spec.TRACK_MONEY][1])
        self.assertEqual(resp.data["progress"]["total"], len(spec.TRACKS[spec.TRACK_MONEY]))
        tour = self.client.get("/api/omviardz/tour/").data
        self.assertEqual(tour["track"], spec.TRACK_MONEY)
        self.assertEqual(tour["resume"], resp.data["next"]["key"])

    def test_the_answer_is_remembered(self):
        self._answer("welcome", "4")
        prog = TourProgress.objects.get(user=self.user)
        self.assertEqual(prog.answers["welcome"]["choice"], "4")
        self.assertIn("Learn", prog.answers["welcome"]["label"])
        self.assertEqual(prog.track, spec.TRACK_LEARN)

    def test_typing_a_question_answers_without_advancing(self):
        resp = self._answer("walletz", text="do I have to add money to use this?")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.data["choice"])
        self.assertIsNone(resp.data["next"])
        # still on the step, and the step's own control stays lit
        self.assertEqual(resp.data["progress"]["step"], spec.first_step())
        self.assertEqual(resp.data["highlight"]["label"], "Balance")
        self.assertNotIn("walletz", resp.data["progress"]["done"])

    def test_an_option_that_jumps_skips_ahead(self):
        # "not interested" on the earn step jumps past royalties to tiers
        resp = self._answer("earnz", "3")
        self.assertEqual(resp.data["next"]["key"], "tierz")

    def test_a_bad_choice_says_what_the_options_are(self):
        resp = self._answer("welcome", "9")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["options"], ["#1", "#2", "#3", "#4"])

    def test_empty_input_is_refused(self):
        self.assertEqual(self._answer("welcome").status_code, 400)
        self.assertEqual(self._answer("welcome", text="   ").status_code, 400)

    def test_unknown_step_is_404(self):
        self.assertEqual(self._answer("nope", "1").status_code, 404)

    def test_the_last_step_completes_the_tour(self):
        last = spec.TRACKS[spec.TRACK_DEFAULT][-1]
        resp = self._answer(last, "3")
        self.assertTrue(resp.data["progress"]["completed"])
        self.assertIsNone(resp.data["next"])

    def test_progress_counts_against_the_current_track(self):
        self._answer("welcome", "1")           # make track
        self._answer("profilez", "1")
        self._answer("welcome", "3")           # switch to money mid-tour
        prog = self.client.get("/api/omviardz/tour/").data["progress"]
        money = spec.TRACKS[spec.TRACK_MONEY]
        self.assertEqual(prog["total"], len(money))
        # personaz/occ answers from the old track don't inflate the bar
        self.assertLessEqual(prog["done_count"], prog["total"])
        self.assertEqual(prog["done_count"], len([k for k in prog["done"] if k in money]))

    def test_skip_is_remembered_and_reset_starts_over(self):
        self._answer("welcome", "2")
        self.assertTrue(self.client.post("/api/omviardz/skip/").data["skipped"])
        resp = self.client.post("/api/omviardz/reset/")
        self.assertEqual(resp.data["resume"], spec.first_step())
        self.assertEqual(resp.data["progress"]["track"], spec.TRACK_DEFAULT)
        self.assertEqual(resp.data["progress"]["done"], [])
        self.assertFalse(resp.data["progress"]["skipped"])


class VoiceTests(TestCase):
    """Corey speaks live when the key is there, and in writing when it isn't."""

    def test_builtin_reply_uses_the_written_answer_and_names_the_control(self):
        step = spec.get_step("profilez")
        opt = spec.get_option("profilez", "1")
        out = builtin_reply(step, opt)
        self.assertIn(opt["explain"][:40], out)
        self.assertIn("Avatar", out)

    def test_builtin_reply_hands_free_text_back_to_the_options(self):
        step = spec.get_step("tierz")
        out = builtin_reply(step, None, text="which one is worth it for a beatmaker")
        self.assertIn("beatmaker", out)
        for opt in step["options"]:
            self.assertIn(f"#{opt['key']}", out)

    def test_explain_falls_back_when_the_llm_is_unavailable(self):
        step, opt = spec.get_step("occ"), spec.get_option("occ", "1")
        with patch("apps.economy.occ._create_with_fallback", side_effect=RuntimeError("no key")):
            text, source = explain(step, opt, track=spec.TRACK_MAKE, facts=spec.tier_facts())
        self.assertEqual(source, SOURCE_BUILTIN)
        self.assertIn("Corey GPT", text)

    def test_explain_uses_corey_when_the_llm_answers(self):
        step, opt = spec.get_step("occ"), spec.get_option("occ", "1")

        class _Block:
            type, text = "text", "🗣️ Three voices, and I'm the cheap one. 🔥"

        class _Resp:
            content = [_Block()]

        with patch("apps.economy.occ._create_with_fallback", return_value=_Resp()) as call, \
                patch("anthropic.Anthropic"):
            text, source = explain(step, opt, text="which voice for a contract?",
                                   track=spec.TRACK_MAKE, facts=spec.tier_facts())
        self.assertEqual(source, SOURCE_LLM)
        self.assertIn("cheap one", text)
        system = call.call_args.kwargs["system"]
        # the model is told exactly what is highlighted, and given real numbers
        self.assertIn("HIGHLIGHTED OPTION", system)
        self.assertIn("Voice picker", system)
        self.assertIn("TRUE PLATFORM NUMBERS", system)
        self.assertIn("OMVIARDZ", system)

    def test_the_answer_endpoint_reports_which_voice_answered(self):
        client = APIClient()
        client.force_authenticate(User.objects.create_user("v", "v@e.com", "pw12345678"))
        with patch("apps.omviardz.views.explain", return_value=("hey", SOURCE_LLM)):
            data = client.post("/api/omviardz/answer/", {"step": "welcome", "choice": "1"},
                               format="json").data
        self.assertEqual(data["explain"]["source"], SOURCE_LLM)
        self.assertEqual(data["explain"]["cost_cents"], 0)


class AssetLinksTests(TestCase):
    """TWA link verification — the app is only chrome-less if this validates."""

    def test_empty_until_a_fingerprint_is_configured(self):
        with self.settings():
            self.assertEqual(assetlinks_payload(fingerprints=[]), [])
        resp = self.client.get("/.well-known/assetlinks.json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/json")

    def test_payload_shape_google_expects(self):
        payload = assetlinks_payload("net.musicconnectz.app", ["AA:BB", "CC:DD"])
        self.assertEqual(payload[0]["target"]["namespace"], "android_app")
        self.assertEqual(payload[0]["target"]["package_name"], "net.musicconnectz.app")
        self.assertEqual(payload[0]["target"]["sha256_cert_fingerprints"], ["AA:BB", "CC:DD"])
        self.assertIn("delegate_permission/common.handle_all_urls", payload[0]["relation"])
