"""The 2.2 contract, pinned.

Every string below was extracted from musicconnectz_code_2.2.docx — the
`instrumentDatabase`, the `personaNames` map, the collab filter `<option
value="…">` list, and the `openSkillModal()` calls. Nothing here is invented.

The bug these exist to stop: 2.2 stores the **decorated label** as the persona,
not the key — `personaNames` holds '🎚️Producer' and the collab filter holds
'🎤Independent  Artist'. Six of those resolved to None, which silently dropped a
member's persona and every skill under it. Emoji were never stripped, so the
handful that did work only worked because they happened to equal a label exactly.
"""
from django.test import SimpleTestCase

from .personaz import (PERSONAZ, V22_SKILLS, _demoji, normalize_persona_key,
                       skill_key_for)

# --- personaNames: what 2.2 saves onto a member's profile -------------------
PERSONA_NAMES = {
    "🎤 Artist": "artist",
    "🎚️Producer": "producer",           # no space after the emoji
    "🎛️ Mix Engineer": "mix-engineer",
    "🎨 Designer": "designer",
    "🎬 Videographer": "videographer",
    "👻Ghostwriter ": "ghostwriter",     # trailing space
    "🕴🏼Manager": "manager",              # skin-tone modifier
    "👾Developer": "developer",
}

# --- collab filter <option value="…"> --------------------------------------
FILTER_OPTIONS = {
    "🎤Independent  Artist": "artist",   # no space, and a double space
    "🎚️Beat Producer": "producer",
    "🎛️Mix Engineer": "mix-engineer",
    "🎨 Designer": "designer",
    "📹 Videographer": "videographer",   # 📹 here, 🎬 in personaNames
    "🕴🏼Manager ": "manager",
    "👻 Ghostwriter ": "ghostwriter",
    "👾Developer ": "developer",
}

# --- openSkillModal() first argument ---------------------------------------
MODAL_KEYS = {
    "Independent  artist": "artist",
    "producer": "producer",
    "E\nngineer": "mix-engineer",        # a literal line break mid-word in 2.2
    "Designer": "designer",
    "videographer": "videographer",
}

# --- instrumentDatabase top-level keys -------------------------------------
DB_KEYS = {
    "artist": "artist",
    "Beat-producer": "producer",
    "mix-engineer": "mix-engineer",
    "designer": "designer",
    "videographer": "videographer",
}


class PersonaKeyTests(SimpleTestCase):
    def _check(self, mapping, label):
        for sent, expected in mapping.items():
            with self.subTest(source=label, sent=sent):
                got = normalize_persona_key(sent)
                self.assertIsNotNone(
                    got, f"{sent!r} resolved to None — that member's persona and "
                         f"all its skills would vanish")
                self.assertEqual(got, expected)
                self.assertIn(got, PERSONAZ)

    def test_persona_names_resolve(self):
        self._check(PERSONA_NAMES, "personaNames")

    def test_collab_filter_options_resolve(self):
        self._check(FILTER_OPTIONS, "collab filter")

    def test_open_skill_modal_keys_resolve(self):
        self._check(MODAL_KEYS, "openSkillModal")

    def test_instrument_database_keys_resolve(self):
        self._check(DB_KEYS, "instrumentDatabase")

    def test_a_string_that_is_only_decoration_resolves_to_nothing(self):
        """Stripping emoji must not turn junk into a match."""
        for junk in ("🎤", "✨🔥", "   ", "", None):
            self.assertIsNone(normalize_persona_key(junk))

    def test_a_genuinely_unknown_persona_is_still_unknown(self):
        self.assertIsNone(normalize_persona_key("🎪 Trapeze Artist"))
        self.assertIsNone(normalize_persona_key("not-a-real-persona"))


