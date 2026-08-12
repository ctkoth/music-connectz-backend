"""OCC's agent loop.

The loop is where the money and the member's source code meet, so these tests
lean on the places that hurt: that the spend ceiling actually binds, that a
refusal doesn't become a 500, that a write nobody approved doesn't happen, and
that the two request parameters which 400 on the FREE tier's model are not sent
to it.

Every test drives a scripted fake client. The real one is never constructed —
a test suite that can reach the Anthropic API is a test suite that bills.
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.economy import occ_agent
from apps.economy.catalog import AI_MODELS, ai_run_budget
from apps.economy.models import (
    TIER_FREE,
    TIER_STATZ,
    OccFile,
    OccTask,
    award_promptz,
    membership_for,
    wallet_for,
)
from apps.economy.occ_agent import MAX_TURNS, run_agent

User = get_user_model()
PW = "hunter2hunter2"


# ---- the fake model -------------------------------------------------------

def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_block(name, tool_input, block_id="toolu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=block_id)


def reply(blocks, *, stop_reason="end_turn", tokens=1_000):
    return SimpleNamespace(
        content=blocks, stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=tokens, output_tokens=tokens // 10,
                              cache_read_input_tokens=0,
                              cache_creation_input_tokens=0),
    )


class FakeClient:
    """Replays a script of responses and records every request it was sent."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            return reply([text_block("done")])
        nxt = self.script.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class Base(TestCase):
    tier = TIER_STATZ

    def setUp(self):
        self.user = User.objects.create_user("coder", "c@e.com", PW)
        m = membership_for(self.user)
        m.tier = self.tier
        m.save()
        award_promptz(self.user, 100_000)   # never fail for lack of funds

    def run_with(self, script, **kw):
        self.fake = FakeClient(script)
        with patch.object(occ_agent, "_client", return_value=self.fake):
            return run_agent(self.user, kw.pop("prompt", "do the thing"), **kw)

    def file(self, path, content="", project="main"):
        return OccFile.objects.create(user=self.user, project=project,
                                      path=path, content=content)


class ThePlainPath(Base):
    def test_a_reply_with_no_tool_calls_ends_the_run(self):
        out = self.run_with([reply([text_block("Nothing to change.")])])
        self.assertTrue(out["ok"])
        self.assertEqual(out["turns"], 1)
        self.assertEqual(out["stopped"], "end_turn")
        self.assertIn("Nothing to change", out["text"])

    def test_a_tool_call_runs_and_the_loop_continues(self):
        self.file("main.py", "print(1)")
        out = self.run_with([
            reply([tool_block("read", {"path": "main.py"})], stop_reason="tool_use"),
            reply([text_block("It prints 1.")]),
        ])
        self.assertTrue(out["ok"])
        self.assertEqual(out["turns"], 2)
        # The tool result went back as a user message with the pairing intact.
        second = self.fake.calls[1]["messages"]
        self.assertEqual(second[-1]["role"], "user")
        self.assertEqual(second[-1]["content"][0]["tool_use_id"], "toolu_1")
        self.assertFalse(second[-1]["content"][0]["is_error"])

    def test_a_failed_tool_comes_back_as_an_error_the_model_can_read(self):
        out = self.run_with([
            reply([tool_block("read", {"path": "nope.py"})], stop_reason="tool_use"),
            reply([text_block("That file doesn't exist.")]),
        ])
        self.assertTrue(out["ok"])
        result = self.fake.calls[1]["messages"][-1]["content"][0]
        self.assertTrue(result["is_error"])
        self.assertIn("no file", result["content"].lower())

    def test_the_run_leaves_a_finished_task_row(self):
        out = self.run_with([reply([text_block("done")])])
        task = OccTask.objects.get(id=out["task_id"])
        self.assertEqual(task.status, OccTask.STATUS_DONE)
        self.assertEqual(task.kind, OccTask.KIND_EDIT)
        self.assertIn("🏷️", task.detail)


