"""Tests for OCC's coding agent — the tools, the loop, and the containment.

The loop is tested against a scripted fake model rather than the real one: a test
that needs an API key isn't a test. `_FakeClient` returns a queued list of
responses, which lets us assert the thing that actually matters — that OCC's tool
calls are executed, their results are fed back, and the loop keeps going until
the model stops asking.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (TIER_FREE, TIER_STATZ, AgentRun, Project,
                                 ProjectFile, ProjectSnapshot, membership_for,
                                 wallet_for)
from apps.economy.occ_agent import (MAX_STEPS, STOP_BUDGET, STOP_DONE,
                                    STOP_ERROR, STOP_MAX_STEPS, build_system,
                                    max_steps_for, run_agent)
from apps.economy.occ_tools import (MAX_FILES, MAX_SNAPSHOTS, TOOL_NAMES,
                                   Workspace, normalize_path, run_tool,
                                   take_snapshot)

User = get_user_model()


# --------------------------------------------------------------- fake model
class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def text_block(text):
    return _Block(type="text", text=text)


def tool_block(name, params, id="tu_1"):
    return _Block(type="tool_use", id=id, name=name, input=params)


class _Resp:
    def __init__(self, blocks):
        self.content = blocks


def script(*turns):
    """Queue model responses. Each turn is a list of blocks."""
    return [_Resp(list(t)) for t in turns]


class _Messages:
    def __init__(self, queue):
        self.queue = queue
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.queue:
            return _Resp([text_block("(nothing left to say)")])
        return self.queue.pop(0)


class _FakeClient:
    def __init__(self, queue):
        self.messages = _Messages(queue)


def run_with(user, project, prompt, turns, **kw):
    """Run the agent against a scripted model. Returns (result, status, calls)."""
    client = _FakeClient(script(*turns))
    with patch("anthropic.Anthropic", return_value=client), \
            patch("apps.economy.occ.anthropic", create=True):
        result, code = run_agent(user, project, prompt, **kw)
    return result, code, client.messages.calls


# --------------------------------------------------------------- tools
class PathSafetyTests(TestCase):
    """The containment story: there is no path out of a workspace."""

    def test_ordinary_paths_are_accepted(self):
        self.assertEqual(normalize_path("main.py"), "main.py")
        self.assertEqual(normalize_path("src/app/views.py"), "src/app/views.py")
        self.assertEqual(normalize_path("./main.py"), "main.py")
        self.assertEqual(normalize_path("a//b.py"), "a/b.py")

    def test_traversal_and_absolute_paths_are_refused(self):
        for bad in ("../secrets.py", "a/../../etc/passwd", "/etc/passwd",
                    "..", "../", "C:\\win", "a\\b", "", "   ", None,
                    "x" * 400, "sp ace.py", "semi;colon.py", "$(whoami)"):
            self.assertIsNone(normalize_path(bad), bad)


class ToolTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("dev", "d@e.com", "pw12345678")
        self.project = Project.objects.create(owner=self.user, name="app")
        self.ws = Workspace(self.project)

    def _file(self, path, content):
        return ProjectFile.objects.create(project=self.project, path=path, content=content)

    def test_list_files_on_an_empty_project_says_so(self):
        ok, text = self.ws.list_files()
        self.assertTrue(ok)
        self.assertIn("no files", text)

    def test_write_then_read_round_trips_with_line_numbers(self):
        ok, _ = self.ws.write_file("main.py", "a = 1\nb = 2\n")
        self.assertTrue(ok)
        ok, text = self.ws.read_file("main.py")
        self.assertTrue(ok)
        self.assertIn("    1\ta = 1", text)
        self.assertIn("    2\tb = 2", text)

    def test_read_paginates_and_says_how_to_continue(self):
        self._file("big.py", "\n".join(f"line{i}" for i in range(1, 51)))
        ok, text = self.ws.read_file("big.py", offset=1, limit=10)
        self.assertTrue(ok)
        self.assertIn("40 more lines", text)
        self.assertIn("offset=11", text)

    def test_write_refuses_to_clobber_a_file_it_has_not_read(self):
        self._file("main.py", "important")
        ok, text = self.ws.write_file("main.py", "gone")
        self.assertFalse(ok)
        self.assertIn("haven't read it", text)
        self.assertEqual(ProjectFile.objects.get(path="main.py").content, "important")
        # reading it first unlocks the write
        self.ws.read_file("main.py")
        ok, _ = self.ws.write_file("main.py", "replaced")
        self.assertTrue(ok)
        self.assertEqual(ProjectFile.objects.get(path="main.py").content, "replaced")

    def test_edit_requires_an_exact_unique_match(self):
        self._file("app.py", "x = 1\ny = 1\n")
        ok, text = self.ws.edit_file("app.py", "z = 1", "z = 2")
        self.assertFalse(ok)
        self.assertIn("isn't in", text)

        ok, text = self.ws.edit_file("app.py", "= 1", "= 2")
        self.assertFalse(ok)
        self.assertIn("appears 2 times", text)

        ok, _ = self.ws.edit_file("app.py", "x = 1", "x = 42")
        self.assertTrue(ok)
        self.assertEqual(ProjectFile.objects.get(path="app.py").content, "x = 42\ny = 1\n")

    def test_edit_replace_all(self):
        self._file("app.py", "a\na\na\n")
        ok, text = self.ws.edit_file("app.py", "a", "b", replace_all=True)
        self.assertTrue(ok)
        self.assertIn("3 replacement", text)
        self.assertEqual(ProjectFile.objects.get(path="app.py").content, "b\nb\nb\n")

    def test_edit_refuses_a_no_op(self):
        self._file("app.py", "a\n")
        ok, text = self.ws.edit_file("app.py", "a", "a")
        self.assertFalse(ok)
        self.assertIn("identical", text)

    def test_search_reports_path_and_line(self):
        self._file("a.py", "import os\nprint(os)\n")
        self._file("b.js", "const os = 1\n")
        ok, text = self.ws.search("os")
        self.assertTrue(ok)
        self.assertIn("a.py:1", text)
        self.assertIn("b.js:1", text)

        ok, text = self.ws.search("os", glob="**/*.py")
        self.assertIn("a.py:1", text)
        self.assertNotIn("b.js", text)

        ok, text = self.ws.search("nothinghere")
        self.assertTrue(ok)
        self.assertIn("No matches", text)

    def test_search_reports_a_bad_regex_instead_of_raising(self):
        ok, text = self.ws.search("(unclosed")
        self.assertFalse(ok)
        self.assertIn("valid regular expression", text)

    def test_rename_and_delete(self):
        self._file("old.py", "x")
        ok, _ = self.ws.rename_file("old.py", "new/newer.py")
        self.assertTrue(ok)
        self.assertTrue(ProjectFile.objects.filter(path="new/newer.py").exists())
        ok, text = self.ws.rename_file("missing.py", "x.py")
        self.assertFalse(ok)
        ok, _ = self.ws.delete_file("new/newer.py")
        self.assertTrue(ok)
        self.assertFalse(ProjectFile.objects.filter(project=self.project).exists())

    def test_file_count_is_capped(self):
        for i in range(MAX_FILES):
            self._file(f"f{i}.py", "x")
        ok, text = self.ws.write_file("one-more.py", "x")
        self.assertFalse(ok)
        self.assertIn(str(MAX_FILES), text)

    def test_changed_paths_are_tracked_in_order(self):
        self.ws.write_file("a.py", "1")
        self.ws.write_file("b.py", "2")
        self.ws.edit_file("a.py", "1", "3")
        self.assertEqual(self.ws.changed, ["a.py", "b.py"])

    def test_run_tool_rejects_unknown_tools_and_bad_args(self):
        ok, text = run_tool(self.ws, "rm_rf", {})
        self.assertFalse(ok)
        self.assertIn("no tool called", text)
        # unexpected kwargs are filtered, not fatal
        ok, _ = run_tool(self.ws, "write_file",
                         {"path": "x.py", "content": "1", "sudo": True})
        self.assertTrue(ok)
        # a genuinely missing required arg reports instead of raising
        ok, text = run_tool(self.ws, "edit_file", {"path": "x.py"})
        self.assertFalse(ok)
        self.assertIn("Wrong arguments", text)

    def test_a_tool_cannot_reach_another_members_project(self):
        other = User.objects.create_user("other", "o@e.com", "pw12345678")
        theirs = Project.objects.create(owner=other, name="theirs")
        ProjectFile.objects.create(project=theirs, path="secret.py", content="TOKEN")
        ok, text = self.ws.read_file("secret.py")
        self.assertFalse(ok)
        ok, text = self.ws.search("TOKEN")
        self.assertNotIn("secret.py", text)


# --------------------------------------------------------------- the loop
class AgentLoopTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("coder", "c@e.com", "pw12345678")
        w = wallet_for(self.user)
        w.money_cents = 5_000
        w.save()
        self.project = Project.objects.create(owner=self.user, name="app")

    def test_a_single_turn_with_no_tools_just_answers(self):
        result, code, calls = run_with(
            self.user, self.project, "what is this project?",
            [[text_block("🧠 Nothing in it yet — want me to scaffold it?")]],
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["stopped"], STOP_DONE)
        self.assertEqual(result["steps"], 1)
        self.assertIn("scaffold", result["text"])
        self.assertEqual(result["tool_calls"], [])
        self.assertEqual(len(calls), 1)

    def test_the_loop_executes_a_tool_and_feeds_the_result_back(self):
        """This is the whole point: chat can't do this in one turn."""
        result, code, calls = run_with(
            self.user, self.project, "create main.py that prints hi",
            [
                [tool_block("write_file", {"path": "main.py", "content": "print('hi')\n"})],
                [text_block("🔥 Created main.py.")],
            ],
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["steps"], 2)
        self.assertEqual(result["changed"], ["main.py"])
        self.assertEqual(ProjectFile.objects.get(project=self.project, path="main.py").content,
                         "print('hi')\n")
        # the tool result was handed back to the model on the second call
        second = calls[1]["messages"]
        self.assertEqual(second[-2]["role"], "assistant")
        self.assertEqual(second[-1]["content"][0]["type"], "tool_result")
        self.assertIn("Created main.py", second[-1]["content"][0]["content"])

    def test_a_realistic_multi_step_run_searches_reads_edits_and_verifies(self):
        ProjectFile.objects.create(
            project=self.project, path="api/auth.py",
            content="def login(request):\n    return ok(request)\n",
        )
        result, code, _ = run_with(
            self.user, self.project, "add a rate limit to login",
            [
                [tool_block("search", {"pattern": "def login"}, id="a")],
                [tool_block("read_file", {"path": "api/auth.py"}, id="b")],
                [tool_block("edit_file", {
                    "path": "api/auth.py",
                    "old_string": "def login(request):",
                    "new_string": "@rate_limit(5)\ndef login(request):",
                }, id="c")],
                [tool_block("read_file", {"path": "api/auth.py"}, id="d")],
                [text_block("✅ Rate limited login to 5/min.")],
            ],
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["steps"], 5)
        self.assertEqual([c["name"] for c in result["tool_calls"]],
                         ["search", "read_file", "edit_file", "read_file"])
        self.assertTrue(all(c["ok"] for c in result["tool_calls"]))
        self.assertEqual(result["changed"], ["api/auth.py"])
        self.assertIn("@rate_limit(5)",
                      ProjectFile.objects.get(path="api/auth.py").content)

    def test_two_tool_calls_in_one_turn_both_run(self):
        result, _, calls = run_with(
            self.user, self.project, "make two files",
            [
                [tool_block("write_file", {"path": "a.py", "content": "1"}, id="x"),
                 tool_block("write_file", {"path": "b.py", "content": "2"}, id="y")],
                [text_block("done")],
            ],
        )
        self.assertEqual(result["changed"], ["a.py", "b.py"])
        self.assertEqual(len(calls[1]["messages"][-1]["content"]), 2)

    def test_a_failing_tool_is_reported_to_the_model_as_an_error(self):
        result, _, calls = run_with(
            self.user, self.project, "read a file that isn't there",
            [
                [tool_block("read_file", {"path": "nope.py"})],
                [text_block("That file doesn't exist yet.")],
            ],
        )
        self.assertFalse(result["tool_calls"][0]["ok"])
        self.assertTrue(calls[1]["messages"][-1]["content"][0]["is_error"])

    def test_the_step_cap_stops_a_loop_that_never_converges(self):
        membership_for(self.user).tier = TIER_FREE
        turns = [[tool_block("list_files", {}, id=f"t{i}")] for i in range(30)]
        result, code, calls = run_with(self.user, self.project, "loop forever", turns)
        self.assertEqual(result["stopped"], STOP_MAX_STEPS)
        self.assertEqual(result["steps"], MAX_STEPS[TIER_FREE])
        self.assertEqual(len(calls), MAX_STEPS[TIER_FREE])
        self.assertIn("keep going", result["text"])
        self.assertEqual(code, 200)

    def test_higher_tiers_get_more_steps(self):
        self.assertEqual(max_steps_for(self.user), MAX_STEPS[TIER_FREE])
        m = membership_for(self.user)
        m.tier = TIER_STATZ
        m.save(update_fields=["tier", "updated_at"])
        self.assertEqual(max_steps_for(self.user), MAX_STEPS[TIER_STATZ])
        self.assertGreater(MAX_STEPS[TIER_STATZ], MAX_STEPS[TIER_FREE])

    def test_max_steps_can_be_lowered_per_run_but_not_raised_past_the_ceiling(self):
        turns = [[tool_block("list_files", {}, id=f"t{i}")] for i in range(5)]
        result, _, calls = run_with(self.user, self.project, "look around", turns, max_steps=2)
        self.assertEqual(result["steps"], 2)
        self.assertEqual(len(calls), 2)

    def test_each_step_is_billed_and_the_run_stops_when_money_runs_out(self):
        w = wallet_for(self.user)
        w.money_cents = 3          # corey-gpt is 1c per step
        w.promptz = 0
        w.save()
        turns = [[tool_block("list_files", {}, id=f"t{i}")] for i in range(10)]
        result, code, _ = run_with(self.user, self.project, "keep looking", turns)
        self.assertEqual(result["stopped"], STOP_BUDGET)
        self.assertEqual(result["steps"], 3)
        self.assertEqual(result["cost_cents"], 3)
        self.assertEqual(wallet_for(self.user).money_cents, 0)

    def test_a_broke_member_cannot_start_a_run(self):
        w = wallet_for(self.user)
        w.money_cents = 0
        w.promptz = 0
        w.save()
        result, code, _ = run_with(self.user, self.project, "do a thing",
                                   [[text_block("hi")]])
        self.assertEqual(code, 402)
        self.assertEqual(result["stopped"], STOP_BUDGET)
        self.assertEqual(result["steps"], 0)

    def test_a_model_failure_keeps_the_edits_it_already_made(self):
        """The files are already written. Reporting a 503 and letting the client
        throw the result away would lose real work."""
        client = _FakeClient(script(
            [tool_block("write_file", {"path": "kept.py", "content": "1"})],
        ))
        original = client.messages.create
        state = {"n": 0}

        def flaky(**kwargs):
            state["n"] += 1
            if state["n"] > 1:
                raise RuntimeError("upstream 529")
            return original(**kwargs)

        client.messages.create = flaky
        with patch("anthropic.Anthropic", return_value=client):
            result, code = run_agent(self.user, self.project, "write a file")

        self.assertEqual(result["stopped"], STOP_ERROR)
        self.assertEqual(code, 200)                      # work landed
        self.assertEqual(result["changed"], ["kept.py"])
        self.assertTrue(ProjectFile.objects.filter(path="kept.py").exists())

    def test_dry_run_investigates_but_refuses_to_write(self):
        ProjectFile.objects.create(project=self.project, path="app.py", content="x = 1\n")
        result, code, calls = run_with(
            self.user, self.project, "plan a refactor",
            [
                [tool_block("read_file", {"path": "app.py"}, id="a")],
                [tool_block("write_file", {"path": "app.py", "content": "y = 2\n"}, id="b")],
                [text_block("Here's the plan.")],
            ],
            dry_run=True,
        )
        self.assertEqual(code, 200)
        self.assertEqual(result["changed"], [])
        self.assertEqual(ProjectFile.objects.get(path="app.py").content, "x = 1\n")
        write = next(c for c in result["tool_calls"] if c["name"] == "write_file")
        self.assertFalse(write["ok"])
        self.assertIn("dry run", write["result"])
        self.assertIn("DRY RUN", calls[0]["system"])

    def test_every_run_is_recorded_for_audit(self):
        run_with(self.user, self.project, "make a file",
                 [[tool_block("write_file", {"path": "a.py", "content": "1"})],
                  [text_block("done")]])
        run = AgentRun.objects.get()
        self.assertEqual(run.project, self.project)
        self.assertEqual(run.steps, 2)
        self.assertEqual(run.changed, ["a.py"])
        self.assertEqual(run.tool_calls[0]["name"], "write_file")
        self.assertEqual(run.cost_cents, 2)
        self.assertEqual(run.stopped, STOP_DONE)

    def test_big_tool_inputs_are_summarised_in_the_transcript(self):
        run_with(self.user, self.project, "write something long",
                 [[tool_block("write_file", {"path": "big.py", "content": "x" * 5000})],
                  [text_block("done")]])
        run = AgentRun.objects.get()
        self.assertEqual(run.tool_calls[0]["input"]["content"], "<5000 chars>")
        self.assertEqual(run.tool_calls[0]["input"]["path"], "big.py")

    def test_the_agent_is_given_the_tools_and_the_current_file_list(self):
        ProjectFile.objects.create(project=self.project, path="app.py", content="x = 1")
        _, _, calls = run_with(self.user, self.project, "hi", [[text_block("hey")]])
        self.assertEqual([t["name"] for t in calls[0]["tools"]], TOOL_NAMES)
        system = calls[0]["system"]
        self.assertIn("app.py", system)
        self.assertIn("CODING-AGENT MODE", system)
        # and told plainly that it cannot run anything
        self.assertIn("CANNOT RUN CODE", system)

    def test_the_system_prompt_says_the_project_is_empty_when_it_is(self):
        self.assertIn("empty project", build_system(self.project))

    def test_history_is_carried_into_the_run(self):
        _, _, calls = run_with(
            self.user, self.project, "and now the tests",
            [[text_block("ok")]],
            history=[{"role": "user", "text": "write the model"},
                     {"role": "occ", "text": "done"}],
        )
        msgs = calls[0]["messages"]
        self.assertEqual(msgs[0]["content"], "write the model")
        self.assertEqual(msgs[1]["role"], "assistant")
        self.assertEqual(msgs[-1]["content"], "and now the tests")

    def test_no_llm_backend_reports_503_without_charging(self):
        w = wallet_for(self.user)
        before = w.money_cents
        with patch.dict("sys.modules", {"anthropic": None}):
            result, code = run_agent(self.user, self.project, "do it")
        self.assertEqual(code, 503)
        self.assertEqual(result["stopped"], STOP_ERROR)
        self.assertEqual(wallet_for(self.user).money_cents, before)