class V22SkillContentTests(SimpleTestCase):
    """Spot-checks that the 2.2 skill labels survived verbatim — same key, same
    label, same emoji. Counts come from parsing the document, not from memory."""

    EXPECT = {
        "artist": {
            "String Instruments": ("Any String", "Any String 🎸"),
            "Singing": ("Mezzo-Soprano", "Mezzo-Soprano 🌊"),
            "Rapping": ("Snap", "Snap 🫰"),
            "Keyboard Instruments": ("Harpsichord", "Harpsichord 🎹"),
        },
        "producer": {
            "Music DAWs": ("Waveform Pro", "Waveform Pro 📊"),
            "Production Techniques": ("Any Production", "Any Production 🎚️"),
        },
        "mix-engineer": {
            "Music DAWs": ("Pro Tools", "Pro Tools 🎙️"),
            "Engineering Skills": ("Reverb/Effects", "Reverb/Effects ✨"),
        },
        "designer": {
            "Design Software": ("Photoshop", "Adobe Photoshop 🎨"),
            "Design Skills": ("Icon Design", "Icon Design 🎭"),
        },
        "videographer": {
            "Video Software": ("OBS", "OBS Studio 🔴"),
            "Video Skills": ("Drone Footage", "Drone Footage 🚁"),
        },
    }

    def test_every_checked_2_2_skill_is_present_and_unchanged(self):
        for persona, cats in self.EXPECT.items():
            for cat, (key, label) in cats.items():
                with self.subTest(persona=persona, category=cat, skill=key):
                    self.assertIn(cat, PERSONAZ[persona]["categories"])
                    self.assertEqual(
                        PERSONAZ[persona]["categories"][cat].get(key), label)

    def test_the_2_2_categories_all_still_exist(self):
        """New categories were added to artist; none of 2.2's may be gone."""
        for persona, cats in {
            "artist": ["String Instruments", "Keyboard Instruments",
                       "Percussion Instruments", "Rapping", "Singing"],
            "producer": ["Music DAWs", "Production Techniques"],
            "mix-engineer": ["Music DAWs", "Engineering Skills"],
            "designer": ["Design Software", "Design Skills"],
            "videographer": ["Video Software", "Video Skills"],
        }.items():
            for cat in cats:
                with self.subTest(persona=persona, category=cat):
                    self.assertIn(cat, PERSONAZ[persona]["categories"])

    def test_every_category_still_opens_with_its_wildcard(self):
        for persona, data in PERSONAZ.items():
            for cat, skills in data["categories"].items():
                first = next(iter(skills))
                with self.subTest(persona=persona, category=cat):
                    self.assertTrue(
                        first.lower().startswith("any"),
                        f"{persona}/{cat} starts with {first!r}, not an 'Any …' "
                        f"wildcard — the client renders that slot specially")


class ReaperAndAzraelTests(SimpleTestCase):
    """2.2's broken line reached for one or the other. We carry both.

    `Reaper:'Reaper🪦': 'Azrael☠️'` is a syntax error, so 2.2 never had a working
    answer here. Reaper is the real product; Azrael is the Music ConnectZ DAW
    that imitates it (DawZ: "+Azrael☠️ reaper knockoff"). Being skilled in one
    is not being skilled in the other.
    """

    DAW_PERSONAS = ("producer", "mix-engineer")

    def test_both_are_offered(self):
        for persona in self.DAW_PERSONAS:
            daws = PERSONAZ[persona]["categories"]["Music DAWs"]
            with self.subTest(persona=persona):
                self.assertEqual(daws.get("Reaper"), "Reaper 🔧")
                self.assertEqual(daws.get("Azrael"), "Azrael ☠️")

    def test_they_are_separate_skills_not_one_renamed(self):
        daws = PERSONAZ["mix-engineer"]["categories"]["Music DAWs"]
        self.assertNotEqual(daws["Reaper"], daws["Azrael"])

    def test_neither_carries_the_2_2_corruption(self):
        """The mangled key and the stray keycap must not have survived."""
        for persona in self.DAW_PERSONAS:
            daws = PERSONAZ[persona]["categories"]["Music DAWs"]
            with self.subTest(persona=persona):
                self.assertNotIn("Reaper🪦", daws)
                self.assertEqual(daws.get("Studio One"), "Studio One 🎛️")
                self.assertNotIn("1⃣", daws.get("Studio One", ""))

    def test_both_resolve_from_a_stored_label(self):
        """A member who picked either must not lose it on the way back in."""
        from .personaz import skill_key_for
        for persona in self.DAW_PERSONAS:
            self.assertEqual(skill_key_for(persona, "Reaper 🔧"), "Reaper")
            self.assertEqual(skill_key_for(persona, "Azrael ☠️"), "Azrael")