class WritesAreGated(Base):
    def test_a_write_is_refused_when_writes_are_not_approved(self):
        out = self.run_with([
            reply([tool_block("write", {"path": "new.py", "content": "x"})],
                  stop_reason="tool_use"),
            reply([text_block("I would create new.py.")]),
        ], writes_allowed=False)
        self.assertFalse(OccFile.objects.filter(user=self.user).exists())
        self.assertEqual(out["changed"], [])
        result = self.fake.calls[1]["messages"][-1]["content"][0]
        self.assertTrue(result["is_error"])
        self.assertIn("aren't approved", result["content"])

    def test_an_edit_is_refused_the_same_way(self):
        self.file("main.py", "old")
        self.run_with([
            reply([tool_block("edit", {"path": "main.py", "old": "old", "new": "new"})],
                  stop_reason="tool_use"),
            reply([text_block("I would change it.")]),
        ], writes_allowed=False)
        self.assertEqual(OccFile.objects.get(user=self.user, path="main.py").content,
                         "old")

    def test_reads_still_work_when_writes_are_refused(self):
        self.file("main.py", "print(1)")
        self.run_with([
            reply([tool_block("read", {"path": "main.py"})], stop_reason="tool_use"),
            reply([text_block("read it")]),
        ], writes_allowed=False)
        self.assertFalse(self.fake.calls[1]["messages"][-1]["content"][0]["is_error"])

    def test_an_approved_write_lands_and_is_reported(self):
        out = self.run_with([
            reply([tool_block("write", {"path": "new.py", "content": "print(2)"})],
                  stop_reason="tool_use"),
            reply([text_block("Created new.py.")]),
        ], writes_allowed=True)
        self.assertEqual(out["changed"], ["new.py"])
        self.assertEqual(
            OccFile.objects.get(user=self.user, path="new.py").content, "print(2)")

    def test_a_written_file_records_the_task_that_wrote_it(self):
        out = self.run_with([
            reply([tool_block("write", {"path": "new.py", "content": "x"})],
                  stop_reason="tool_use"),
            reply([text_block("done")]),
        ], writes_allowed=True)
        row = OccFile.objects.get(user=self.user, path="new.py")
        self.assertEqual(row.task_id, out["task_id"])


class TheCeilingBinds(Base):
    def test_the_run_stops_when_the_budget_is_reached(self):
        # One enormous turn, then the loop must not start another.
        huge = reply([tool_block("read", {"path": "a.py"})],
                     stop_reason="tool_use", tokens=100_000_000)
        out = self.run_with([huge, reply([text_block("more")]), reply([text_block("more")])])
        self.assertEqual(out["stopped"], "budget")
        self.assertEqual(len(self.fake.calls), 1)

    def test_a_budget_stop_still_counts_as_a_usable_run(self):
        huge = reply([tool_block("read", {"path": "a.py"})],
                     stop_reason="tool_use", tokens=100_000_000)
        out = self.run_with([huge])
        # It did work and produced output — it just stopped early. Marking it
        # failed would throw away what the member already paid for.
        self.assertTrue(out["ok"])
        self.assertEqual(OccTask.objects.get(id=out["task_id"]).status,
                         OccTask.STATUS_DONE)

    def test_the_ceiling_is_reported_so_the_client_can_state_it(self):
        out = self.run_with([reply([text_block("done")])])
        self.assertEqual(out["max_cents"], ai_run_budget(self.tier)["max_cents"])

    def test_a_looping_model_is_stopped_by_the_turn_backstop(self):
        # Cheap enough never to reach the spend ceiling — this is the other net.
        cheap = [reply([tool_block("glob", {})], stop_reason="tool_use", tokens=1)
                 for _ in range(MAX_TURNS + 5)]
        out = self.run_with(cheap)
        self.assertEqual(out["stopped"], "max_turns")
        self.assertEqual(out["turns"], MAX_TURNS)


