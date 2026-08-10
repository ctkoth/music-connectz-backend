"""ModelZ — the engine you pick, the tier that gates it, the price it costs.

Every model run in this app bills one Anthropic account: the platform's. So the
rule these tests hold the ladder to is that the price a member is charged has to
cover the run they triggered — a per-message price under real cost is the
platform paying people to use it, and it gets worse the more popular it gets.

The other rule is the app's own: the price is on the row BEFORE anybody picks
it. A member choosing a better engine is choosing a bigger bill.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.catalog import (
    AI_MODELS,
    AI_MODEL_ORDER,
    ai_model_for,
    ai_models_for,
    default_ai_model,
)
from apps.economy.models import (
    TIER_FREE,
    TIER_PREMIUM,
    TIER_STATZ,
    membership_for,
    profile_for,
)

User = get_user_model()
PW = "hunter2hunter2"
URL = "/api/economy/ai/models/"


def as_tier(user, tier):
    m = membership_for(user)
    m.tier = tier
    m.save(update_fields=["tier", "updated_at"])
    return user


class Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("picker", "p@e.com", PW)
        membership_for(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)


class TheLadderTests(Base):
    def test_free_gets_the_cheap_engine_only(self):
        self.assertEqual(ai_models_for(TIER_FREE), ["haiku"])

    def test_premium_reaches_opus(self):
        self.assertIn("opus", ai_models_for(TIER_PREMIUM))

    def test_only_statz_reaches_fable(self):
        self.assertNotIn("fable", ai_models_for(TIER_PREMIUM))
        self.assertIn("fable", ai_models_for(TIER_STATZ))

    def test_a_tier_keeps_everything_below_it(self):
        # Upgrading only ever adds. A Premium member must not lose Haiku.
        for lower, higher in ((TIER_FREE, TIER_PREMIUM), (TIER_PREMIUM, TIER_STATZ)):
            self.assertTrue(set(ai_models_for(lower)) <= set(ai_models_for(higher)),
                            f"{higher} lost something {lower} had")

    def test_the_order_is_cheapest_first(self):
        costs = [AI_MODELS[k]["cost_cents"] for k in AI_MODEL_ORDER]
        self.assertEqual(costs, sorted(costs))

    def test_a_dearer_engine_never_sits_on_a_lower_tier(self):
        # The ladder has to climb in both money and tier at once, or a member
        # can pay less and get more.
        rank = {TIER_FREE: 0, TIER_PREMIUM: 1, TIER_STATZ: 2}
        tiers = [rank[AI_MODELS[k]["tier"]] for k in AI_MODEL_ORDER]
        self.assertEqual(tiers, sorted(tiers))


class WhatItCostsUsTests(Base):
    """The numbers, checked against the published per-million rates.

    A typical OCC turn is about 10,000 input tokens and 800 output. If the
    charged minimum drops under that, the app is losing money per message.
    """

    # (key, $ per M input, $ per M output)
    RATES = [("haiku", 1, 5), ("sonnet", 3, 15), ("opus", 5, 25), ("fable", 10, 50)]

    def test_each_price_covers_a_typical_run(self):
        for key, in_rate, out_rate in self.RATES:
            real = (10_000 / 1_000_000) * in_rate * 100 + (800 / 1_000_000) * out_rate * 100
            self.assertGreaterEqual(
                AI_MODELS[key]["cost_cents"], real,
                f"{key} charges {AI_MODELS[key]['cost_cents']}c to run a "
                f"{real:.1f}c message — the platform eats the difference")

    def test_the_old_flat_price_would_not_have(self):
        # The bug this replaced, pinned so it can't come back: 3c was the old
        # 'standard' price and it does not cover Opus, never mind Fable.
        self.assertLess(3, AI_MODELS["opus"]["cost_cents"])
        self.assertLess(3, AI_MODELS["fable"]["cost_cents"])


class TheDefaultTests(Base):
    def test_a_member_who_never_chose_gets_the_best_rung_they_own(self):
        # They paid for the tier. Quietly serving them the cheapest engine
        # would be selling a thing and then not handing it over.
        self.assertEqual(default_ai_model(TIER_FREE), "haiku")
        self.assertEqual(default_ai_model(TIER_STATZ), "fable")

    def test_a_choice_above_your_tier_falls_back_rather_than_breaking(self):
        # A lapsed StatZ member still has 'fable' stored. That must not 500 or
        # 402 them on a screen they didn't come to fix.
        key, spec = ai_model_for("fable", TIER_FREE)
        self.assertEqual(key, "haiku")
        self.assertEqual(spec["cost_cents"], AI_MODELS["haiku"]["cost_cents"])

    def test_junk_falls_back_too(self):
        self.assertEqual(ai_model_for("", TIER_FREE)[0], "haiku")
        self.assertEqual(ai_model_for("gpt-9", TIER_STATZ)[0], "fable")


class TheScreenTests(Base):
    def test_every_row_states_its_price_before_anybody_picks_it(self):
        rows = self.client.get(URL).data["models"]
        self.assertEqual(len(rows), len(AI_MODEL_ORDER))
        for r in rows:
            self.assertGreater(r["cost_cents"], 0, r["key"])
            self.assertIn("🏷️", r["cost_note"])

    def test_locked_rows_are_shown_not_hidden(self):
        # A locked row nobody can see is not an upsell, it's a secret.
        rows = {r["key"]: r for r in self.client.get(URL).data["models"]}
        self.assertFalse(rows["fable"]["allowed"])
        self.assertEqual(rows["fable"]["tier"], TIER_STATZ)

    def test_a_locked_row_says_where_to_go(self):
        resp = self.client.patch(URL, {"model": "fable"}, format="json")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data["required_tier"], TIER_STATZ)
        self.assertEqual(resp.data["open_in"], "membershipz")
        # And the price is in the refusal, so the upgrade decision is informed.
        self.assertEqual(resp.data["cost_cents"], AI_MODELS["fable"]["cost_cents"])

    def test_choosing_within_your_tier_sticks(self):
        as_tier(self.user, TIER_PREMIUM)
        resp = self.client.patch(URL, {"model": "sonnet"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["model"], "sonnet")
        self.assertEqual(resp.data["cost_cents"], AI_MODELS["sonnet"]["cost_cents"])
        self.assertEqual(self.client.get(URL).data["model"], "sonnet")

    def test_a_nonsense_model_is_refused_with_the_real_list(self):
        resp = self.client.patch(URL, {"model": "sonnet-9000"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["models"], list(AI_MODEL_ORDER))

    def test_the_screen_says_whether_you_actually_chose(self):
        self.assertFalse(self.client.get(URL).data["chosen"])
        self.client.patch(URL, {"model": "haiku"}, format="json")
        self.assertTrue(self.client.get(URL).data["chosen"])

    def test_the_model_id_is_not_published(self):
        # It changes when a better model ships; a client rendering it goes
        # stale that day.
        row = self.client.get(URL).data["models"][0]
        self.assertNotIn("id", row)

    def test_an_upgrade_does_not_wipe_a_saved_choice(self):
        as_tier(self.user, TIER_PREMIUM)
        self.client.patch(URL, {"model": "sonnet"}, format="json")
        as_tier(self.user, TIER_STATZ)
        self.assertEqual(self.client.get(URL).data["model"], "sonnet")


class WhatOccChargesTests(Base):
    """The engine is what costs, not the voice."""

    def test_the_voice_no_longer_sets_the_price(self):
        from apps.economy.catalog import ai_cost
        # Tone is a system prompt. Three of them, one price each, none of which
        # matched what the model underneath actually cost.
        as_tier(self.user, TIER_STATZ)
        p = profile_for(self.user)
        p.ai_model = "fable"
        p.save(update_fields=["ai_model"])
        _, spec = ai_model_for(p.ai_model, TIER_STATZ)
        self.assertNotEqual(spec["cost_cents"], ai_cost("corey-gpt"))
        self.assertEqual(spec["cost_cents"], AI_MODELS["fable"]["cost_cents"])

    def test_a_free_member_on_occ_is_charged_the_cheap_engine(self):
        _, spec = ai_model_for(profile_for(self.user).ai_model, TIER_FREE)
        self.assertEqual(spec["cost_cents"], AI_MODELS["haiku"]["cost_cents"])


class FakeBlock:
    type = "text"
    def __init__(self, text): self.text = text


def recording_client(seen):
    """An anthropic stand-in that records the model each call asked for."""
    class C:
        class messages:
            @staticmethod
            def create(**kw):
                seen.append(kw.get("model"))
                return type("R", (), {"content": [FakeBlock("ok")]})()
    return C


class FreeSurfacesStayCheapTests(TestCase):
    """A surface that charges nothing must not run the priciest engine.

    Both of these were on flagship models with no payer — the bill had no
    ceiling and nobody to send it to. Asserted on the model actually sent to
    the API, not on the source text, so a comment can't satisfy it.
    """

    def test_the_keyboard_runs_the_cheap_engine(self):
        from apps.economy.keyconnectz import TRANSLATE_MODEL
        self.assertEqual(TRANSLATE_MODEL, AI_MODELS["haiku"]["id"])

    def test_omviardz_guidance_runs_the_cheap_engine(self):
        from unittest.mock import patch

        from apps.omviardz.voice import explain
        seen = []
        fake = type("anthropic", (), {"Anthropic": recording_client(seen)})
        with patch.dict("sys.modules", {"anthropic": fake}):
            explain({"screen": "postz"}, {"label": "Post"}, "what is this?")
        self.assertEqual(seen, [AI_MODELS["haiku"]["id"]])


class OccRunsTheChosenEngineTests(Base):
    """What the member picked is what gets run — and what they get billed."""

    def ask(self, seen):
        from unittest.mock import patch
        fake = type("anthropic", (), {"Anthropic": recording_client(seen)})
        with patch.dict("sys.modules", {"anthropic": fake}):
            return self.client.post("/api/economy/ai/occ/",
                                    {"prompt": "hi", "model": "corey-gpt"}, format="json")

    def test_a_free_member_runs_the_cheap_engine(self):
        seen = []
        resp = self.ask(seen)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(seen, [AI_MODELS["haiku"]["id"]])
        self.assertEqual(resp.data["cost_cents"], AI_MODELS["haiku"]["cost_cents"])
        self.assertEqual(resp.data["engine"], "haiku")

    def test_a_statz_member_who_picked_fable_runs_fable_and_pays_for_it(self):
        as_tier(self.user, TIER_STATZ)
        p = profile_for(self.user)
        p.ai_model = "fable"
        p.save(update_fields=["ai_model"])
        from apps.economy.models import wallet_for
        w = wallet_for(self.user)
        w.promptz = 500
        w.save(update_fields=["promptz"])
        seen = []
        resp = self.ask(seen)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(seen, [AI_MODELS["fable"]["id"]])
        self.assertEqual(resp.data["cost_cents"], AI_MODELS["fable"]["cost_cents"])

    def test_the_voice_still_shapes_the_tone_it_just_does_not_set_the_price(self):
        # Two voices, one engine, one price. Tone is free.
        seen = []
        from unittest.mock import patch
        fake = type("anthropic", (), {"Anthropic": recording_client(seen)})
        costs = []
        for voice in ("corey-gpt", "technical"):
            with patch.dict("sys.modules", {"anthropic": fake}):
                r = self.client.post("/api/economy/ai/occ/",
                                     {"prompt": "hi", "model": voice}, format="json")
            costs.append(r.data["cost_cents"])
        self.assertEqual(costs[0], costs[1])
        self.assertEqual(set(seen), {AI_MODELS["haiku"]["id"]})