class EveryV22SkillResolvesTests(SimpleTestCase):
    """Exhaustive, not spot-checked: all 131 skills, in every form 2.2 could
    have stored them in.

    The spot-checks above prove the labels are unchanged. This proves they can
    be *read back*, which is the failure that actually loses a member's skills.
    Driven off V22_SKILLS so it covers the whole set rather than a sample.

    The forms matter because 2.2 is inconsistent about the space before the
    emoji. Most entries are "Acoustic Guitar 🎸"; some are "Reaper🪦" and
    "🎚️Producer" with none. Matching only the spaced form meant a skill
    survived or vanished depending on whether whoever typed that catalog line
    happened to hit the space bar.
    """

    def forms_for(self, label):
        """Every way a client might hand this label back to us."""
        return {
            label,                              # exactly as served
            label.replace(" ", "", 1) if label.startswith(" ") else label,
            "".join(label.rsplit(" ", 1)),      # emoji welded to the name
            label.strip().upper(),
            f"  {label}  ",                     # copied with stray whitespace
        }

    def test_every_2_2_skill_resolves_from_its_key(self):
        for persona, cats in V22_SKILLS.items():
            for cat, keys in cats.items():
                for key in keys:
                    with self.subTest(persona=persona, category=cat, skill=key):
                        self.assertEqual(skill_key_for(persona, key), key)

    def test_every_2_2_skill_resolves_from_every_stored_label_form(self):
        checked = 0
        for persona, cats in V22_SKILLS.items():
            for cat, keys in cats.items():
                catalog = PERSONAZ[persona]["categories"][cat]
                for key in keys:
                    for form in self.forms_for(catalog[key]):
                        checked += 1
                        with self.subTest(persona=persona, skill=key, form=form):
                            self.assertEqual(skill_key_for(persona, form), key)
        self.assertGreater(checked, 500, "the sweep stopped covering the set")

    def test_the_count_is_still_the_whole_2_2_build(self):
        total = sum(len(keys) for cats in V22_SKILLS.values()
                    for keys in cats.values())
        self.assertEqual(total, 131)

    def test_a_keycap_is_decoration_but_a_digit_is_content(self):
        """2.2 wrote 'Studio One1⃣ 🎛️'. Stripping only the combining mark left
        "Studio One1", which matched nothing — but dropping every digit would
        break real names like "808"."""
        self.assertEqual(skill_key_for("mix-engineer", "Studio One1⃣ 🎛️"),
                         "Studio One")
        self.assertEqual(_demoji("808"), "808")
        self.assertEqual(_demoji("Sound Forge 2"), "sound forge 2")

    def test_the_artist_persona_is_named_the_way_2_2_names_it(self):
        """2.2's button and collab filter both say "Independent Artist"."""
        self.assertEqual(PERSONAZ["artist"]["name"], "Independent Artist")
        for sent in ("Independent Artist", "Independent  artist",
                     "🎤Independent Artist", "artist"):
            with self.subTest(sent=sent):
                self.assertEqual(normalize_persona_key(sent), "artist")

    def test_independent_artist_covers_instruments_beyond_2_2(self):
        """2.2 had strings, keys and five percussion entries — no wind, no
        brass, nothing electronic. A saxophonist had no way to say so."""
        cats = PERSONAZ["artist"]["categories"]
        for cat in ("Wind & Woodwind", "Brass Instruments", "Electronic & DJ"):
            with self.subTest(category=cat):
                self.assertIn(cat, cats)
        self.assertIsNotNone(skill_key_for("artist", "Saxophone (Tenor)"))
        self.assertIsNotNone(skill_key_for("artist", "Trumpet"))
        self.assertIsNotNone(skill_key_for("artist", "Turntablism"))

    def test_a_renamed_product_keeps_its_2_2_key_and_old_label(self):
        """Bringing a display name up to date must not drop what a member
        already picked, or what a 2.2 client stored."""
        for old, new in (("Sony Vegas 📹", "VEGAS Pro 📹"),
                         ("Adobe Premiere 🎬", "Adobe Premiere Pro 🎬")):
            with self.subTest(old=old):
                key = skill_key_for("videographer", old)
                self.assertIsNotNone(key, "a 2.2 label stopped resolving")
                self.assertEqual(skill_key_for("videographer", new), key)

    def test_decoration_alone_still_resolves_to_nothing(self):
        """Stripping harder must not turn junk into a false match."""
        for junk in ("🎸", "🎛️ ✨", "1⃣", "   "):
            with self.subTest(junk=junk):
                self.assertIsNone(skill_key_for("artist", junk))


# ---------------------------------------------------------------- genres ----
# The 2.2 genre list, extracted from `openGenreModal()`:
#   const genres = ['Trap', 'Drill', ...];
# Fifteen, flat, single-select, required on the Upload Work Example form.
V22_GENRES_FROM_DOC = [
    "Trap", "Drill", "Cloud Rap", "Boom Bap", "House", "Techno", "Pop",
    "Hip Hop", "R&B", "Jazz", "Soul", "Indie", "Electronic", "Ambient", "Lo-Fi",
]


