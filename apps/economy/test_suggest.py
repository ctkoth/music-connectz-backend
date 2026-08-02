"""A suggestion says What / Why / How. All three, everywhere.

This existed in three places and two of them were wrong: OmviardZ asked for
"what to do and why" and dropped the How, and the OCC agent — the thing that
actually edits your code — had no suggestion mode at all. These tests pin the
rule to one definition so it can't drift again.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import TIER_FREE, TIER_PREMIUM, TIER_STATZ, membership_for
from .suggest import (PARTS, SUGGEST_STYLE, SUGGEST_STYLE_SHORT, gate,
                      may_suggest, payload)

User = get_user_model()


def member(name, tier=TIER_FREE):
    u = User.objects.create_user(username=name, password="suggest-pass-1")
    m = membership_for(u)
    m.tier = tier
    m.save(update_fields=["tier"])
    return u


class StyleTests(TestCase):
    def test_the_full_style_names_all_three_parts(self):
        for word in ("What", "Why", "How"):
            self.assertIn(word, SUGGEST_STYLE)

    def test_the_short_style_also_names_all_three(self):
        """The phone version is shorter, not weaker — this is where How was lost."""
        lowered = SUGGEST_STYLE_SHORT.lower()
        for word in ("what", "why", "how"):
            self.assertIn(word, lowered)

    def test_the_parts_list_matches_the_rule(self):
        self.assertEqual([p["key"] for p in PARTS], ["what", "why", "how"])
        for part in PARTS:
            self.assertTrue(part["blurb"].strip())

    def test_the_settings_payload_states_the_tier_honestly(self):
        self.assertEqual(payload()["requires_tier"], TIER_STATZ)


class GateTests(TestCase):
    def test_statz_gets_suggestions(self):
        self.assertTrue(may_suggest(member("statz_member", TIER_STATZ)))

    def test_free_and_premium_do_not(self):
        self.assertFalse(may_suggest(member("free_member", TIER_FREE)))
        self.assertFalse(may_suggest(member("prem_member", TIER_PREMIUM)))

    def test_not_asking_for_them_produces_no_notice(self):
        enabled, notice = gate(member("quiet", TIER_FREE), False)
        self.assertFalse(enabled)
        self.assertIsNone(notice)

    def test_asking_without_the_tier_explains_why_instead_of_failing(self):
        """A hard error would lose the answer they actually asked for; silence
        would look like the toggle is broken."""
        enabled, notice = gate(member("asker", TIER_FREE), True)
        self.assertFalse(enabled)
        self.assertIn("StatZ", notice)

    def test_asking_with_the_tier_just_works(self):
        enabled, notice = gate(member("asker_statz", TIER_STATZ), True)
        self.assertTrue(enabled)
        self.assertIsNone(notice)

    def test_an_anonymous_caller_never_gets_them(self):
        self.assertFalse(may_suggest(None))


class OneDefinitionTests(TestCase):
    def test_occ_chat_uses_the_shared_style(self):
        from .occ import SUGGEST_STYLE as occ_style
        self.assertIs(occ_style, SUGGEST_STYLE)

    def test_the_omviardz_tour_asks_for_all_three_parts(self):
        """Guards the exact drift that happened: the tour had its own wording
        and dropped the How. Asserts on the prompt actually sent, not on the
        source text — a comment mentioning the old wording is not a bug."""
        from unittest import mock

        from apps.omviardz import voice

        captured = {}

        def fake_create(client, model, fallback, **kwargs):
            captured["system"] = kwargs.get("system", "")
            raise RuntimeError("stop here — we only wanted the prompt")

        step = {"screen": "welcome", "title": "Welcome", "blurb": "Hi",
                "options": [{"key": "1", "label": "Start", "explain": "Tap it."}]}
        with mock.patch.dict("sys.modules", {"anthropic": mock.MagicMock()}), \
                mock.patch("apps.economy.occ._create_with_fallback", fake_create):
            voice.explain(step, step["options"][0], suggest=True)

        system = captured.get("system", "").lower()
        self.assertTrue(system, "the system prompt was never built")
        for word in ("what", "why", "how"):
            self.assertIn(word, system, f"the tour's suggestion prompt lost '{word}'")

    def test_the_tour_does_not_ask_for_suggestions_when_it_was_not_asked_to(self):
        from unittest import mock

        from apps.omviardz import voice

        captured = {}

        def fake_create(client, model, fallback, **kwargs):
            captured["system"] = kwargs.get("system", "")
            raise RuntimeError("stop here")

        step = {"screen": "welcome", "title": "Welcome", "blurb": "Hi", "options": []}
        with mock.patch.dict("sys.modules", {"anthropic": mock.MagicMock()}), \
                mock.patch("apps.economy.occ._create_with_fallback", fake_create):
            voice.explain(step, None, suggest=False)
        self.assertNotIn("💡 Suggestion", captured.get("system", ""))

    def test_the_agent_accepts_a_suggest_flag(self):
        import inspect

        from .occ_agent import run_agent
        self.assertIn("suggest", inspect.signature(run_agent).parameters)