# --------------------------------------------------------------- endpoints
class ProjectEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("dev", "d@e.com", "pw12345678")
        self.client.force_authenticate(self.user)

    def test_create_list_and_delete_a_project(self):
        resp = self.client.post("/api/economy/occ/projects/", {"name": "beatmaker"},
                                format="json")
        self.assertEqual(resp.status_code, 201)
        pk = resp.data["project"]["id"]

        listing = self.client.get("/api/economy/occ/projects/").data
        self.assertEqual(listing["projects"][0]["name"], "beatmaker")
        self.assertFalse(listing["can_run_code"])
        self.assertEqual([t["name"] for t in listing["tools"]], TOOL_NAMES)

        self.assertEqual(self.client.delete(f"/api/economy/occ/projects/{pk}/").status_code, 200)
        self.assertFalse(Project.objects.exists())

    def test_a_duplicate_name_is_a_conflict_not_a_500(self):
        self.client.post("/api/economy/occ/projects/", {"name": "app"}, format="json")
        resp = self.client.post("/api/economy/occ/projects/", {"name": "app"}, format="json")
        self.assertEqual(resp.status_code, 409)

    def test_files_can_be_written_and_read_by_hand(self):
        pk = self.client.post("/api/economy/occ/projects/", {"name": "app"},
                              format="json").data["project"]["id"]
        resp = self.client.post(f"/api/economy/occ/projects/{pk}/files/",
                                {"path": "src/main.py", "content": "print(1)"}, format="json")
        self.assertEqual(resp.status_code, 201)
        got = self.client.get(f"/api/economy/occ/projects/{pk}/files/?path=src/main.py")
        self.assertEqual(got.data["content"], "print(1)")
        self.assertEqual(
            self.client.delete(f"/api/economy/occ/projects/{pk}/files/?path=src/main.py").status_code,
            200,
        )

    def test_a_traversal_path_is_refused_by_the_endpoint_too(self):
        pk = self.client.post("/api/economy/occ/projects/", {"name": "app"},
                              format="json").data["project"]["id"]
        resp = self.client.post(f"/api/economy/occ/projects/{pk}/files/",
                                {"path": "../../settings.py", "content": "x"}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_another_members_project_is_a_404_not_a_403(self):
        other = User.objects.create_user("other", "o@e.com", "pw12345678")
        theirs = Project.objects.create(owner=other, name="theirs")
        for url in (f"/api/economy/occ/projects/{theirs.id}/",
                    f"/api/economy/occ/projects/{theirs.id}/files/",
                    f"/api/economy/occ/projects/{theirs.id}/runs/"):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertEqual(
            self.client.post(f"/api/economy/occ/projects/{theirs.id}/agent/",
                             {"prompt": "read everything"}, format="json").status_code, 404)

    def test_the_agent_endpoint_needs_a_prompt(self):
        pk = self.client.post("/api/economy/occ/projects/", {"name": "app"},
                              format="json").data["project"]["id"]
        resp = self.client.post(f"/api/economy/occ/projects/{pk}/agent/", {}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_the_agent_endpoint_runs_the_loop_and_reports_the_run(self):
        w = wallet_for(self.user)
        w.money_cents = 100
        w.save()
        pk = self.client.post("/api/economy/occ/projects/", {"name": "app"},
                              format="json").data["project"]["id"]
        client = _FakeClient(script(
            [tool_block("write_file", {"path": "a.py", "content": "1"})],
            [text_block("🔥 made it")],
        ))
        with patch("anthropic.Anthropic", return_value=client):
            resp = self.client.post(f"/api/economy/occ/projects/{pk}/agent/",
                                    {"prompt": "make a.py"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["changed"], ["a.py"])
        self.assertEqual(resp.data["steps"], 2)

        runs = self.client.get(f"/api/economy/occ/projects/{pk}/runs/").data["runs"]
        self.assertEqual(runs[0]["changed"], ["a.py"])
        self.assertEqual(runs[0]["prompt"], "make a.py")

    def test_projects_need_a_login(self):
        self.assertEqual(APIClient().get("/api/economy/occ/projects/").status_code, 401)


class UndoTests(TestCase):
    """OCC has no git. It has snapshots, which is the part that matters: an
    agentic run makes several edits and any one of them can be wrong."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("coder", "c@e.com", "pw12345678")
        w = wallet_for(self.user)
        w.money_cents = 5_000
        w.save()
        self.client.force_authenticate(self.user)
        self.project = Project.objects.create(owner=self.user, name="app")

    def _file(self, path, content):
        return ProjectFile.objects.create(project=self.project, path=path, content=content)

    def test_a_run_that_changes_files_offers_an_undo(self):
        self._file("app.py", "original\n")
        result, _, _ = run_with(
            self.user, self.project, "rewrite app.py",
            [[tool_block("read_file", {"path": "app.py"}, id="a")],
             [tool_block("write_file", {"path": "app.py", "content": "ruined\n"}, id="b")],
             [text_block("done")]],
        )
        self.assertEqual(result["changed"], ["app.py"])
        self.assertIn("undo", result)
        self.assertEqual(result["undo"]["files"], 1)
        self.assertEqual(ProjectFile.objects.get(path="app.py").content, "ruined\n")

        resp = self.client.post(f"/api/economy/occ/projects/{self.project.id}/undo/",
                                {}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ProjectFile.objects.get(path="app.py").content, "original\n")

    def test_undo_removes_files_the_run_created(self):
        """A half-restore that leaves the agent's new file behind is the worst
        outcome — the workspace then matches neither state."""
        self._file("keep.py", "1\n")
        run_with(self.user, self.project, "add a file",
                 [[tool_block("write_file", {"path": "new.py", "content": "2\n"})],
                  [text_block("done")]])
        self.assertEqual(ProjectFile.objects.filter(project=self.project).count(), 2)

        self.client.post(f"/api/economy/occ/projects/{self.project.id}/undo/", {},
                         format="json")
        paths = set(ProjectFile.objects.filter(project=self.project).values_list("path", flat=True))
        self.assertEqual(paths, {"keep.py"})

    def test_undo_restores_a_deleted_file(self):
        self._file("gone.py", "important\n")
        run_with(self.user, self.project, "delete it",
                 [[tool_block("delete_file", {"path": "gone.py"})],
                  [text_block("done")]])
        self.assertFalse(ProjectFile.objects.filter(path="gone.py").exists())

        self.client.post(f"/api/economy/occ/projects/{self.project.id}/undo/", {},
                         format="json")
        self.assertEqual(ProjectFile.objects.get(path="gone.py").content, "important\n")

    def test_undo_is_itself_undoable(self):
        """An undo you can't undo is just a second way to lose work."""
        self._file("app.py", "v1\n")
        run_with(self.user, self.project, "change it",
                 [[tool_block("read_file", {"path": "app.py"}, id="a")],
                  [tool_block("write_file", {"path": "app.py", "content": "v2\n"}, id="b")],
                  [text_block("done")]])
        self.client.post(f"/api/economy/occ/projects/{self.project.id}/undo/", {},
                         format="json")
        self.assertEqual(ProjectFile.objects.get(path="app.py").content, "v1\n")

        # the newest snapshot is now the pre-undo state (v2)
        resp = self.client.post(f"/api/economy/occ/projects/{self.project.id}/undo/", {},
                                format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ProjectFile.objects.get(path="app.py").content, "v2\n")

    def test_a_run_that_changed_nothing_leaves_no_snapshot(self):
        self._file("app.py", "1\n")
        result, _, _ = run_with(self.user, self.project, "just look",
                               [[tool_block("list_files", {})], [text_block("nothing to do")]])
        self.assertEqual(result["changed"], [])
        self.assertNotIn("undo", result)
        self.assertEqual(ProjectSnapshot.objects.count(), 0)

    def test_a_dry_run_takes_no_snapshot(self):
        self._file("app.py", "1\n")
        run_with(self.user, self.project, "plan it",
                 [[tool_block("read_file", {"path": "app.py"})], [text_block("plan")]],
                 dry_run=True)
        self.assertEqual(ProjectSnapshot.objects.count(), 0)

    def test_an_empty_project_is_not_snapshotted(self):
        """Restoring to "nothing" is what deleting files already does, and it
        would push a real snapshot off the stack."""
        run_with(self.user, self.project, "start it",
                 [[tool_block("write_file", {"path": "a.py", "content": "1"})],
                  [text_block("done")]])
        self.assertEqual(ProjectSnapshot.objects.count(), 0)

    def test_the_undo_stack_is_listed_and_bounded(self):
        self._file("app.py", "0\n")
        for i in range(MAX_SNAPSHOTS + 4):
            take_snapshot(self.project, label=f"snap {i}")
        self.assertEqual(ProjectSnapshot.objects.filter(project=self.project).count(),
                         MAX_SNAPSHOTS)
        data = self.client.get(f"/api/economy/occ/projects/{self.project.id}/undo/").data
        self.assertEqual(len(data["snapshots"]), MAX_SNAPSHOTS)
        self.assertEqual(data["limit"], MAX_SNAPSHOTS)
        # the newest survived, the oldest fell off
        self.assertEqual(data["snapshots"][0]["label"], f"snap {MAX_SNAPSHOTS + 3}")

    def test_undoing_a_specific_snapshot(self):
        self._file("app.py", "v1\n")
        snap = take_snapshot(self.project, label="v1")
        ProjectFile.objects.filter(path="app.py").update(content="v9\n")
        resp = self.client.post(f"/api/economy/occ/projects/{self.project.id}/undo/",
                                {"snapshot_id": snap.id}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["restored_from"], snap.id)
        self.assertEqual(ProjectFile.objects.get(path="app.py").content, "v1\n")

    def test_nothing_to_undo_is_a_404(self):
        resp = self.client.post(f"/api/economy/occ/projects/{self.project.id}/undo/", {},
                                format="json")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("nothing to undo", resp.data["detail"])

    def test_another_members_snapshot_cannot_be_restored(self):
        other = User.objects.create_user("other", "o@e.com", "pw12345678")
        theirs = Project.objects.create(owner=other, name="theirs")
        ProjectFile.objects.create(project=theirs, path="x.py", content="1")
        snap = take_snapshot(theirs, label="theirs")
        # wrong project in the URL -> 404
        self.assertEqual(
            self.client.post(f"/api/economy/occ/projects/{theirs.id}/undo/", {},
                             format="json").status_code, 404)
        # right project, someone else's snapshot id -> also 404
        self._file("mine.py", "1")
        take_snapshot(self.project, label="mine")
        resp = self.client.post(f"/api/economy/occ/projects/{self.project.id}/undo/",
                                {"snapshot_id": snap.id}, format="json")
        self.assertEqual(resp.status_code, 404)

    def test_the_run_history_reports_which_runs_are_undoable(self):
        self._file("app.py", "1\n")
        run_with(self.user, self.project, "change it",
                 [[tool_block("read_file", {"path": "app.py"}, id="a")],
                  [tool_block("write_file", {"path": "app.py", "content": "2\n"}, id="b")],
                  [text_block("done")]])
        runs = self.client.get(f"/api/economy/occ/projects/{self.project.id}/runs/").data["runs"]
        self.assertIsNotNone(runs[0]["undo"])
        self.assertEqual(runs[0]["undo"]["files"], 1)
