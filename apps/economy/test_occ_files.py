"""FileZ — the filesystem OCC can hold between turns.

OCC's editor held one string in React state, so nothing it wrote survived the
reply that wrote it. `OccFile` is the store that replaces it, and `path` is the
part that has to be right BEFORE anything writes to it: these rows get
materialised into a sandbox as real files, so an unchecked path here is a
traversal there, written to the database weeks earlier and fired later.

The path tests are deliberately exhaustive. A traversal that only fails on the
one spelling somebody thought of is not a defence — it is a defence against
that spelling.
"""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.economy.catalog import (
    OCC_MAX_FILE_CHARS,
    OCC_MAX_PATH_CHARS,
    OCC_MAX_PROJECT_NAME_CHARS,
    OCC_PROJECTS,
    OCC_PROJECT_FILES,
    occ_file_limits,
)
from apps.economy.models import (
    TIER_FREE,
    TIER_PREMIUM,
    TIER_STATZ,
    OccFile,
    membership_for,
    normalize_occ_path,
)

User = get_user_model()
PW = "hunter2hunter2"


class ThePathGateRefusesEscape(TestCase):
    """Everything that could resolve to somewhere outside the project root."""

    def test_dot_dot_is_refused_however_it_is_spelled(self):
        for path in (
            "../etc/passwd",
            "..",
            "src/../../etc/passwd",
            "src/../../../etc/passwd",
            "a/b/../../../c",
            "./../../etc/passwd",
            "src/..",
            "..\\..\\windows\\system32",   # backslashes normalise, then get caught
        ):
            with self.subTest(path=path):
                self.assertIsNone(normalize_occ_path(path),
                                  f"{path!r} was allowed through")

    def test_absolute_paths_and_drive_letters_are_refused_or_made_relative(self):
        # A leading slash is stripped rather than refused: "/main.py" plainly
        # means the project's own main.py, and refusing it would be pedantry.
        self.assertEqual(normalize_occ_path("/main.py"), "main.py")
        self.assertEqual(normalize_occ_path("///src//main.py"), "src/main.py")
        # A drive letter is a different filesystem, not a path in this one.
        self.assertIsNone(normalize_occ_path("C:/windows/system32"))
        self.assertIsNone(normalize_occ_path("C:\\windows\\system32"))

    def test_nul_bytes_are_refused(self):
        # A NUL truncates the path in C-level filesystem calls, so a name that
        # looks safe in Python can be a different name on disk.
        self.assertIsNone(normalize_occ_path("main.py\x00.txt"))
        self.assertIsNone(normalize_occ_path("\x00"))

    def test_empty_and_meaningless_paths_are_refused(self):
        for path in ("", "   ", None, "/", "///", ".", "./", "./."):
            with self.subTest(path=path):
                self.assertIsNone(normalize_occ_path(path))

    def test_a_path_over_the_cap_is_refused(self):
        self.assertIsNone(normalize_occ_path("a" * (OCC_MAX_PATH_CHARS + 1)))
        self.assertEqual(normalize_occ_path("a" * OCC_MAX_PATH_CHARS),
                         "a" * OCC_MAX_PATH_CHARS)

    def test_the_cap_matches_the_column_it_is_stored_in(self):
        # SQLite ignores varchar length and production is Postgres, so a cap
        # wider than the column is a bug that only appears live. See CLAUDE.md.
        column = OccFile._meta.get_field("path").max_length
        self.assertLessEqual(OCC_MAX_PATH_CHARS, column)
        project_column = OccFile._meta.get_field("project").max_length
        self.assertLessEqual(OCC_MAX_PROJECT_NAME_CHARS, project_column)


