"""Corey's rule, enforced: every credit spent buys a tangible, shareable,
understandable, lucrative, braggable or learnable outcome — and the module that
spends it SAYS which, in `credit_outcomes.CREDIT_OUTCOMES`.

This is a source walk, deliberately: a registry nobody is forced to update is a
wish. A new way to spend credits fails here until it is declared, and a
declaration for code that no longer spends fails too."""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy import credit_outcomes as C

ROOT = Path(__file__).resolve().parents[1]
CALL = re.compile(r"(?<![\w.])(" + "|".join(C.SPEND_PRIMITIVES) + r")\(")
ENERGY_DOWN = re.compile(r"\.energy\s*-=|energy=F\(\"energy\"\)\s*-|\.energy\s*=\s*have\s*-")


def _code(text):
    """Source with comments and docstring-ish prose dropped, definitions excluded:
    half the comments in this codebase NAME a primitive to explain it."""
    lines = []
    in_doc = False
    for line in text.splitlines():
        s = line.strip()
        if s.count('"""') % 2 == 1:
            in_doc = not in_doc
            continue
        if in_doc or s.startswith("#") or s.startswith("def "):
            continue
        lines.append(line.split("  #")[0])
    return "\n".join(lines)


def spending_modules():
    out = {}
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if "migrations" in rel.parts or path.name.startswith("test_") or path.name in ("tests.py", "credit_outcomes.py"):
            continue
        if rel.parts[0] == "economy" and path.stem == "models":
            continue                                        # where the primitives are DEFINED
        code = _code(path.read_text(encoding="utf-8"))
        if CALL.search(code) or ENERGY_DOWN.search(code):
            out[path.stem] = str(rel)
    return out


class CreditOutcomeAuditTests(TestCase):
    def test_every_module_that_spends_is_declared(self):
        undeclared = {m: p for m, p in spending_modules().items() if m not in C.CREDIT_OUTCOMES}
        self.assertEqual(undeclared, {},
                         "These modules spend credits but say nothing about what the spend buys. "
                         "Declare each in apps/economy/credit_outcomes.py (resource, buys, outcomes, "
                         "lands_in, free_way or no_free_way).")

    def test_no_declaration_outlives_the_code_it_describes(self):
        spending = spending_modules()
        stale = [m for m in C.CREDIT_OUTCOMES if m not in spending]
        self.assertEqual(stale, [], "Declared as spending, but nothing in the module spends any more.")

    def test_every_declaration_is_sound(self):
        for key, entry in C.CREDIT_OUTCOMES.items():
            self.assertEqual(C.validate(entry), [], key)

    def test_a_spend_with_no_outcome_is_refused_by_the_validator(self):
        bad = {"resource": "promptz", "buys": "A fee.", "outcomes": [], "lands_in": ["x"], "no_free_way": "n/a"}
        self.assertIn("outcomes", C.validate(bad))
        self.assertIn("free_way or no_free_way", C.validate({**bad, "outcomes": ["tangible"], "no_free_way": ""}))
        self.assertIn("outcomes", C.validate({**bad, "outcomes": ["profitable"]}))   # not one of the six

    def test_the_list_is_published_to_members_before_they_spend(self):
        u = get_user_model().objects.create_user("creditx", "c@e.com", "pw-Long-enough-1")
        c = APIClient()
        c.force_authenticate(u)
        d = c.get("/api/economy/creditz/").json()
        self.assertEqual(set(d["outcomes"]), set(C.OUTCOMES))
        by = {s["key"]: s for s in d["spends"]}
        self.assertIn("lucrative", by["sentencez"]["outcomes"])
        self.assertTrue(by["vocalcoach"]["buys"])
