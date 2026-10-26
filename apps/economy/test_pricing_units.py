"""A price a member sets must say what it is per — and a new one cannot ship without saying so."""
import re
from pathlib import Path

from django.test import SimpleTestCase

from apps.economy import pricing_units as pu

MODELS = Path(__file__).with_name("models.py")
PRICE_FIELD = re.compile(r"^\s+(\w*(?:price|rate)\w*)\s*=\s*models\.(?:Positive)?(?:Integer|BigInteger|Decimal|Float)Field")
# Not prices: a rater's foreign key matches "rate", a count of takes rated, an energy rate, etc.
NOT_PRICES = {"takes_rated", "rate_limit"}


def _model_fields():
    cls, found = None, set()
    for line in MODELS.read_text().splitlines():
        m = re.match(r"class (\w+)\(", line)
        if m:
            cls = m.group(1)
        f = PRICE_FIELD.match(line)
        if f and cls and f.group(1) not in NOT_PRICES:
            found.add(f"{cls}.{f.group(1)}")
    return found


class EveryPriceDeclaresItsUnit(SimpleTestCase):
    def test_every_price_or_rate_field_is_declared(self):
        declared = set(pu.PRICES) | set(pu.SNAPSHOTS)
        # The skill price lives inside Profile.personas JSON, so it is declared by its path.
        undeclared = sorted(f for f in _model_fields() if f not in declared)
        self.assertEqual(undeclared, [], "a price field with no declared unit — add it to PRICES "
                                         "(member-set) or SNAPSHOTS (a record of what was paid)")

    def test_a_declaration_cannot_outlive_its_field(self):
        fields = _model_fields()
        stale = sorted(k for k in list(pu.PRICES) + list(pu.SNAPSHOTS)
                       if not k.startswith("Profile.personas") and k not in fields)
        self.assertEqual(stale, [], "declared, but no such field any more")

    def test_a_price_that_cannot_choose_its_unit_says_what_is_missing(self):
        for key, p in pu.PRICES.items():
            self.assertTrue(p["units"], key)
            if not p["choosable"]:
                self.assertIn(key, pu.GAPS, f"{key} offers no unit choice and lists no gap")
            if len(p["units"]) == 1:
                self.assertTrue(p.get("why") or p.get("gap"), f"{key} is single-unit with no reason")
        self.assertEqual(set(pu.GAPS), {k for k, p in pu.PRICES.items() if not p["choosable"]})

    def test_the_skill_price_unit_is_enforced_by_the_one_cleaner(self):
        from apps.economy.personaz import RATE_UNITS
        self.assertEqual(tuple(pu.PRICES["Profile.personas.skills.rate_cents"]["units"]), RATE_UNITS)
