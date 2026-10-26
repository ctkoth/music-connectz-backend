"""Interests, brands and suggested strengths.

The thing under test is a LINE rather than a feature: what a member says they like may
be matched against a closed list and may produce a SUGGESTION with a reason, and that
suggestion is saved only when the member sends it and is never read as a measurement.
"""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.economy import interestz, interestz_table as T, personaz
from apps.economy.models import profile_for

User = get_user_model()


def member(name="maker", personas=None):
    u = User.objects.create_user(name, f"{name}@x.com", "hunter2hunter2")
    if personas is not None:
        p = profile_for(u)
        p.personas = personas
        p.save()
    return u


def client_for(u):
    c = APIClient()
    c.force_authenticate(u)
    return c


DESIGNER = {"key": "designer", "name": "Designer", "skills": [{"name": "Album Cover Design"}]}


class ScanTests(SimpleTestCase):
    def test_it_picks_brands_and_interests_out_of_what_was_said(self):
        i, b = interestz.scan("I mostly draw on my iPad in Procreate, then I'll mess about on my Fender and Ableton Live.")
        self.assertEqual(b, ["fender", "ableton", "procreate"] if False else sorted(b, key=["fender", "ableton", "procreate"].index))
        self.assertEqual(set(b), {"fender", "ableton", "procreate"})
        self.assertIn("drawing", interestz.scan("I love drawing")[0])

    def test_a_word_inside_another_word_is_not_a_match(self):
        self.assertEqual(interestz.scan("Fenderson was great and I bake")[1], [])

    def test_nothing_said_is_nothing_found(self):
        self.assertEqual(interestz.scan(""), ([], []))
        self.assertEqual(interestz.scan(None), ([], []))

    def test_a_closed_list_cannot_find_what_is_not_on_it(self):
        # Sensitive territory is absent from the table, so it cannot come out of a transcript.
        i, b = interestz.scan("I go to church, I'm gay, I vote, I have depression and I love drawing")
        self.assertEqual((i, b), (["drawing"], []))

    def test_the_tables_are_consistent(self):
        aliases = {}
        for table in (T.INTERESTS, T.BRANDS):
            for key, row in table.items():
                for a in row[2]:
                    self.assertEqual(a, a.lower(), a)
                    self.assertNotIn(a, aliases, f"{a} names both {aliases.get(a)} and {key}")
                    aliases[a] = key
        for who, wants, trait, because in T.RULES:
            self.assertIn(trait, T.TRAITS)
            self.assertTrue(set(wants) <= set(T.INTERESTS), wants)
            self.assertTrue(because.strip())
            self.assertNotIn("!", because)


class SuggestTests(SimpleTestCase):
    def test_a_designer_who_draws_is_offered_dexterous_with_the_reason(self):
        s = {x["key"]: x for x in interestz.suggest(DESIGNER, ["drawing"])}
        self.assertIn("dexterous", s)
        self.assertIn("steady, fine control", s["dexterous"]["because"][0])
        self.assertEqual(s["dexterous"]["from"], ["Drawing"])

    def test_a_designer_with_cover_art_is_offered_creative_and_observant(self):
        keys = {x["key"] for x in interestz.suggest(DESIGNER, ["cover_art"])}
        self.assertTrue({"creative", "observant"} <= keys)

    def test_two_rules_for_one_trait_make_one_suggestion(self):
        s = interestz.suggest(DESIGNER, ["drawing", "cover_art"])
        self.assertEqual(len([x for x in s if x["key"] == "detail_minded"]), 1)
        self.assertEqual(len({x["key"] for x in s}), len(s))

    def test_no_suggestion_without_the_interest_or_the_kind_of_work(self):
        self.assertEqual(interestz.suggest(DESIGNER, []), [])
        self.assertEqual(interestz.suggest(DESIGNER, ["dance"]), [])
        self.assertEqual(interestz.suggest({"name": "Manager", "skills": []}, ["drawing"]), [])

    def test_every_suggestion_says_it_is_inferred_and_not_a_score(self):
        for x in interestz.suggest(DESIGNER, list(T.INTERESTS)):
            self.assertTrue(x["inferred"])
            self.assertFalse(x["scored"])
            self.assertTrue(x["because"])