class V22GenreTests(SimpleTestCase):
    def test_all_fifteen_are_present_in_order(self):
        from .genrez import V22_GENRES
        self.assertEqual(V22_GENRES, V22_GENRES_FROM_DOC)

    def test_each_one_resolves_from_the_plain_2_2_string(self):
        from .genrez import normalize_genre
        for name in V22_GENRES_FROM_DOC:
            with self.subTest(genre=name):
                self.assertEqual(normalize_genre(name), name)

    def test_each_one_resolves_from_its_decorated_label(self):
        """The catalog serves 'Trap 🏚️'. A client that stores what it displayed
        sends that back — and every one of them used to resolve to None, which
        silently dropped every genre the member had picked."""
        from .genrez import catalog_payload, normalize_genre

        emoji = {r["key"]: r["emoji"] for r in catalog_payload()["genres"]}
        for name in V22_GENRES_FROM_DOC:
            for sent in (f"{name} {emoji[name]}", f"{name}{emoji[name]}"):
                with self.subTest(genre=name, sent=sent):
                    self.assertEqual(normalize_genre(sent), name)

    def test_case_and_stray_whitespace_still_resolve(self):
        from .genrez import normalize_genre
        for name in V22_GENRES_FROM_DOC:
            with self.subTest(genre=name):
                self.assertEqual(normalize_genre(name.lower()), name)
                self.assertEqual(normalize_genre(f"  {name}  "), name)

    def test_the_hand_typed_spellings_still_work(self):
        """Members have always typed these by hand; the squash rule is why."""
        from .genrez import normalize_genre
        for sent in ("r and b", "RnB", "r&b", "R&B 💜"):
            self.assertEqual(normalize_genre(sent), "R&B")
        for sent in ("lofi", "lo fi", "Lo-Fi 📻"):
            self.assertEqual(normalize_genre(sent), "Lo-Fi")

    def test_decoration_alone_is_not_a_genre(self):
        """Stripping emoji must not turn junk into a match."""
        from .genrez import normalize_genre
        for junk in ("🏚️", "✨🔥", "", "   ", "not-a-genre", "dawz"):
            with self.subTest(junk=junk):
                self.assertIsNone(normalize_genre(junk))

    def test_the_four_that_are_also_rapping_skills_are_flagged(self):
        """A genre describes the work, a skill describes the person — 2.2 had
        both and the overlap is deliberate."""
        from .genrez import ALSO_SKILLS
        self.assertEqual(ALSO_SKILLS, {"Trap", "Drill", "Cloud Rap", "Boom Bap"})
        for name in ALSO_SKILLS:
            self.assertIn(name, PERSONAZ["artist"]["categories"]["Rapping"])

    def test_a_members_saved_genres_survive_a_round_trip(self):
        from .genrez import catalog_payload, normalize_genres

        emoji = {r["key"]: r["emoji"] for r in catalog_payload()["genres"]}
        stored = [f"{n} {emoji[n]}" for n in V22_GENRES_FROM_DOC[:12]]
        self.assertEqual(normalize_genres(stored), V22_GENRES_FROM_DOC[:12])


class DawZSuiteTests(SimpleTestCase):
    """The seven Music ConnectZ DAWs are skills in their own right.

    Members work in these on the platform (DawZ), so "I use Fruity Möbius" is a
    real thing to be able to say. Each sits ALONGSIDE the product it imitates —
    knowing Fruity Möbius is not knowing FL Studio.
    """

    # Music ConnectZ app -> the product it imitates, per the DawZ spec.
    DAWZ = {
        "Azrael": ("Azrael ☠️", "Reaper"),
        "Arsenal": ("Arsenal ⚔️", "Pro Tools"),
        "Fruity Möbius": ("Fruity Möbius 🍑", "FL Studio"),
        "Witchcraft": ("Witchcraft 🔮", "Mixcraft"),
        "Trump Toupee": ("Trump Toupee 🤵🏼‍♂️", "Bitwig Studio"),
        "Intuition": ("Intuition 🤔", "Logic Pro"),
        "FormulaWon": ("FormulaWon 🚦", "GarageBand"),
    }

    DAW_PERSONAS = ("producer", "mix-engineer")

    def test_all_seven_are_offered_to_both_daw_personas(self):
        for persona in self.DAW_PERSONAS:
            daws = PERSONAZ[persona]["categories"]["Music DAWs"]
            for key, (label, _) in self.DAWZ.items():
                with self.subTest(persona=persona, daw=key):
                    self.assertEqual(daws.get(key), label)

    def test_each_sits_alongside_the_product_it_imitates(self):
        daws = PERSONAZ["producer"]["categories"]["Music DAWs"]
        for key, (_, imitates) in self.DAWZ.items():
            with self.subTest(daw=key):
                self.assertIn(imitates, daws,
                              f"{key} replaced {imitates} instead of joining it")

    def test_they_resolve_from_a_stored_label(self):
        from .personaz import skill_key_for
        for persona in self.DAW_PERSONAS:
            for key, (label, _) in self.DAWZ.items():
                with self.subTest(persona=persona, daw=key):
                    self.assertEqual(skill_key_for(persona, label), key)

    def test_the_2_2_daws_all_survived(self):
        """Adding seven must not have disturbed the eighteen that shipped."""
        from .personaz import PERSONAZ as P
        v22_daws = [
            "Any DAW", "Ableton Live", "Adobe Audition", "Audacity",
            "Bitwig Studio", "Cakewalk", "Cubase", "FL Studio", "GarageBand",
            "Logic Pro", "Luna", "Mixcraft", "PreSonus Studio One",
            "Pro Tools", "Reason", "Reaper", "Studio One", "Waveform Pro",
        ]
        daws = P["producer"]["categories"]["Music DAWs"]
        for key in v22_daws:
            with self.subTest(daw=key):
                self.assertIn(key, daws)
        self.assertEqual(len(daws), len(v22_daws) + len(self.DAWZ))