class BillingIsHonest(Base):
    def test_a_run_is_charged_what_it_used(self):
        before = wallet_for(self.user).promptz
        out = self.run_with([reply([text_block("done")], tokens=1_000_000)])
        self.assertGreater(out["cost_cents"], 0)
        self.assertEqual(wallet_for(self.user).promptz, before - out["cost_cents"])

    def test_the_wallet_is_debited_the_price_not_the_cost(self):
        # The distinction that stops a 20% loss: what Anthropic billed and what
        # the member pays are two numbers, and the wallet must see the second.
        from apps.economy.catalog import ai_run_charge_cents, ai_run_cost_cents
        before = wallet_for(self.user).promptz
        out = self.run_with([reply([text_block("done")], tokens=1_000_000)])
        spent = before - wallet_for(self.user).promptz
        self.assertEqual(spent, out["cost_cents"])
        self.assertGreater(spent, out["served_cents"])
        self.assertEqual(out["served_cents"],
                         ai_run_cost_cents(out["engine"], out["usage"]))
        self.assertEqual(spent, ai_run_charge_cents(out["engine"], out["usage"]))

    def test_the_budget_gate_measures_what_the_member_pays(self):
        # If the gate watched cost while the button promised charge, a run could
        # bill past the ceiling the member was shown.
        from apps.economy.catalog import ai_run_charge_cents
        huge = reply([tool_block("glob", {})], stop_reason="tool_use",
                     tokens=100_000_000)
        out = self.run_with([huge, reply([text_block("more")])])
        self.assertEqual(out["stopped"], "budget")
        self.assertGreaterEqual(
            ai_run_charge_cents(out["engine"], out["usage"]), out["max_cents"])

    def test_a_run_that_reached_nothing_is_not_billed(self):
        # Same rule vocalcoach.py bills on: no usable result, no charge.
        before = wallet_for(self.user).promptz
        out = self.run_with([RuntimeError("network gone")])
        self.assertEqual(out["stopped"], "error")
        self.assertEqual(out["cost_cents"], 0)
        self.assertEqual(wallet_for(self.user).promptz, before)

    def test_the_daily_free_prompt_is_not_spent_on_an_agent_run(self):
        # The allowance is one free PROMPT. Letting it cover an 80-call run
        # would be giving away a dollar of tokens for a one-cent allowance.
        from apps.economy.models import daily_prompt_state
        _, _, before = daily_prompt_state(self.user)
        self.run_with([reply([text_block("done")], tokens=1_000_000)])
        _, _, after = daily_prompt_state(self.user)
        self.assertEqual(before, after)


class FailuresStaySafe(Base):
    def test_a_refusal_does_not_crash_on_empty_content(self):
        # Claude Opus 5 can decline. content is empty or partial on a refusal,
        # so indexing it before checking stop_reason is how this becomes a 500.
        out = self.run_with([reply([], stop_reason="refusal")])
        self.assertEqual(out["stopped"], "refused")
        self.assertFalse(out["ok"])
        self.assertIn("declined", out["text"])

    def test_a_backend_error_is_reported_not_raised(self):
        out = self.run_with([RuntimeError("boom")])
        self.assertEqual(out["stopped"], "error")
        self.assertFalse(out["ok"])
        self.assertEqual(OccTask.objects.get(id=out["task_id"]).status,
                         OccTask.STATUS_FAILED)

    def test_a_missing_api_key_says_so_instead_of_pretending(self):
        with patch.object(occ_agent, "_client", return_value=None):
            out = run_agent(self.user, "hello")
        self.assertFalse(out["ok"])
        self.assertEqual(out["stopped"], "unavailable")
        self.assertNotIn("task_id", out)

    def test_a_tool_the_model_invented_does_not_break_the_run(self):
        out = self.run_with([
            reply([tool_block("rm_rf", {"path": "/"})], stop_reason="tool_use"),
            reply([text_block("sorry")]),
        ])
        self.assertTrue(out["ok"])
        self.assertTrue(self.fake.calls[1]["messages"][-1]["content"][0]["is_error"])


