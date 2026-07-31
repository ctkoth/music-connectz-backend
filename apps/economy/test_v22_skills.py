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

from .personaz import PERSONAZ, normalize_persona_key

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