class EndpointTests(TestCase):
    def test_the_catalogue_states_the_rule_before_anyone_says_anything(self):
        r = client_for(member()).get("/api/economy/interestz/")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["scored"])
        self.assertIn("never changes a rating", r.data["rule"])
        self.assertIn("Nothing you said is stored", r.data["kept"])

    def test_signed_out_gets_nothing(self):
        self.assertEqual(APIClient().get("/api/economy/interestz/").status_code, 401)
        self.assertEqual(APIClient().post("/api/economy/interestz/scan/", {"text": "x"}, format="json").status_code, 401)

    def test_scan_returns_matches_and_suggestions_and_writes_nothing(self):
        u = member(personas=[DESIGNER])
        before = list(profile_for(u).personas)
        r = client_for(u).post("/api/economy/interestz/scan/",
                               {"text": "I do cover art and sketching in Procreate", "persona_key": "designer"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual({x["key"] for x in r.data["brands"]}, {"procreate"})
        self.assertEqual({x["key"] for x in r.data["suggestions"]} >= {"dexterous", "creative"}, True)
        self.assertEqual(list(profile_for(u).personas), before)

    def test_scan_can_read_a_persona_that_is_not_saved_yet(self):
        r = client_for(member()).post("/api/economy/interestz/scan/", {
            "text": "I sketch all day", "persona": {"key": "designer", "name": "Designer", "skills": []}}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("dexterous", {x["key"] for x in r.data["suggestions"]})

    def test_scan_for_a_persona_that_does_not_exist_says_where_to_add_it(self):
        r = client_for(member()).post("/api/economy/interestz/scan/", {"text": "drawing", "persona_key": "ghost"}, format="json")
        self.assertEqual(r.status_code, 404)
        self.assertIn("ProfileZ", r.data["detail"])

    def test_save_keeps_only_what_was_picked_and_only_from_the_lists(self):
        u = member(personas=[{**DESIGNER, "interests": ["jazz"]}])
        r = client_for(u).post("/api/economy/interestz/save/", {
            "persona_key": "designer", "interests": ["drawing", "nonsense"],
            "brands": ["procreate", "evilcorp"], "strengths": ["dexterous", "psychic"]}, format="json")
        self.assertEqual(r.status_code, 200)
        p = personaz.personas_of(profile_for(u))[0]
        self.assertEqual(p["interests"], ["jazz", "Drawing"])      # added to, not replaced
        self.assertEqual(p["declared_brands"], ["procreate"])
        self.assertEqual(p["declared_strengths"], ["dexterous"])
        self.assertNotIn("psychic", str(p))

    def test_a_declined_strength_can_be_taken_back(self):
        u = member(personas=[{**DESIGNER, "declared_strengths": ["dexterous"], "declared_brands": ["figma"]}])
        client_for(u).post("/api/economy/interestz/save/", {"persona_key": "designer", "brands": [], "strengths": []}, format="json")
        p = personaz.personas_of(profile_for(u))[0]
        self.assertNotIn("declared_strengths", p)
        self.assertNotIn("declared_brands", p)

    def test_the_transcript_is_not_kept(self):
        u = member(personas=[DESIGNER])
        client_for(u).post("/api/economy/interestz/scan/", {"text": "SECRET-SENTENCE about drawing", "persona_key": "designer"}, format="json")
        client_for(u).post("/api/economy/interestz/save/", {"persona_key": "designer", "interests": ["drawing"]}, format="json")
        self.assertNotIn("SECRET-SENTENCE", str(profile_for(u).personas))


class NothingMeasuresStrengthsTests(SimpleTestCase):
    """A strength is a declaration. If something outside these files reads one, it has
    become a score by the back door, which is the failure this feature is built not to be."""

    ALLOWED = {"interestz.py", "interestz_table.py", "personaz.py", "test_interestz.py"}

    def test_no_other_module_reads_strengths_or_brands_off_a_persona(self):
        root = Path(__file__).resolve().parent
        pat = re.compile(r"declared_(strengths|brands)")
        offenders = []
        for f in root.rglob("*.py"):
            if f.name in self.ALLOWED or "migrations" in f.parts or f.name.startswith("test_"):
                continue
            if pat.search(f.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(f.name)
        self.assertEqual(offenders, [])