class TheRequestSuitsTheModel(Base):
    """Two parameters 400 on Haiku 4.5 — which is the FREE tier's model."""

    def test_haiku_is_sent_neither_effort_nor_task_budget(self):
        fake = FakeClient([reply([text_block("hi")])])
        with patch.object(occ_agent, "_client", return_value=fake):
            run_agent(self.user, "hi", model_key="haiku")
        sent = fake.calls[0]
        # Either one is a 400 on Haiku 4.5, and a 400 here means the FREE tier's
        # agent never runs at all.
        self.assertNotIn("output_config", sent)
        self.assertNotIn("betas", sent)

    def test_opus_is_sent_effort(self):
        fake = FakeClient([reply([text_block("hi")])])
        with patch.object(occ_agent, "_client", return_value=fake):
            run_agent(self.user, "hi", model_key="opus")
        self.assertIn("effort", fake.calls[0]["output_config"])

    def test_the_flags_match_what_the_loop_sends(self):
        for key in ("haiku", "opus"):
            with self.subTest(model=key):
                fake = FakeClient([reply([text_block("hi")])])
                with patch.object(occ_agent, "_client", return_value=fake):
                    run_agent(self.user, "hi", model_key=key)
                sent = fake.calls[0]
                if AI_MODELS[key]["effort"]:
                    self.assertIn("effort", sent["output_config"])
                else:
                    # Sent to Haiku, this is a 400 and the member sees nothing.
                    self.assertNotIn("output_config", sent)

    def test_the_model_is_actually_told_how_much_budget_is_left(self):
        # The system prompt tells the model it "is told what is left". Nothing
        # sent it — so the model paced against a number it had to invent.
        fake = FakeClient([
            reply([tool_block("glob", {})], stop_reason="tool_use", tokens=1),
            reply([text_block("done")]),
        ])
        with patch.object(occ_agent, "_client", return_value=fake):
            run_agent(self.user, "hi")
        self.assertIn("Budget:", fake.calls[0]["system"])

    def test_the_note_gets_more_urgent_as_the_budget_goes(self):
        early = occ_agent._budget_note(0, 100)
        mid = occ_agent._budget_note(60, 100)
        late = occ_agent._budget_note(95, 100)
        self.assertIn("normally", early)
        self.assertIn("prioritis", mid)
        self.assertIn("Finish cleanly", late)

    def test_the_note_never_divides_by_zero(self):
        self.assertIn("Budget:", occ_agent._budget_note(0, 0))

    def test_no_call_carries_a_beta_only_parameter(self):
        # `task_budget` needs the beta endpoint AND the beta flag. Sent here it
        # would 400 every real request while a fake client accepted it happily.
        fake = FakeClient([reply([text_block("hi")])])
        with patch.object(occ_agent, "_client", return_value=fake):
            run_agent(self.user, "hi", model_key="opus")
        self.assertNotIn("task_budget", fake.calls[0].get("output_config", {}))
        self.assertNotIn("betas", fake.calls[0])

    def test_every_call_carries_the_tools(self):
        fake = FakeClient([reply([text_block("hi")])])
        with patch.object(occ_agent, "_client", return_value=fake):
            run_agent(self.user, "hi")
        self.assertTrue(fake.calls[0]["tools"])


class FreeTierRuns(Base):
    tier = TIER_FREE

    def test_a_free_member_gets_a_smaller_ceiling_but_still_runs(self):
        out = self.run_with([reply([text_block("done")])])
        self.assertTrue(out["ok"])
        self.assertEqual(out["max_cents"], ai_run_budget(TIER_FREE)["max_cents"])

    def test_a_free_member_is_put_on_a_model_their_tier_owns(self):
        out = self.run_with([reply([text_block("done")])])
        self.assertEqual(out["engine"], "haiku")
