"""LogicZ is what tells a member what this app HAS. It was lying four ways.

The modal renders `built: false` as a gold "not built yet". So a stale flag
does not merely fail to advertise a feature — it actively tells people not to
go looking for one that is right there. That is the five-trial-coaches failure
with a label on it.
"""
from django.test import TestCase

from .logicz import LOGICZ_TABS


def apps_by_name():
    return {a["name"]: a for tab in LOGICZ_TABS for a in tab["apps"]}


class WhatItClaimsIsBuiltTests(TestCase):

    def test_vybez_is_built_and_spelled_the_way_the_tab_is(self):
        """It was "VibeZ", built=False, while VybeZ has been a mounted tab
        with its own route. A member reading this was told not to look."""
        a = apps_by_name()
        self.assertIn("VybeZ", a)
        self.assertNotIn("VibeZ", a, "one spelling, and it is the tab's")
        self.assertTrue(a["VybeZ"]["built"])

    def test_personalitiez_is_built(self):
        a = apps_by_name()["PersonalitieZ"]
        self.assertTrue(a["built"])

    def test_religionz_is_built(self):
        # Same trap as PersonalitieZ right above it — a real, filterable
        # ProfileZ field is worth nothing if this screen still calls it
        # coming soon.
        a = apps_by_name()["ReligionZ"]
        self.assertTrue(a["built"])

    def test_languagez_is_built(self):
        a = apps_by_name()["LanguageZ"]
        self.assertTrue(a["built"])

    def test_both_extra_battle_kinds_are_built(self):
        """BattleEnterView accepts 1v1, freestyle and cypher, BattleZ offers
        all three in its picker, and each has a drawn icon."""
        a = apps_by_name()
        self.assertTrue(a["Freestyle"]["built"])
        self.assertTrue(a["Battle Cypher"]["built"])

    def test_the_battle_kinds_match_what_the_server_accepts(self):
        """The flag and the code cannot drift apart silently — this is the
        pairing that made them wrong in the first place."""
        import re

        from . import battlez
        src = open(battlez.__file__).read()
        m = re.search(r'kind if kind in \(([^)]*)\)', src)
        self.assertTrue(m, "the accepted battle kinds moved")
        accepted = set(re.findall(r'"([a-z0-9]+)"', m.group(1)))
        self.assertEqual(accepted, {"1v1", "freestyle", "cypher"})


class ItDoesNotPublishSomebodyElsesTrademarkTests(TestCase):
    """`personalityz.py`'s own docstring says, in as many words, that this is
    deliberately not called MBTI — and two member-facing strings called it
    that. `occ_spec.tabs_for` serves its `desc` to members too."""

    def test_logicz_says_nothing_about_mbti(self):
        text = " ".join(a["desc"] for a in apps_by_name().values())
        self.assertNotIn("MBTI", text.upper())

    def test_the_occ_tab_list_does_not_either(self):
        from .occ_spec import OCC_TABS
        text = " ".join(t.get("desc", "") for t in OCC_TABS)
        self.assertNotIn("MBTI", text.upper())

    def test_no_member_facing_module_reintroduces_it(self):
        """The whole point: it came back once already, in a second file."""
        import pathlib
        root = pathlib.Path(__file__).resolve().parent
        offenders = []
        for f in root.glob("*.py"):
            if f.name.startswith("test_") or f.name == "personalityz.py":
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                bare = line.strip()
                if "MBTI" in bare and not bare.startswith("#"):
                    offenders.append(f"{f.name}:{i}")
        self.assertEqual(offenders, [],
                         "Myers-Briggs is somebody's trademark; we publish four axes")


class ABuiltAppNamesItsDoorTests(TestCase):
    """`tab` has been in `_app` since it was written and was set on NOTHING,
    so the modal listed apps and gave a member nowhere to go — the
    cross-pollination rule broken on the one screen whose job is saying what
    this app has."""

    def test_the_built_apps_that_have_a_home_name_it(self):
        a = apps_by_name()
        for name in ("VybeZ", "PersonalitieZ", "ReligionZ", "LanguageZ", "Freestyle", "Battle Cypher"):
            self.assertTrue(a[name]["tab"], f"{name} is built and links nowhere")

    def test_an_unbuilt_app_never_claims_a_door(self):
        """A link to a tab that cannot do the thing is worse than no link."""
        for app in apps_by_name().values():
            if not app["built"]:
                self.assertEqual(app["tab"], "", f"{app['name']} is not built")

    def test_every_named_tab_is_a_real_one(self):
        keys = {t["key"] for t in LOGICZ_TABS}
        # The tabs LogicZ itself describes, plus the ones a row may point at
        # that live under another group's key.
        extra = {"vybez", "profilez"}
        for app in apps_by_name().values():
            if app["tab"]:
                self.assertIn(app["tab"], keys | extra,
                              f"{app['name']} points at a tab that does not exist")
