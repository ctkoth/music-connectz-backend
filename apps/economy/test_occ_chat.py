"""OCC's chat — the part of OCC that is an AI you talk to.

The endpoint existed for as long as OCC did and nothing mounted called it. These
hold the promises the screen now makes beside the Send button:

* the price is knowable BEFORE sending (`GET /ai/models/`), and is the price the
  send then charges — or "Free today", when the day's allowance covers it;
* a reply that fails is never charged, whichever way it fails;
* the member's stored VoiceZ voice applies unless the request carries a dial;
* the wait is bounded, and a 503 for "not switched on" reads differently from a
  503 for "the model had a bad minute".
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.catalog import AI_MODELS, OCC_MAX_PROMPT_CHARS
from apps.economy.models import (
    TIER_FREE,
    TIER_PREMIUM,
    Transaction,
    membership_for,
    voice_prefs_for,
    wallet_for,
)
from apps.economy.occ import CHAT_BUDGET_SECONDS, COREY_VOICE, VOICE_STYLE

User = get_user_model()
PW = "hunter2hunter2"
CHAT = "/api/economy/ai/occ/"
MODELS = "/api/economy/ai/models/"


class Block:
    type = "text"

    def __init__(self, text):
        self.text = text


def client_that(seen, reply="a reply", fail=None):
    """An anthropic stand-in. `fail` is raised by messages.create."""
    class C:
        class messages:
            @staticmethod
            def create(**kw):
                seen.append(kw)
                if fail is not None:
                    raise fail
                return type("R", (), {"content": [Block(reply)] if reply else []})()
    return C


def as_tier(user, tier):
    m = membership_for(user)
    m.tier = tier
    m.save(update_fields=["tier", "updated_at"])


class Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("chatter", "c@e.com", PW)
        membership_for(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def say(self, seen=None, reply="a reply", fail=None, **body):
        seen = seen if seen is not None else []
        fake = type("anthropic", (), {"Anthropic": client_that(seen, reply, fail)})
        with patch.dict("sys.modules", {"anthropic": fake}):
            return self.client.post(CHAT, {"prompt": "hi", **body}, format="json"), seen

    def money(self, promptz=0, cents=0):
        w = wallet_for(self.user)
        w.promptz, w.money_cents = promptz, cents
        w.save(update_fields=["promptz", "money_cents"])

    def use_up_the_free_prompts(self):
        from apps.economy.models import PROMPT_ALLOWANCE
        w = wallet_for(self.user)
        from django.utils import timezone
        w.prompt_day = timezone.now().strftime("%Y-%m-%d")
        w.prompts_used_today = PROMPT_ALLOWANCE["free"]
        w.save(update_fields=["prompt_day", "prompts_used_today"])


class ThePriceIsKnownBeforeSending(Base):
    """`GET /ai/models/` carries everything the Send button needs to state its
    price — it used to arrive only in the reply, which is the bill."""

    def state(self):
        return self.client.get(MODELS).data

    def row(self, key):
        return next(r for r in self.state()["models"] if r["key"] == key)

    def test_the_free_allowance_is_published_with_what_is_left(self):
        st = self.state()
        self.assertEqual(st["daily_prompts"], 3)
        self.assertEqual(st["daily_prompts_left"], 3)
        self.assertIn("daily_prompt_max_cents", st)

    def test_an_engine_the_allowance_covers_says_free_today(self):
        self.assertTrue(self.row("haiku")["free_today"])

    def test_a_dearer_engine_is_free_today_while_prompts_are_left(self):
        # One task is one PromptZ whatever the engine (Corey's rule), so a free
        # prompt covers Sonnet as it does Haiku.
        as_tier(self.user, TIER_PREMIUM)
        self.assertTrue(self.row("sonnet")["free_today"])

    def test_free_today_goes_when_the_prompts_do(self):
        self.use_up_the_free_prompts()
        self.assertFalse(self.row("haiku")["free_today"])
        self.assertEqual(self.state()["daily_prompts_left"], 0)

    def test_each_row_says_whether_the_wallet_covers_it(self):
        self.money(promptz=0, cents=0)
        self.assertFalse(self.row("haiku")["affordable"])
        self.money(promptz=AI_MODELS["haiku"]["cost_cents"])
        self.assertTrue(self.row("haiku")["affordable"])

    def test_the_balance_travels_with_it(self):
        self.money(promptz=7, cents=40)
        st = self.state()
        self.assertEqual((st["promptz"], st["money_cents"]), (7, 40))

    def test_the_wait_the_server_will_allow_is_published_for_the_screens_timeout(self):
        self.assertEqual(self.state()["chat_budget_seconds"], CHAT_BUDGET_SECONDS)

    def test_a_locked_row_names_the_tier_it_needs(self):
        row = self.row("fable")
        self.assertFalse(row["allowed"])
        self.assertEqual(row["required_tier"], "statz")

    def test_the_price_beforehand_is_the_price_charged(self):
        self.money(promptz=50)
        self.use_up_the_free_prompts()
        before = self.state()
        cost = next(r for r in before["models"] if r["current"])["cost_cents"]
        resp, _ = self.say()
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["cost_cents"], cost)
        self.assertEqual(wallet_for(self.user).promptz, 50 - cost)
        self.assertFalse(resp.data["free_prompt"])

    def test_a_free_today_message_charges_nothing_and_says_so(self):
        self.money(promptz=50)
        resp, _ = self.say()
        self.assertTrue(resp.data["free_prompt"])
        self.assertEqual(wallet_for(self.user).promptz, 50)
        self.assertEqual(resp.data["daily_prompts_left"], 2)


class AReplyThatFailsIsNeverCharged(Base):
    def setUp(self):
        super().setUp()
        self.money(promptz=50)
        self.use_up_the_free_prompts()       # so a charge would actually show

    def assert_free(self, resp):
        self.assertEqual(wallet_for(self.user).promptz, 50)
        self.assertEqual(wallet_for(self.user).money_cents, 0)
        self.assertFalse(Transaction.objects.filter(user=self.user, note__contains="OCC").exists())
        self.assertEqual(resp.data.get("charged"), 0)

    def test_a_model_error(self):
        resp, _ = self.say(fail=RuntimeError("overloaded"))
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data["code"], "backend_error")
        self.assert_free(resp)

    def test_an_empty_reply(self):
        resp, _ = self.say(reply="")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data["code"], "empty_reply")
        self.assert_free(resp)

    def test_running_out_of_time(self):
        class APITimeoutError(Exception):
            pass
        resp, _ = self.say(fail=APITimeoutError("Request timed out."))
        self.assertEqual(resp.status_code, 504)
        self.assertEqual(resp.data["code"], "timed_out")
        self.assertIn(str(CHAT_BUDGET_SECONDS), resp.data["detail"])
        self.assertIn("weren't charged", resp.data["detail"])
        self.assert_free(resp)

    def test_a_missing_key(self):
        err = TypeError("Could not resolve authentication method. Expected one of api_key...")
        resp, _ = self.say(fail=err)
        self.assertEqual(resp.status_code, 503)
        self.assert_free(resp)

    def test_a_refused_message_never_reaches_the_model(self):
        seen = []
        resp, seen = self.say(seen, prompt="x" * (OCC_MAX_PROMPT_CHARS + 1))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(seen, [])


class ThePictureOf503(Base):
    """"Not switched on" and "bad minute" are different sentences."""

    def test_no_key_reads_as_not_switched_on(self):
        err = TypeError("Could not resolve authentication method. Expected one of api_key...")
        resp, _ = self.say(fail=err)
        self.assertEqual(resp.data["code"], "not_configured")
        self.assertEqual(resp.data["detail"], "OCC's chat isn't switched on yet.")

    def test_a_refused_key_reads_the_same(self):
        class AuthenticationError(Exception):
            pass
        resp, _ = self.say(fail=AuthenticationError("invalid x-api-key"))
        self.assertEqual(resp.data["code"], "not_configured")

    def test_the_sdk_not_installed_reads_the_same(self):
        with patch.dict("sys.modules", {"anthropic": None}):
            resp = self.client.post(CHAT, {"prompt": "hi"}, format="json")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data["code"], "not_configured")

    def test_a_model_error_never_leaks_its_text_to_the_member(self):
        resp, _ = self.say(fail=RuntimeError("secret-host.internal refused sk-ant-abc123"))
        self.assertNotIn("sk-ant", resp.data["detail"])
        self.assertNotIn("secret-host", resp.data["detail"])
        self.assertEqual(resp.data["code"], "backend_error")


class TheWaitIsBounded(Base):
    def test_each_call_carries_a_timeout_from_the_budget(self):
        resp, seen = self.say()
        self.assertEqual(resp.status_code, 200)
        t = seen[0]["timeout"]
        self.assertLessEqual(t, CHAT_BUDGET_SECONDS)
        self.assertGreater(t, CHAT_BUDGET_SECONDS - 10)

    def test_the_fallback_draws_on_the_same_budget(self):
        # First model "not found" -> falls back; both calls carry a timeout and the
        # second can never have more than the first.
        calls = []

        class C:
            class messages:
                @staticmethod
                def create(**kw):
                    calls.append(kw)
                    if len(calls) == 1:
                        raise RuntimeError("404 model not found")
                    return type("R", (), {"content": [Block("ok")]})()
        as_tier(self.user, TIER_PREMIUM)
        from apps.economy.models import profile_for
        p = profile_for(self.user)
        p.ai_model = "sonnet"
        p.save(update_fields=["ai_model"])
        self.money(promptz=100)
        fake = type("anthropic", (), {"Anthropic": C})
        with patch.dict("sys.modules", {"anthropic": fake}):
            resp = self.client.post(CHAT, {"prompt": "hi"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(len(calls), 2)
        self.assertLessEqual(calls[1]["timeout"], calls[0]["timeout"])

    def test_a_spent_budget_does_not_start_a_fallback(self):
        calls = []

        class C:
            class messages:
                @staticmethod
                def create(**kw):
                    calls.append(kw)
                    raise RuntimeError("404 model not found")
        as_tier(self.user, TIER_PREMIUM)
        from apps.economy.models import profile_for
        p = profile_for(self.user)
        p.ai_model = "sonnet"
        p.save(update_fields=["ai_model"])
        self.money(promptz=100)
        fake = type("anthropic", (), {"Anthropic": C})
        with patch.dict("sys.modules", {"anthropic": fake}), \
                patch("apps.economy.occ.Deadline.expired", side_effect=[False, True, True]):
            resp = self.client.post(CHAT, {"prompt": "hi"}, format="json")
        self.assertEqual(resp.status_code, 504, resp.data)
        self.assertEqual(len(calls), 1, "no second call on an empty budget")
        self.assertEqual(wallet_for(self.user).promptz, 100)


class TheMembersStoredVoiceApplies(Base):
    """`model` is a per-message dial. When it is not sent the member's own VoiceZ
    voice applies — it used to default to corey-gpt and override the stored style
    every time, so a member who chose Technical was answered in Corey's voice by
    the one screen that took no voice field."""

    def set_style(self, style, slang=False):
        p = voice_prefs_for(self.user)
        p.style, p.slang = style, slang
        p.save(update_fields=["style", "slang", "updated_at"])

    def system_for(self, **body):
        resp, seen = self.say(**body)
        self.assertEqual(resp.status_code, 200, resp.data)
        return seen[0]["system"], resp

    def test_the_stored_style_is_used_when_no_dial_is_sent(self):
        self.set_style("technical")
        system, resp = self.system_for()
        self.assertIn(VOICE_STYLE["technical"], system)
        self.assertNotIn(COREY_VOICE[:60], system)
        self.assertEqual(resp.data["model"], "technical")

    def test_an_explicit_dial_overrides_for_that_message_only(self):
        self.set_style("technical")
        system, _ = self.system_for(model="corey-gpt")
        self.assertIn(COREY_VOICE[:60], system)
        # ...and the stored voice is untouched.
        voice_prefs_for(self.user).refresh_from_db()
        self.assertEqual(voice_prefs_for(self.user).style, "technical")

    def test_the_default_member_still_gets_corey(self):
        system, resp = self.system_for()
        self.assertIn(COREY_VOICE[:60], system)
        self.assertEqual(resp.data["model"], "corey-gpt")

    def test_an_unknown_dial_falls_back_to_the_stored_voice_not_to_corey(self):
        self.set_style("standard")
        system, _ = self.system_for(model="not-a-voice")
        self.assertIn(VOICE_STYLE["standard"], system)

    def test_stored_slang_holds_unless_the_request_says_otherwise(self):
        from apps.economy.occ import AAVE_STYLE
        self.set_style("corey", slang=True)
        system, _ = self.system_for()
        self.assertIn(AAVE_STYLE[:40], system)
        system, _ = self.system_for(slang=False)
        self.assertNotIn(AAVE_STYLE[:40], system)

    def test_history_is_sent_in_the_shape_the_endpoint_reads(self):
        resp, seen = self.say(history=[{"role": "user", "text": "first"},
                                       {"role": "occ", "text": "answer"}])
        msgs = seen[0]["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])
        self.assertEqual(msgs[1]["content"], "answer")


class TheRefusalCarriesTheWayForward(Base):
    def test_a_402_says_which_wall_and_where_to_go(self):
        self.money(0, 0)
        self.use_up_the_free_prompts()
        resp, seen = self.say()
        self.assertEqual(resp.status_code, 402)
        self.assertEqual(seen, [])
        # The engine picker lives in OCC's own chat panel; topping up is PromptZ's
        # door in MembershipZ. There is no `modelz` tab.
        self.assertEqual((resp.data["open_in"], resp.data["target"]), ("occ", "occ-chat"))
        self.assertEqual((resp.data["buy_in"], resp.data["buy_target"]),
                         ("membershipz", "promptz-door"))
        self.assertIn("today's free prompts are spent", resp.data["detail"])

    def test_a_save_offer_points_at_a_real_anchor(self):
        resp, _ = self.say()
        self.assertEqual(resp.data["can_save_work"]["target"], "occ-workz")

    def test_a_free_member_can_still_choose_only_what_the_tier_allows(self):
        as_tier(self.user, TIER_FREE)
        r = self.client.patch(MODELS, {"model": "opus"}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data["required_tier"], "statz")