class V22OnlyViewTests(SimpleTestCase):
    """`?since=2.2` serves the original build and nothing else.

    Filtered from the single catalog rather than stored twice, so the 2.2 view
    and the full view can never disagree about a label.
    """

    def test_it_serves_exactly_the_2_2_skill_count(self):
        from .personaz import V22_SKILL_COUNT, catalog_payload
        body = catalog_payload(since="2.2")
        total = sum(len(c["skills"]) for p in body["personas"] for c in p["categories"])
        self.assertEqual(total, V22_SKILL_COUNT)
        self.assertEqual(V22_SKILL_COUNT, 131)

    def test_it_serves_only_the_five_2_2_personas(self):
        from .personaz import catalog_payload
        keys = [p["key"] for p in catalog_payload(since="2.2")["personas"]]
        self.assertEqual(sorted(keys), ["artist", "designer", "mix-engineer",
                                        "producer", "videographer"])

    def test_nothing_added_afterwards_leaks_in(self):
        from .personaz import catalog_payload
        body = catalog_payload(since="2.2")
        cats, skills = set(), set()
        for p in body["personas"]:
            for c in p["categories"]:
                cats.add(c["name"])
                skills.update(s["key"] for s in c["skills"])
        for gone in ("Wind & Woodwind", "Brass Instruments", "Electronic & DJ"):
            self.assertNotIn(gone, cats)
        for gone in ("Azrael", "Fruity Möbius", "Full Drum Kit", "Congas"):
            self.assertNotIn(gone, skills)

    def test_the_labels_match_the_full_catalog_exactly(self):
        """One catalog, two views — a label must never differ between them."""
        from .personaz import catalog_payload
        full = {(p["key"], c["name"], s["key"]): s["label"]
                for p in catalog_payload()["personas"]
                for c in p["categories"] for s in c["skills"]}
        for p in catalog_payload(since="2.2")["personas"]:
            for c in p["categories"]:
                for s in c["skills"]:
                    with self.subTest(skill=s["key"]):
                        self.assertEqual(s["label"],
                                         full[(p["key"], c["name"], s["key"])])

    def test_skill_count_reports_the_filtered_total(self):
        from .personaz import catalog_payload
        for p in catalog_payload(since="2.2")["personas"]:
            counted = sum(len(c["skills"]) for c in p["categories"])
            with self.subTest(persona=p["key"]):
                self.assertEqual(p["skill_count"], counted)

    def test_the_full_catalog_is_untouched_by_the_filter(self):
        from .personaz import catalog_payload
        self.assertEqual(len(catalog_payload()["personas"]), 11)

    def test_genres_filter_the_same_way(self):
        from .genrez import catalog_payload as g
        body = g(since="2.2")
        self.assertEqual(body["count"], 15)
        self.assertEqual([x["key"] for x in body["genres"]], V22_GENRES_FROM_DOC)

    def test_2_2_had_no_screen_genres_so_that_view_is_empty(self):
        """Rather than inventing history to fill the list."""
        from .genrez import catalog_payload as g
        self.assertEqual(g(kind="screen", since="2.2")["count"], 0)
