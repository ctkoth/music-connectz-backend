"""Gemini reads, Claude answers, and the member's tier caps which Claude (Corey, Nov 2026): Free picks Haiku or
Sonnet, Premium reaches Opus, StatZ reaches Fable. The SDK is stubbed — no key exists here."""
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import coach_think
from apps.economy.catalog import AI_MODELS, ai_models_for, default_ai_model
from apps.economy.crosspost import coach_price
from apps.economy.deadline import Deadline
from apps.economy.models import TIER_FREE, TIER_PREMIUM, TIER_STATZ, Membership, daily_prompt_covers, profile_for
from apps.economy.test_coach_think import GOOD, KEY, PAYLOAD, client_returning, resp

User = get_user_model()


def member(name, tier=TIER_FREE, pick=None):
    u = User.objects.create_user(name, password="pw12345!x")
    Membership.objects.update_or_create(user=u, defaults={"tier": tier})
    if pick:
        p = profile_for(u)
        p.ai_model = pick
        p.save()
    return u


class LadderTests(TestCase):
    def test_coreys_ladder(self):
        self.assertEqual(ai_models_for(TIER_FREE), ["haiku", "sonnet"])
        self.assertEqual(ai_models_for(TIER_PREMIUM), ["haiku", "sonnet", "opus"])
        self.assertEqual(ai_models_for(TIER_STATZ), ["haiku", "sonnet", "opus", "fable"])

    def test_a_member_who_never_chose_gets_the_best_engine_the_free_prompts_cover(self):
        self.assertEqual([default_ai_model(t) for t in (TIER_FREE, TIER_PREMIUM, TIER_STATZ)],
                         ["sonnet", "sonnet", "sonnet"])

    def test_the_current_generation_of_each(self):
        self.assertEqual({k: v["id"] for k, v in AI_MODELS.items()},
                         {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5",
                          "opus": "claude-opus-5-5", "fable": "claude-fable-5-2"})

    def test_list_prices_in_cents_per_million_tokens(self):
        self.assertEqual({k: (v["in_cents_mtok"], v["out_cents_mtok"]) for k, v in AI_MODELS.items()},
                         {"haiku": (10, 50), "sonnet": (200, 1000), "opus": (400, 2000), "fable": (800, 4000)})

    def test_a_short_haiku_call_turns_thinking_off_at_low_effort(self):
        # Haiku 5.5 thinks by default and thinking counts against max_tokens; a 300-token reply cannot afford it.
        self.assertEqual(AI_MODELS["haiku"]["short"], {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}})

    def test_the_free_daily_prompt_covers_every_engine_but_fable(self):
        self.assertEqual([daily_prompt_covers(1, k) for k in ("haiku", "sonnet", "opus", "fable")],
                         [True, True, False, False])


class CoachEngineTests(TestCase):
    def run_pass(self, user, trial=False):
        seen = []
        with patch.dict(os.environ, KEY), patch("anthropic.Anthropic", client_returning(resp(GOOD), seen=seen)):
            out = coach_think.apply("singz", dict(PAYLOAD), user=user, genre="R&B", target="tenor",
                                    difficulty="builder", style="", deadline=Deadline(120), trial=trial)
        return seen[0]["model"], out["think"]

    def test_the_members_pick_writes_the_answer(self):
        model, meta = self.run_pass(member("prem", TIER_PREMIUM, pick="opus"))
        self.assertEqual(model, "claude-opus-5-5")
        self.assertEqual(meta["engine"]["key"], "opus")
        self.assertTrue(meta["used"])

    def test_a_pick_above_the_tier_falls_back_to_the_best_the_tier_reaches(self):
        model, meta = self.run_pass(member("free", TIER_FREE, pick="fable"))
        self.assertEqual(model, "claude-sonnet-5-5")
        self.assertEqual(meta["engine"]["key"], "sonnet")

    def test_statz_reaches_fable_and_a_member_who_never_chose_gets_it(self):
        # Unchosen is Sonnet (the free prompts cover it); Fable only when picked.
        self.assertEqual(self.run_pass(member("z", TIER_STATZ))[0], "claude-sonnet-5-5")
        self.assertEqual(self.run_pass(member("z1", TIER_STATZ, pick="fable"))[0], "claude-fable-5-2")
        self.assertEqual(self.run_pass(member("z2", TIER_STATZ, pick="haiku"))[0], "claude-haiku-5-5")

    def test_a_stranger_on_the_trial_gets_sonnet_as_before(self):
        self.assertEqual(self.run_pass(None, trial=True)[0], "claude-sonnet-5-5")

    def test_an_operator_pin_overrides_everybody(self):
        with patch.object(coach_think, "COACH_THINK_MODEL", "claude-sonnet-5-5"):
            self.assertEqual(self.run_pass(member("z3", TIER_STATZ))[0], "claude-sonnet-5-5")

    def test_no_engine_is_named_when_claude_did_not_write_the_answer(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None); os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
            out = coach_think.apply("singz", dict(PAYLOAD), user=member("x"), genre="", target="", difficulty="",
                                    style="", deadline=Deadline(120), trial=False)
        self.assertFalse(out["think"]["used"])
        self.assertNotIn("engine", out["think"])


class PriceBeforeThePressTests(TestCase):
    def test_the_price_names_the_engine_and_fable_is_not_free_today(self):
        with patch.dict(os.environ, KEY):
            z = coach_price(member("zz", TIER_STATZ, pick="fable"))
            p = coach_price(member("pp", TIER_PREMIUM, pick="opus"))
            d = coach_price(member("pd", TIER_PREMIUM))
        self.assertEqual(z["engine"]["key"], "fable")
        self.assertFalse(z["free_today"])
        self.assertEqual(p["engine"]["key"], "opus")
        self.assertFalse(p["free_today"])
        self.assertEqual(d["engine"]["key"], "sonnet")
        self.assertTrue(d["free_today"])

    def test_with_no_key_there_is_no_second_pass_to_price(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None); os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
            z = coach_price(member("zk", TIER_STATZ))
        self.assertIsNone(z["engine"])
        self.assertTrue(z["free_today"])

    def test_the_coach_says_which_claude_will_answer_and_what_the_plan_reaches(self):
        u = member("pk", TIER_PREMIUM)
        c = APIClient()
        c.force_authenticate(u)
        with patch.dict(os.environ, KEY):
            d = c.get("/api/singz/coach/").data
        self.assertEqual(d["think"]["engine"]["key"], "sonnet")
        self.assertEqual([e["key"] for e in d["think"]["engines"] if e["allowed"]], ["haiku", "sonnet", "opus"])
        self.assertIn("Gemini listens", d["think"]["note"])


class BillOnTheEngineThatWroteTests(TestCase):
    def test_the_bill_passes_the_engine_on(self):
        from apps.economy import gemini
        u = member("b", TIER_STATZ)
        with patch("apps.economy.gemini.charge_ai_usage", return_value=100) as charge, \
             patch("apps.economy.gemini.credit_owner"):
            gemini._bill(u, "take", count_daily=True, engine="fable")
        self.assertEqual(charge.call_args.kwargs["engine"], "fable")


class LadderZRowTests(TestCase):
    def test_the_plan_table_shows_the_engine_ladder(self):
        from apps.economy.ladders import ladders
        row = next(r for r in ladders() if r["key"] == "ai_engine")
        self.assertEqual(row["values"], {"free": "Sonnet", "premium": "Opus", "statz": "Fable"})
