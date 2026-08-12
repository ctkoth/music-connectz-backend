"""The agent endpoint — and the price it has to state before it spends.

A run is 20-80 model calls, so the member cannot guess what it costs. The GET
exists to put the ceiling on the button. These tests hold that, and hold the
402 that has to fire BEFORE the work is done rather than after it.
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import occ_agent
from apps.economy.catalog import OCC_MAX_PROMPT_CHARS, ai_run_budget
from apps.economy.models import (
    TIER_STATZ,
    OccFile,
    award_promptz,
    membership_for,
    occ_settings_for,
    wallet_for,
)
from apps.economy.test_occ_agent import FakeClient, reply, text_block, tool_block

User = get_user_model()
PW = "hunter2hunter2"
URL = "/api/economy/occ/agent/"


class Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("coder", "c@e.com", PW)
        m = membership_for(self.user)
        m.tier = TIER_STATZ
        m.save()
        award_promptz(self.user, 100_000)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def post(self, script, **body):
        fake = FakeClient(script)
        with patch.object(occ_agent, "_client", return_value=fake):
            resp = self.client.post(URL, {"prompt": "do it", **body}, format="json")
        self.fake = fake
        return resp


class ThePriceIsStatedFirst(Base):
    def test_the_get_names_a_ceiling_before_anything_is_spent(self):
        d = self.client.get(URL).json()
        self.assertEqual(d["max_cents"], ai_run_budget(TIER_STATZ)["max_cents"])
        self.assertIn("🏷️", d["billing_note"])

    def test_the_get_says_which_engine_will_run_and_what_it_costs_on(self):
        d = self.client.get(URL).json()
        self.assertTrue(d["engine"])
        self.assertTrue(d["engine_name"])
        self.assertTrue(d["engine_emoji"])

    def test_the_get_says_whether_writes_will_happen(self):
        d = self.client.get(URL).json()
        self.assertFalse(d["writes_allowed"])
        self.assertIn("won't", d["write_note"])
        s = occ_settings_for(self.user)
        s.automation = True
        s.save()
        d = self.client.get(URL).json()
        self.assertTrue(d["writes_allowed"])
        self.assertIn("without asking", d["write_note"])

    def test_the_get_marks_which_tools_change_files(self):
        tools = {t["name"]: t["changes_files"] for t in self.client.get(URL).json()["tools"]}
        self.assertTrue(tools["write"])
        self.assertTrue(tools["edit"])
        self.assertFalse(tools["read"])

    def test_the_get_needs_no_money_and_spends_none(self):
        before = wallet_for(self.user).promptz
        self.assertEqual(self.client.get(URL).status_code, 200)
        self.assertEqual(wallet_for(self.user).promptz, before)


class TheEndpointRuns(Base):
    def test_a_run_returns_what_changed_and_what_it_cost(self):
        s = occ_settings_for(self.user); s.automation = True; s.save()
        resp = self.post([
            reply([tool_block("write", {"path": "a.py", "content": "x"})],
                  stop_reason="tool_use"),
            reply([text_block("Created a.py.")]),
        ])
        self.assertEqual(resp.status_code, 201)
        d = resp.json()
        self.assertEqual(d["changed"], ["a.py"])
        self.assertGreater(d["cost_cents"], 0)
        self.assertEqual(OccFile.objects.get(user=self.user, path="a.py").content, "x")

    def test_a_run_without_automation_changes_nothing(self):
        resp = self.post([
            reply([tool_block("write", {"path": "a.py", "content": "x"})],
                  stop_reason="tool_use"),
            reply([text_block("I would create a.py.")]),
        ])
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["changed"], [])
        self.assertFalse(OccFile.objects.filter(user=self.user).exists())

    def test_an_empty_prompt_is_refused_before_the_model_runs(self):
        with patch.object(occ_agent, "_client") as client:
            resp = self.client.post(URL, {"prompt": "   "}, format="json")
        self.assertEqual(resp.status_code, 400)
        client.assert_not_called()

    def test_an_enormous_prompt_is_refused_with_the_limit_named(self):
        resp = self.client.post(URL, {"prompt": "x" * (OCC_MAX_PROMPT_CHARS + 1)},
                                format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn(f"{OCC_MAX_PROMPT_CHARS:,}", resp.json()["detail"])

    def test_the_result_says_where_it_can_be_opened(self):
        d = self.post([reply([text_block("done")])]).json()
        self.assertEqual(d["open_in"], "occ")
        self.assertTrue(d["target"])

    def test_anonymous_callers_are_turned_away(self):
        anon = APIClient()
        self.assertEqual(anon.get(URL).status_code, 401)
        self.assertEqual(anon.post(URL, {"prompt": "hi"}, format="json").status_code, 401)


class TheMoneyGateFiresFirst(Base):
    def test_a_member_who_cannot_cover_the_ceiling_is_stopped_before_the_run(self):
        w = wallet_for(self.user)
        w.promptz = 0
        w.money_cents = 0
        w.save()
        with patch.object(occ_agent, "_client") as client:
            resp = self.client.post(URL, {"prompt": "do it"}, format="json")
        self.assertEqual(resp.status_code, 402)
        # The whole point: no work is done that we then can't bill for.
        client.assert_not_called()
        self.assertIn("🏷️", resp.json()["detail"])
        self.assertEqual(resp.json()["open_in"], "modelz")

    def test_the_402_still_carries_the_numbers_so_the_screen_can_explain(self):
        w = wallet_for(self.user); w.promptz = 0; w.money_cents = 0; w.save()
        d = self.client.post(URL, {"prompt": "do it"}, format="json").json()
        self.assertIn("max_cents", d)
        self.assertIn("promptz", d)


class WhenTheBackendIsMissing(Base):
    def test_an_unconfigured_backend_is_a_503_that_says_so(self):
        with patch.object(occ_agent, "_client", return_value=None):
            resp = self.client.post(URL, {"prompt": "do it"}, format="json")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("isn't configured", resp.json()["detail"])

    def test_nothing_is_charged_when_the_backend_is_missing(self):
        before = wallet_for(self.user).promptz
        with patch.object(occ_agent, "_client", return_value=None):
            self.client.post(URL, {"prompt": "do it"}, format="json")
        self.assertEqual(wallet_for(self.user).promptz, before)
