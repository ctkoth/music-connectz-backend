"""The PersonaZ audit, as tests.

The v2.2 frontend carried this catalog as a hand-maintained JavaScript object
with nothing checking it, and it rotted: two entries became syntax errors, four
of five persona buttons passed keys the database didn't have, and three personas
were named in the UI with no skills at all. Every check below is one of those
failures, turned into something that can't happen again quietly.

Findings and history: PERSONAZ_AUDIT.md
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import profile_for
from apps.economy.personaz import (PERSONAZ, is_any_skill, normalize_personas,
                                   normalize_persona_key, normalize_skill,
                                   normalize_start, skill_key_for, skills_for)
from apps.economy.social import profile_max_experience

User = get_user_model()

# The personas that shipped in the 2.2 build. Their skills must stay exactly as
# they were — members have already picked them and stored the labels.
V22_PERSONAS = ("artist", "producer", "mix-engineer", "designer", "videographer")
# Named in 2.2's personaNames map with no entry in instrumentDatabase, so their
# picker opened empty. Built here in the same paradigm.
NEW_PERSONAS = ("ghostwriter", "manager", "developer")

# The artist families exactly as the 2.2 build shipped them, transcribed from
# `instrumentDatabase` in musicconnectz_code_2.2.docx. Categories added after the
# audit are deliberately NOT here — this fixture exists to prove the 2.2 content
# survived, not to freeze the catalog against growth.
V22_ARTIST = {
    "String Instruments": {
        "Any String": "Any String 🎸", "Acoustic Guitar": "Acoustic Guitar 🎸",
        "Electric Guitar": "Electric Guitar 🎸", "Bass Guitar": "Bass Guitar 🎸",
        "Ukulele": "Ukulele 🎸", "Banjo": "Banjo 🎸", "Mandolin": "Mandolin 🎸",
        "Violin": "Violin 🎻", "Viola": "Viola 🎻", "Cello": "Cello 🎻",
        "Double Bass": "Double Bass 🎻", "Harp": "Harp 🎵",
    },
    "Keyboard Instruments": {
        "Any Keyboard": "Any Keyboard 🎹", "Acoustic Piano": "Acoustic Piano 🎹",
        "Digital Piano": "Digital Piano 🎹", "Synthesizer": "Synthesizer 🎹",
        "Organ": "Organ 🎹", "Harpsichord": "Harpsichord 🎹",
        "Accordion": "Accordion 🎹",
    },
    "Percussion Instruments": {
        "Any Percussion": "Any Percussion 🥁", "Drums (Snare)": "Drums (Snare) 🥁",
        "Drums (Bass)": "Drums (Bass) 🥁", "Drums (Bongo)": "Drums (Bongo) 🥁",
        "Cymbals": "Cymbals 🥁",
    },
    "Rapping": {
        "Any Rapping": "Any Rapping 🎤", "Alternative Rap": "Alternative Rap 🎸",
        "Boom Bap": "Boom Bap 🥁", "Chopper": "Chopper 🚁",
        "Cloud Rap": "Cloud Rap ☁️", "Conscious Rap": "Conscious Rap 🧠",
        "Crunk": "Crunk 🔥", "Drill": "Drill ⚔️", "Emo Rap": "Emo Rap 🖤",
        "G-Funk": "G-Funk 🌴", "Gangsta Rap": "Gangsta Rap ⛓️",
        "Hardcore Hip Hop": "Hardcore Hip Hop 🎤", "Jazz Rap": "Jazz Rap 🎷",
        "Mumble Rap": "Mumble Rap 💤", "Old School": "Old School 📻",
        "Snap": "Snap 🫰", "Trap": "Trap 🏚️",
    },
    "Singing": {
        "Any Singing": "Any Singing 🎶", "Bass": "Bass 🧔‍♂️",
        "Baritone": "Baritone 🎙️", "Tenor": "Tenor 🎤",
        "Countertenor": "Countertenor 🕊️", "Contralto": "Contralto 🎻",
        "Alto": "Alto 🎶", "Mezzo-Soprano": "Mezzo-Soprano 🌊",
        "Soprano": "Soprano ☀️",
    },
}


class ParadigmTests(TestCase):
    """Every persona, old and new, obeys the same shape."""

    def test_every_persona_has_at_least_two_categories(self):
        for key, persona in PERSONAZ.items():
            self.assertGreaterEqual(len(persona["categories"]), 2, key)

    def test_every_category_opens_with_an_any_wildcard(self):
        """The client styles these differently and members rely on them to claim
        a category without enumerating it, so first position is load-bearing."""
        for key, persona in PERSONAZ.items():
            for cat, skills in persona["categories"].items():
                self.assertTrue(skills, f"{key}/{cat} is empty")
                first = next(iter(skills))
                self.assertTrue(is_any_skill(first), f"{key}/{cat} opens with {first!r}")

    def test_only_the_first_entry_of_a_category_is_a_wildcard(self):
        for key, persona in PERSONAZ.items():
            for cat, skills in persona["categories"].items():
                extra = [s for s in list(skills)[1:] if is_any_skill(s)]
                self.assertEqual(extra, [], f"{key}/{cat} has extra wildcards: {extra}")

    def test_every_label_ends_in_an_emoji(self):
        for key, persona in PERSONAZ.items():
            for cat, skills in persona["categories"].items():
                for sk, label in skills.items():
                    self.assertTrue(label.strip(), f"{key}/{cat}/{sk} has no label")
                    self.assertFalse(
                        label.strip()[-1].isalnum(),
                        f"{key}/{cat}/{sk} label {label!r} has no trailing emoji",
                    )

    def test_keys_are_tidy(self):
        """2.2 shipped 'Manager ', 'Developer ' and 'Independent  artist'."""
        for key, persona in PERSONAZ.items():
            self.assertEqual(key, key.strip().lower(), key)
            self.assertNotIn(" ", key, key)
            for cat, skills in persona["categories"].items():
                self.assertEqual(cat, cat.strip(), f"{key}: category {cat!r} padded")
                for sk in skills:
                    self.assertEqual(sk, sk.strip(), f"{key}/{cat}: key {sk!r} padded")

    def test_no_skill_key_repeats_within_a_persona(self):
        for key, persona in PERSONAZ.items():
            counted = sum(len(s) for s in persona["categories"].values())
            self.assertEqual(counted, len(skills_for(key)), f"{key} repeats a skill key")

    def test_every_persona_is_described_and_dated(self):
        for key, persona in PERSONAZ.items():
            self.assertTrue(persona["name"].strip(), key)
            self.assertTrue(persona["emoji"].strip(), key)
            self.assertTrue(persona["blurb"].strip(), key)
            self.assertIn(persona["since"], ("2.2", "2.4"), key)


class V22SkillsPreservedTests(TestCase):
    """The exact 2.2 skill lists, spot-checked against the source build."""

    def test_the_five_v22_personas_are_all_present(self):
        for key in V22_PERSONAS:
            self.assertIn(key, PERSONAZ)
            self.assertEqual(PERSONAZ[key]["since"], "2.2")

    def test_artist_keeps_every_2_2_family_and_every_2_2_skill_verbatim(self):
        """Preserved-verbatim means nothing was changed or removed. Families were
        ADDED after the audit (#12), so this asserts the 2.2 content is intact
        rather than asserting a total that additions would break."""
        cats = PERSONAZ["artist"]["categories"]
        for family, skills in V22_ARTIST.items():
            self.assertIn(family, cats, family)
            for key, label in skills.items():
                self.assertIn(key, cats[family], f"{family}/{key} disappeared")
                self.assertEqual(cats[family][key], label, f"{family}/{key} relabelled")

    def test_the_2_2_families_still_open_with_their_original_wildcards(self):
        cats = PERSONAZ["artist"]["categories"]
        for family, skills in V22_ARTIST.items():
            self.assertEqual(next(iter(cats[family])), next(iter(skills)), family)

    def test_the_audit_gap_families_are_now_covered(self):
        """#12: 2.2 had nowhere to put a saxophone, a trumpet or a full kit."""
        cats = PERSONAZ["artist"]["categories"]
        self.assertIn("Wind & Woodwind", cats)
        self.assertIn("Brass Instruments", cats)
        self.assertIn("Electronic & DJ", cats)
        for expected, family in (
            ("Saxophone (Tenor)", "Wind & Woodwind"),
            ("Flute", "Wind & Woodwind"),
            ("Clarinet", "Wind & Woodwind"),
            ("Harmonica", "Wind & Woodwind"),
            ("Trumpet", "Brass Instruments"),
            ("Trombone", "Brass Instruments"),
            ("French Horn", "Brass Instruments"),
            ("Tuba", "Brass Instruments"),
            ("Full Drum Kit", "Percussion Instruments"),
            ("Congas", "Percussion Instruments"),
            ("DJ Decks", "Electronic & DJ"),
            ("Turntablism", "Electronic & DJ"),
        ):
            self.assertIn(expected, cats[family], expected)

    def test_a_saxophonist_can_now_register_their_instrument(self):
        """The concrete complaint behind finding #12."""
        self.assertEqual(skill_key_for("artist", "Saxophone (Tenor) 🎷"), "Saxophone (Tenor)")
        self.assertEqual(skill_key_for("artist", "Trumpet"), "Trumpet")

    def test_artist_labels_are_verbatim(self):
        cats = PERSONAZ["artist"]["categories"]
        self.assertEqual(cats["String Instruments"]["Acoustic Guitar"], "Acoustic Guitar 🎸")
        self.assertEqual(cats["String Instruments"]["Harp"], "Harp 🎵")
        self.assertEqual(cats["Rapping"]["Boom Bap"], "Boom Bap 🥁")
        self.assertEqual(cats["Rapping"]["Snap"], "Snap 🫰")
        self.assertEqual(cats["Singing"]["Mezzo-Soprano"], "Mezzo-Soprano 🌊")

    def test_producer_and_mix_engineer_share_the_same_daw_list(self):
        """They were duplicated by hand in 2.2, which is how one got corrupted."""
        self.assertEqual(
            PERSONAZ["producer"]["categories"]["Music DAWs"],
            PERSONAZ["mix-engineer"]["categories"]["Music DAWs"],
        )
        # 18 from 2.2, plus Azrael ☠️ — the Music ConnectZ DAW the corrupted
        # 2.2 line was reaching for. Both it and Reaper are carried.
        self.assertEqual(len(PERSONAZ["producer"]["categories"]["Music DAWs"]), 19)

    def test_the_corrupted_reaper_entry_is_repaired(self):
        """2.2 had `Reaper:'Reaper🪦': 'Azrael☠️'` — a JavaScript syntax error
        that took the whole app script down with it."""
        daws = PERSONAZ["mix-engineer"]["categories"]["Music DAWs"]
        self.assertEqual(daws["Reaper"], "Reaper 🔧")
        self.assertEqual(daws["Studio One"], "Studio One 🎛️")
        self.assertNotIn("Azrael☠️", daws.values())
        for label in daws.values():
            self.assertNotIn("1⃣", label)

    def test_designer_and_videographer_keep_their_key_to_label_renames(self):
        design = PERSONAZ["designer"]["categories"]["Design Software"]
        self.assertEqual(design["Photoshop"], "Adobe Photoshop 🎨")
        self.assertEqual(design["InDesign"], "Adobe InDesign 📄")
        self.assertEqual(
            PERSONAZ["videographer"]["categories"]["Video Software"]["OBS"], "OBS Studio 🔴"
        )

    def test_engineering_and_production_categories_are_intact(self):
        self.assertEqual(
            list(PERSONAZ["mix-engineer"]["categories"]["Engineering Skills"]),
            ["Any Engineering", "Mixing", "Mastering", "EQ", "Compression", "Reverb/Effects"],
        )
        self.assertEqual(
            list(PERSONAZ["producer"]["categories"]["Production Techniques"]),
            ["Any Production", "Beat Making", "Sampling", "Sound Design", "Arrangement",
             "Synthesis"],
        )


class NewPersonaTests(TestCase):
    """The three that 2.2 named but never gave skills to."""

    def test_all_three_now_have_skills(self):
        for key in NEW_PERSONAS:
            self.assertIn(key, PERSONAZ)
            self.assertGreater(len(skills_for(key)), 10, key)

    def test_they_follow_the_tools_plus_craft_split(self):
        self.assertEqual(
            list(PERSONAZ["ghostwriter"]["categories"]), ["Writing Tools", "Writing Skills"]
        )
        self.assertEqual(
            list(PERSONAZ["manager"]["categories"]),
            ["Management Tools", "Management Skills"],
        )
        self.assertEqual(
            list(PERSONAZ["developer"]["categories"]),
            ["Programming Languages", "Developer Tools", "Development Skills"],
        )

    def test_developer_carries_exactly_the_top_forty_languages(self):
        langs = PERSONAZ["developer"]["categories"]["Programming Languages"]
        # 40 languages plus the "Any Language" wildcard.
        self.assertEqual(len(langs), 41)
        self.assertEqual(len(langs) - 1, 40)
        # the first twenty — what most people actually ship
        for expected in ("Python", "JavaScript", "TypeScript", "Java", "C", "C++", "C#",
                         "SQL", "Go", "Rust", "PHP", "Swift", "Kotlin", "Ruby", "R",
                         "Dart", "Scala", "MATLAB", "Perl", "Lua"):
            self.assertIn(expected, langs, expected)
        # and the twenty that cover the programmer who isn't writing web apps
        for expected in ("Shell / Bash", "PowerShell", "Assembly", "Objective-C",
                         "Visual Basic", "Groovy", "Haskell", "Elixir", "Erlang",
                         "Clojure", "F#", "Julia", "Fortran", "COBOL", "Solidity",
                         "Zig", "Nim", "OCaml", "Ada", "Prolog"):
            self.assertIn(expected, langs, expected)

    def test_developer_covers_this_platform_s_own_stack(self):
        """A developer persona that can't describe the app it lives in is the
        wrong list — Python/Django backend, JS frontend, Kotlin Android."""
        langs = PERSONAZ["developer"]["categories"]["Programming Languages"]
        for lang in ("Python", "JavaScript", "Kotlin", "SQL"):
            self.assertIn(lang, langs)
        skills = PERSONAZ["developer"]["categories"]["Development Skills"]
        for skill in ("Backend", "Frontend", "Mobile Apps", "APIs & Integrations"):
            self.assertIn(skill, skills)

    def test_ghostwriter_and_manager_cover_their_actual_craft(self):
        writing = PERSONAZ["ghostwriter"]["categories"]["Writing Skills"]
        for skill in ("Songwriting", "Hook Writing", "Cadence & Flow", "Storytelling"):
            self.assertIn(skill, writing)
        managing = PERSONAZ["manager"]["categories"]["Management Skills"]
        for skill in ("Contract Negotiation", "Royalty Accounting", "Release Planning", "A&R"):
            self.assertIn(skill, managing)


class KeyDriftTests(TestCase):
    """Every persona key 2.2 ever passed has to resolve to something."""

    def test_the_keys_the_v22_buttons_actually_sent(self):
        """Four of the five persona buttons passed a key `instrumentDatabase`
        did not have, so their skill picker rendered nothing at all."""
        for sent, expected in (
            ("Independent  artist", "artist"),   # double space, and no such key
            ("producer", "producer"),            # db key was 'Beat-producer'
            ("Engineer", "mix-engineer"),        # db key was 'mix-engineer'
            ("Designer", "designer"),            # db key was lowercase
            ("videographer", "videographer"),    # the one that worked
        ):
            self.assertEqual(normalize_persona_key(sent), expected, sent)

    def test_the_padded_keys_from_the_persona_names_map(self):
        self.assertEqual(normalize_persona_key("Developer "), "developer")
        self.assertEqual(normalize_persona_key("Manager "), "manager")
        self.assertEqual(normalize_persona_key("Ghostwriter"), "ghostwriter")

    def test_a_key_split_across_a_line_break_still_resolves(self):
        """2.2's Mix Engineer button held a raw newline inside the string
        literal — `openSkillModal('E` / `ngineer', …)` — which is itself a
        JavaScript syntax error. Resolve the key anyway."""
        self.assertEqual(normalize_persona_key("E\nngineer"), "mix-engineer")
        self.assertEqual(normalize_persona_key("mix_engineer"), "mix-engineer")

    def test_old_and_alternate_spellings(self):
        self.assertEqual(normalize_persona_key("Beat-producer"), "producer")
        self.assertEqual(normalize_persona_key("BEAT PRODUCER"), "producer")
        self.assertEqual(normalize_persona_key("🎤 Artist"), "artist")
        self.assertEqual(normalize_persona_key("coder"), "developer")

    def test_genuinely_unknown_keys_report_as_unknown(self):
        # NOT a plausible persona name: this test used to say "mime", which then
        # became a real persona — the same trap as the Theremin skill. Use a
        # string nothing will ever legitimately be called.
        self.assertIsNone(normalize_persona_key("not-a-real-persona"))
        self.assertIsNone(normalize_persona_key(""))
        self.assertIsNone(normalize_persona_key(None))


class SkillLookupTests(TestCase):
    def test_a_skill_resolves_from_its_key_or_its_stored_label(self):
        """2.2 stored the label, emoji included, as the skill name."""
        self.assertEqual(skill_key_for("artist", "Acoustic Guitar"), "Acoustic Guitar")
        self.assertEqual(skill_key_for("artist", "Acoustic Guitar 🎸"), "Acoustic Guitar")
        self.assertEqual(skill_key_for("designer", "Adobe Photoshop 🎨"), "Photoshop")
        self.assertEqual(skill_key_for("developer", "Rust 🦀"), "Rust")

    def test_a_skill_from_another_persona_does_not_resolve(self):
        self.assertIsNone(skill_key_for("designer", "Acoustic Guitar"))
        self.assertIsNone(skill_key_for("artist", ""))


class StartDateTests(TestCase):
    """The bug that made every member's experience read as None."""

    def test_the_slash_format_the_picker_actually_wrote(self):
        # `${mo}/${day}/${yr}` in addSkills()
        self.assertEqual(normalize_start("7/4/2020"), "2020-07-04")
        self.assertEqual(normalize_start("12/31/1999"), "1999-12-31")

    def test_iso_dates_pass_through(self):
        self.assertEqual(normalize_start("2015-06-01"), "2015-06-01")

    def test_junk_is_refused_rather_than_guessed(self):
        for bad in ("", None, "yesterday", "2020", "2020-13-01", "0/0/0", "1/2"):
            self.assertIsNone(normalize_start(bad), bad)

    def test_experience_now_counts_a_slash_date(self):
        p = profile_for(User.objects.create_user("slash", "s@e.com", "pw12345678"))
        p.personas = [{"key": "artist", "name": "Artist", "skills": [
            {"name": "Acoustic Guitar 🎸", "startDate": f"1/1/{date.today().year - 9}"},
        ]}]
        p.save()
        # Before this fix: None, because the metric only read `start` in ISO form.
        self.assertEqual(profile_max_experience(p), 9)

    def test_patch_stores_the_pickers_date_instead_of_dropping_it(self):
        client = APIClient()
        user = User.objects.create_user("patcher", "p@e.com", "pw12345678")
        client.force_authenticate(user)
        resp = client.patch("/api/auth/me/", {"personas": [{
            "key": "producer", "name": "Producer",
            "skills": [{"name": "Beat Making 🎚️", "startDate": "3/15/2018"}],
        }]}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        stored = profile_for(user).personas
        self.assertEqual(stored[0]["skills"][0], {"name": "Beat Making 🎚️", "start": "2018-03-15"})


class NormalizeTests(TestCase):
    """Normalising is not allowed to delete anything."""

    def test_a_v22_persona_is_cleaned_into_the_canonical_shape(self):
        out = normalize_personas([{
            "key": "Beat-producer", "name": "🎚️Producer",
            "skills": [{"name": "Beat Making 🎚️", "startDate": "3/15/2018"}],
        }])
        self.assertEqual(out[0]["key"], "producer")
        self.assertEqual(out[0]["label"], "🎚️ Beat Producer")
        self.assertTrue(out[0]["catalog"])
        self.assertEqual(out[0]["skills"][0],
                         {"key": "Beat Making", "name": "Beat Making 🎚️",
                          "start": "2018-03-15", "catalog": True})

    def test_bare_strings_from_before_the_picker_still_work(self):
        out = normalize_personas(["designer", "videographer"])
        self.assertEqual([p["key"] for p in out], ["designer", "videographer"])
        self.assertEqual(out[0]["skills"], [])

    def test_personas_outside_the_catalog_are_kept_not_deleted(self):
        """The platform has personas the picker doesn't carry — DirectZ, and
        whatever gets built next. A catalog is not a licence to throw away a
        member's data."""
        out = normalize_personas(["dawz", {"key": "directz", "skills": [{"name": "Whatever"}]}])
        self.assertEqual([p["key"] for p in out], ["dawz", "directz"])
        self.assertFalse(out[0]["catalog"])
        self.assertEqual(out[1]["skills"][0]["name"], "Whatever")
        self.assertFalse(out[1]["skills"][0]["catalog"])

    def test_an_unknown_skill_on_a_known_persona_is_kept_and_flagged(self):
        # A string that will never be a catalog entry. (This test used to say
        # "Theremin" — which then became a real skill when the Electronic & DJ
        # family was added, so the test was asserting the opposite of the truth.)
        unknown = "Not A Real Instrument"
        self.assertIsNone(skill_key_for("artist", unknown))
        out = normalize_personas([{"key": "artist", "skills": [
            {"name": "Acoustic Guitar 🎸"}, {"name": unknown},
        ]}])
        skills = out[0]["skills"]
        self.assertEqual(skills[0]["catalog"], True)
        self.assertEqual(skills[1], {"key": None, "name": unknown, "start": None,
                                     "catalog": False})

    def test_the_same_persona_sent_under_two_spellings_merges(self):
        out = normalize_personas([
            {"key": "Beat-producer", "skills": [{"name": "Sampling 🎵"}]},
            {"key": "producer", "skills": [{"name": "Synthesis 🎹"}]},
        ])
        self.assertEqual(len(out), 1)
        self.assertEqual([s["key"] for s in out[0]["skills"]], ["Sampling", "Synthesis"])

    def test_duplicate_skills_collapse(self):
        out = normalize_personas([{"key": "artist", "skills": [
            {"name": "Violin 🎻"}, {"name": "Violin"}, {"name": "Violin 🎻"},
        ]}])
        self.assertEqual(len(out[0]["skills"]), 1)

    def test_junk_input_does_not_raise(self):
        self.assertEqual(normalize_personas(None), [])
        self.assertEqual(normalize_personas("artist"), [])
        self.assertEqual(normalize_personas([None, 7, {}, {"key": ""}]), [])
        self.assertIsNone(normalize_skill("artist", 7))
        self.assertIsNone(normalize_skill("artist", {"name": "  "}))


class CatalogEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_the_catalog_is_public_and_complete(self):
        resp = self.client.get("/api/economy/personaz/")
        self.assertEqual(resp.status_code, 200)
        keys = [p["key"] for p in resp.data["personas"]]
        self.assertEqual(keys, list(PERSONAZ))
        for key in V22_PERSONAS + NEW_PERSONAS:
            self.assertIn(key, keys)

    def test_each_persona_reports_its_categories_and_wildcards(self):
        data = self.client.get("/api/economy/personaz/").data
        artist = next(p for p in data["personas"] if p["key"] == "artist")
        self.assertEqual(len(artist["categories"]),
                         len(PERSONAZ["artist"]["categories"]))
        self.assertGreaterEqual(len(artist["categories"]), len(V22_ARTIST))
        self.assertEqual(artist["skill_count"], len(skills_for("artist")))
        strings = artist["categories"][0]
        self.assertEqual(strings["name"], "String Instruments")
        self.assertTrue(strings["skills"][0]["any"])
        self.assertFalse(strings["skills"][1]["any"])

    def test_the_rules_the_client_used_to_guess_at_are_stated(self):
        rules = self.client.get("/api/economy/personaz/").data["rules"]
        self.assertEqual(rules["start_date_format"], "YYYY-MM-DD")
        self.assertTrue(rules["start_date_required"])

    def test_a_persona_detail_accepts_any_spelling_that_ever_shipped(self):
        for sent in ("producer", "Beat-producer", "BEAT PRODUCER"):
            resp = self.client.get(f"/api/economy/personaz/{sent}/")
            self.assertEqual(resp.status_code, 200, sent)
            self.assertEqual(resp.data["key"], "producer")
            self.assertEqual(resp.data["requested"], sent)

    def test_developer_detail_lists_the_languages(self):
        resp = self.client.get("/api/economy/personaz/developer/")
        langs = next(c for c in resp.data["categories"] if c["name"] == "Programming Languages")
        self.assertEqual(len(langs["skills"]), 41)
        self.assertTrue(langs["skills"][0]["any"])

    def test_an_unknown_persona_404s_with_the_known_list(self):
        resp = self.client.get("/api/economy/personaz/saxophonist/")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.data["known"], list(PERSONAZ))


class AuditCommandTests(TestCase):
    def test_the_audit_runs_clean_on_the_catalog(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("audit_personaz", "--catalog", stdout=out)
        text = out.getvalue()
        self.assertIn("No problems found", text)
        self.assertIn("Developer", text)

    def test_fix_normalises_stored_drift_without_losing_anything(self):
        from io import StringIO

        from django.core.management import call_command

        user = User.objects.create_user("drift", "d@e.com", "pw12345678")
        p = profile_for(user)
        p.personas = [
            {"key": "Beat-producer", "skills": [{"name": "Sampling 🎵", "startDate": "6/1/2016"}]},
            "dawz",
        ]
        p.save()

        call_command("audit_personaz", "--fix", stdout=StringIO())
        p.refresh_from_db()
        self.assertEqual(p.personas[0]["key"], "producer")
        self.assertEqual(p.personas[0]["skills"][0]["start"], "2016-06-01")
        # the persona outside the catalog survived
        self.assertEqual(p.personas[1]["key"], "dawz")
        self.assertFalse(p.personas[1]["catalog"])
