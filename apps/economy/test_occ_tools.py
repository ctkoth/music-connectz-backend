"""The tools OCC uses to change code.

`occ.py` made one `messages.create()` call with no `tools=`, which is the whole
difference between explaining code and changing it. These tests cover the other
half — and they lean hardest on the two places this can go wrong quietly:

* **the path gate**, because these rows become real files in a sandbox, so a
  path checked in the view and not in the tool is a path that isn't checked;
* **failure shape**, because a tool that raises makes the MEMBER fix a mistake
  the MODEL made. Every bad input has to come back as a readable error the model
  can act on.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.economy.catalog import OCC_MAX_FILE_CHARS, occ_file_limits
from apps.economy.models import OccFile, TIER_FREE, membership_for
from apps.economy.occ_tools import (
    CHANGES_FILES,
    MAX_READ_CHARS,
    TOOLS,
    TOOL_NAMES,
    run_tool,
)

User = get_user_model()
PW = "hunter2hunter2"


class Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("coder", "c@e.com", PW)
        membership_for(self.user)

    def file(self, path, content="", project="main"):
        return OccFile.objects.create(user=self.user, project=project,
                                      path=path, content=content)

    def call(self, name, **args):
        return run_tool(self.user, name, args)


class TheDefinitionsAreUsable(TestCase):
    def test_every_tool_describes_itself_properly(self):
        for tool in TOOLS:
            with self.subTest(tool=tool["name"]):
                # Under-description is the most common tool-use failure. Three
                # sentences is the documented floor; these are the contract the
                # model reads before it ever calls anything.
                self.assertGreaterEqual(len(tool["description"]), 200)
                self.assertIn("input_schema", tool)
                self.assertEqual(tool["input_schema"]["type"], "object")
                for prop in tool["input_schema"]["properties"].values():
                    self.assertIn("description", prop)

    def test_the_tools_that_change_files_are_all_declared(self):
        # The loop reads CHANGES_FILES to decide what needs approval, so a
        # writing tool missing from it edits a member's code with nobody asked.
        self.assertTrue(CHANGES_FILES <= TOOL_NAMES)
        self.assertEqual(CHANGES_FILES, {"write", "edit"})

    def test_read_only_tools_are_not_marked_as_changing_anything(self):
        for name in ("read", "glob", "grep"):
            self.assertNotIn(name, CHANGES_FILES)


class ReadTests(Base):
    def test_reading_a_file_returns_it_with_line_numbers(self):
        self.file("main.py", "one\ntwo")
        out = self.call("read", path="main.py")
        self.assertTrue(out["ok"])
        self.assertIn("one", out["content"])
        self.assertIn("1", out["content"])

    def test_a_missing_file_is_an_error_not_an_empty_file(self):
        out = self.call("read", path="nope.py")
        self.assertFalse(out["ok"])
        self.assertIn("no file", out["error"].lower())

    def test_a_truncated_read_says_so(self):
        # A model that edits the part of a file it couldn't see is confidently
        # wrong and has no way to know.
        self.file("big.py", "x" * (MAX_READ_CHARS + 500))
        out = self.call("read", path="big.py")
        self.assertTrue(out["ok"])
        self.assertIn("truncated", out)
        self.assertIn(f"{MAX_READ_CHARS:,}", out["truncated"])

    def test_a_short_read_does_not_claim_truncation(self):
        self.file("small.py", "hi")
        self.assertNotIn("truncated", self.call("read", path="small.py"))


class WriteTests(Base):
    def test_writing_creates_a_file_that_persists(self):
        out = self.call("write", path="src/main.py", content="print(1)")
        self.assertTrue(out["ok"])
        self.assertTrue(out["created"])
        self.assertEqual(
            OccFile.objects.get(user=self.user, path="src/main.py").content, "print(1)")

    def test_writing_over_a_file_replaces_it_and_says_it_was_not_new(self):
        self.file("main.py", "old")
        out = self.call("write", path="main.py", content="new")
        self.assertTrue(out["ok"])
        self.assertFalse(out["created"])
        self.assertEqual(OccFile.objects.get(user=self.user, path="main.py").content, "new")
        self.assertEqual(OccFile.objects.filter(user=self.user, path="main.py").count(), 1)

    def test_a_file_over_the_character_cap_is_refused(self):
        out = self.call("write", path="big.py", content="x" * (OCC_MAX_FILE_CHARS + 1))
        self.assertFalse(out["ok"])
        self.assertFalse(OccFile.objects.filter(user=self.user).exists())

    def test_the_file_count_ceiling_holds(self):
        cap = occ_file_limits(TIER_FREE)["files_per_project"]
        for i in range(cap):
            self.file(f"f{i}.py")
        out = self.call("write", path="one-too-many.py", content="x")
        self.assertFalse(out["ok"])
        self.assertIn("limit", out["error"].lower())
        self.assertEqual(OccFile.objects.filter(user=self.user).count(), cap)

    def test_the_ceiling_does_not_block_editing_files_that_already_exist(self):
        # Otherwise a member at their limit can never fix anything — the cap
        # would take away the files they already have.
        cap = occ_file_limits(TIER_FREE)["files_per_project"]
        for i in range(cap):
            self.file(f"f{i}.py", "old")
        out = self.call("write", path="f0.py", content="new")
        self.assertTrue(out["ok"])

    def test_content_that_is_not_a_string_is_refused(self):
        self.assertFalse(self.call("write", path="a.py", content={"nope": 1})["ok"])


class EditTests(Base):
    def test_a_unique_match_is_replaced(self):
        self.file("main.py", "alpha\nbeta\ngamma")
        out = self.call("edit", path="main.py", old="beta", new="BETA")
        self.assertTrue(out["ok"])
        self.assertEqual(
            OccFile.objects.get(user=self.user, path="main.py").content,
            "alpha\nBETA\ngamma")

    def test_an_ambiguous_edit_is_refused_and_changes_nothing(self):
        # Landing in the wrong one of three identical blocks is a bug the member
        # finds much later. Refusing beats guessing.
        self.file("main.py", "x = 1\nx = 1\nx = 1")
        out = self.call("edit", path="main.py", old="x = 1", new="x = 2")
        self.assertFalse(out["ok"])
        self.assertIn("3 times", out["error"])
        self.assertEqual(
            OccFile.objects.get(user=self.user, path="main.py").content,
            "x = 1\nx = 1\nx = 1")

    def test_a_missing_match_is_refused_with_a_usable_reason(self):
        self.file("main.py", "alpha")
        out = self.call("edit", path="main.py", old="omega", new="x")
        self.assertFalse(out["ok"])
        self.assertIn("whitespace", out["error"].lower())

    def test_editing_a_file_that_does_not_exist_points_at_write(self):
        out = self.call("edit", path="nope.py", old="a", new="b")
        self.assertFalse(out["ok"])
        self.assertIn("write", out["error"].lower())

    def test_an_empty_old_is_refused(self):
        self.file("main.py", "alpha")
        self.assertFalse(self.call("edit", path="main.py", old="", new="x")["ok"])

    def test_an_edit_that_would_burst_the_cap_is_refused(self):
        self.file("main.py", "seed")
        out = self.call("edit", path="main.py", old="seed",
                       new="x" * (OCC_MAX_FILE_CHARS + 1))
        self.assertFalse(out["ok"])
        self.assertEqual(
            OccFile.objects.get(user=self.user, path="main.py").content, "seed")


class GlobTests(Base):
    def setUp(self):
        super().setUp()
        self.file("main.py", "a")
        self.file("src/app.py", "bb")
        self.file("src/ui/page.jsx", "ccc")

    def test_a_pattern_matches_across_directories(self):
        out = self.call("glob", pattern="*.py")
        paths = {f["path"] for f in out["files"]}
        self.assertEqual(paths, {"main.py", "src/app.py"})

    def test_no_pattern_lists_everything(self):
        self.assertEqual(self.call("glob")["count"], 3)

    def test_glob_returns_sizes_but_never_contents(self):
        out = self.call("glob", pattern="*.py")
        for entry in out["files"]:
            self.assertIn("chars", entry)
            self.assertNotIn("content", entry)

    def test_a_directory_prefix_matches_what_is_under_it(self):
        paths = {f["path"] for f in self.call("glob", pattern="src")["files"]}
        self.assertIn("src/app.py", paths)


class GrepTests(Base):
    def setUp(self):
        super().setUp()
        self.file("main.py", "import os\nprint(os)")
        self.file("src/app.py", "import sys")

    def test_matches_come_back_with_path_and_line_number(self):
        out = self.call("grep", pattern=r"^import")
        self.assertEqual(out["count"], 2)
        self.assertEqual({m["path"] for m in out["matches"]}, {"main.py", "src/app.py"})
        self.assertTrue(all(m["line"] >= 1 for m in out["matches"]))

    def test_a_glob_filter_narrows_the_search(self):
        out = self.call("grep", pattern="import", glob="src/*")
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["matches"][0]["path"], "src/app.py")

    def test_a_broken_regex_is_the_models_error_to_fix_not_a_crash(self):
        out = self.call("grep", pattern="(unclosed")
        self.assertFalse(out["ok"])
        self.assertIn("regular expression", out["error"])

    def test_an_empty_pattern_is_refused(self):
        self.assertFalse(self.call("grep", pattern="")["ok"])


class TheGateHoldsInsideTheToolsToo(Base):
    """The path check lives in the executor, not only in whatever calls it."""

    def test_every_tool_refuses_a_traversal(self):
        self.file("main.py", "seed")
        for name, args in (
            ("read", {"path": "../../etc/passwd"}),
            ("write", {"path": "../escape.py", "content": "x"}),
            ("edit", {"path": "../main.py", "old": "seed", "new": "x"}),
        ):
            with self.subTest(tool=name):
                out = run_tool(self.user, name, args)
                self.assertFalse(out["ok"], f"{name} let a traversal through")
        self.assertEqual(OccFile.objects.filter(user=self.user).count(), 1)

    def test_a_bad_project_name_is_refused(self):
        for project in ("../other", "a/b", "a\\b", "x" * 500, "nul\x00"):
            with self.subTest(project=project):
                out = run_tool(self.user, "glob", {}, project=project)
                self.assertFalse(out["ok"], f"{project!r} was allowed through")

    def test_a_blank_project_means_the_default_one_consistently(self):
        # "" and "   " used to do different things — one defaulted to main, the
        # other was refused — which is a rule no member could have predicted.
        self.file("main.py", "seed")
        for project in ("", "   ", None):
            with self.subTest(project=project):
                out = run_tool(self.user, "glob", {}, project=project)
                self.assertTrue(out["ok"])
                self.assertEqual(out["count"], 1)

    def test_tools_never_reach_another_members_files(self):
        other = User.objects.create_user("other", "o@e.com", PW)
        membership_for(other)
        OccFile.objects.create(user=other, project="main", path="secret.py",
                               content="theirs")
        self.assertFalse(self.call("read", path="secret.py")["ok"])
        self.assertEqual(self.call("glob")["count"], 0)
        self.assertEqual(self.call("grep", pattern="theirs")["count"], 0)

    def test_a_write_does_not_leak_into_another_project(self):
        self.call("write", path="main.py", content="in-main")
        self.assertEqual(
            OccFile.objects.filter(user=self.user, project="main").count(), 1)
        self.assertEqual(
            OccFile.objects.filter(user=self.user, project="other").count(), 0)


class UnknownToolsFailSafely(Base):
    def test_a_tool_that_does_not_exist_is_an_error_not_an_exception(self):
        out = run_tool(self.user, "rm_rf", {"path": "/"})
        self.assertFalse(out["ok"])

    def test_missing_arguments_never_raise(self):
        # The model supplies these, so every shape it can get wrong has to come
        # back as a readable error rather than a 500 the member sees.
        for name in sorted(TOOL_NAMES):
            with self.subTest(tool=name):
                out = run_tool(self.user, name, {})
                self.assertIn("ok", out)
                if not out["ok"]:
                    self.assertTrue(out["error"])

    def test_none_arguments_never_raise(self):
        for name in sorted(TOOL_NAMES):
            with self.subTest(tool=name):
                self.assertIn("ok", run_tool(self.user, name, None))