class ThePathGateKeepsRealPaths(TestCase):
    """The other half: it has to let actual source files through unchanged."""

    def test_ordinary_paths_survive(self):
        for raw, want in (
            ("main.py", "main.py"),
            ("src/apps/BossTake.jsx", "src/apps/BossTake.jsx"),
            ("  src/main.py  ", "src/main.py"),
            ("src\\apps\\main.py", "src/apps/main.py"),   # pasted from Windows
            ("src//apps///main.py", "src/apps/main.py"),
            ("src/./apps/main.py", "src/apps/main.py"),
            (".gitignore", ".gitignore"),                  # a leading dot is a name
            ("a/.hidden/b.txt", "a/.hidden/b.txt"),
            ("..hidden.py", "..hidden.py"),                # not a traversal segment
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_occ_path(raw), want)

    def test_two_spellings_of_one_file_normalise_to_one_path(self):
        # Otherwise the uniqueness constraint can be sidestepped by writing
        # "src//main.py", and `read` returns whichever row ordering picks.
        self.assertEqual(normalize_occ_path("src//main.py"),
                         normalize_occ_path("/src/./main.py"))


class TheStoreHoldsOneRowPerFile(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("coder", "c@e.com", PW)
        membership_for(self.user)

    def test_a_file_survives_the_turn_that_wrote_it(self):
        OccFile.objects.create(user=self.user, project="main",
                               path="main.py", content="print('hi')")
        again = OccFile.objects.get(user=self.user, project="main", path="main.py")
        self.assertEqual(again.content, "print('hi')")

    def test_the_same_path_twice_in_one_project_is_refused(self):
        OccFile.objects.create(user=self.user, project="main", path="main.py")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OccFile.objects.create(user=self.user, project="main", path="main.py")

    def test_the_same_path_in_a_different_project_is_a_different_file(self):
        OccFile.objects.create(user=self.user, project="main", path="main.py",
                               content="one")
        OccFile.objects.create(user=self.user, project="other", path="main.py",
                               content="two")
        self.assertEqual(OccFile.objects.filter(user=self.user, path="main.py").count(), 2)

    def test_one_members_files_are_not_anothers(self):
        other = User.objects.create_user("other", "o@e.com", PW)
        membership_for(other)
        OccFile.objects.create(user=self.user, project="main", path="main.py",
                               content="mine")
        OccFile.objects.create(user=other, project="main", path="main.py",
                               content="theirs")
        self.assertEqual(
            OccFile.objects.get(user=self.user, path="main.py").content, "mine")


class TheLimitsAreServedNotHardcoded(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("coder", "c@e.com", PW)

    def test_every_tier_has_a_ceiling(self):
        for tier in (TIER_FREE, TIER_PREMIUM, TIER_STATZ):
            with self.subTest(tier=tier):
                limits = occ_file_limits(tier)
                self.assertGreater(limits["files_per_project"], 0)
                self.assertGreater(limits["projects"], 0)
                self.assertEqual(limits["file_chars"], OCC_MAX_FILE_CHARS)

    def test_the_ladder_only_goes_up(self):
        # A tier that bought MORE and got LESS is the bug this app keeps
        # finding — the StatZ coach gate gave strangers a better deal than
        # paying members had.
        for table in (OCC_PROJECT_FILES, OCC_PROJECTS):
            with self.subTest(table=table):
                self.assertLess(table[TIER_FREE], table[TIER_PREMIUM])
                self.assertLess(table[TIER_PREMIUM], table[TIER_STATZ])

    def test_an_unknown_tier_gets_the_free_ceiling_not_an_error(self):
        # A lapsed subscription should fall back, never 500.
        limits = occ_file_limits("no-such-tier")
        self.assertEqual(limits["files_per_project"], OCC_PROJECT_FILES[TIER_FREE])

    def test_a_file_may_hold_a_real_source_file(self):
        # 200k characters is the same ceiling modal_sandbox already runs, so a
        # file OCC can store is a file OCC can run.
        from apps.economy.modal_sandbox import MAX_SOURCE_CHARS
        self.assertEqual(OCC_MAX_FILE_CHARS, MAX_SOURCE_CHARS)
