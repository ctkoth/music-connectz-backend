"""One contract for every vocabulary the client displays and stores back.

The same bug has now been found four times: personas, genres, skills, and the
form where the emoji touches the name. Each time it was fixed where it was
found, and each time the next vocabulary had it too.

The shape is always identical. A catalog serves a **decorated label** —
"Trap 🏚️", "🎚️Producer", "Reaper🪦". A client stores what it displayed and sends
that back. The resolver only matched the undecorated key, so the value returned
None and the member's persona, genre or skill silently vanished. Nobody reports
"my skill disappeared"; they just stop using the feature.

So this file does not test a vocabulary. It tests *all* of them, from one list,
against the rule they must all obey:

    every label a catalog serves must resolve back to the key it came from,
    in every decoration form a client could plausibly store it in.

A vocabulary added later gets added to REGISTRY below and is held to the same
rule. One that isn't added is the gap this file exists to close — so there is
also a test that every normalizer in the codebase is registered here.
"""
from django.test import SimpleTestCase

from apps.vstz import catalog as vstz_catalog

from . import genrez, personaz


def _persona_pairs():
    """(key, served label) for every skill under every persona."""
    for persona, data in personaz.PERSONAZ.items():
        for skills in data["categories"].values():
            for key, label in skills.items():
                yield key, label, (lambda v, p=persona: personaz.skill_key_for(p, v))


def _persona_name_pairs():
    for key, data in personaz.PERSONAZ.items():
        label = f"{data['emoji']} {data['name']}"
        yield key, label, personaz.normalize_persona_key


def _genre_pairs():
    """Genres render without emoji in 2.2, but the tour and later catalogs ship
    the decorated form — so both have to resolve."""
    for name in genrez.GENRES:
        payload = genrez.genre_payload(name)
        yield name, payload["name"], genrez.normalize_genre
        yield name, f"{payload['name']} {payload['emoji']}", genrez.normalize_genre


def _vst_pairs():
    for entry in vstz_catalog.catalog_payload()["plugins"]:
        yield entry["key"], entry["name"], vstz_catalog.normalize_key
        yield (entry["key"], f"{entry['kind_emoji']} {entry['name']}",
               vstz_catalog.normalize_key)


REGISTRY = {
    "personaz.skill_key_for": _persona_pairs,
    "personaz.normalize_persona_key": _persona_name_pairs,
    "genrez.normalize_genre": _genre_pairs,
    "vstz.normalize_key": _vst_pairs,
}


def weld_emoji(label):
    """The label with the space next to the emoji removed.

    Only the space ADJACENT to the decoration — not an arbitrary one. "🔎 A&R
    Scout" becomes "🔎A&R Scout", never "🔎 A&RScout": nothing produces the
    latter, and asserting on it would be inventing a failure rather than
    catching one.
    """
    if not label:
        return label
    if not label[0].isalnum() and " " in label:
        head, _, rest = label.partition(" ")
        return head + rest
    if not label[-1].isalnum() and " " in label:
        head, _, tail = label.rpartition(" ")
        return head + tail
    return label


def decoration_forms(label):
    """Every way a client might hand a served label back.

    Not hypothetical — each of these is a form found in the 2.2 document:
    the label as served, the emoji welded to the name (`🎚️Producer`), a
    trailing space (`👻Ghostwriter `), a double space (`Independent  Artist`),
    and wrong case.
    """
    return {
        label,
        weld_emoji(label),
        f"{label} ",
        f" {label}",
        label.replace(" ", "  "),
        label.upper(),
        label.lower(),
    }


class EveryVocabularyResolvesItsOwnLabels(SimpleTestCase):
    def test_every_served_label_resolves_back_to_its_key(self):
        checked = 0
        for name, pairs in REGISTRY.items():
            for key, label, resolve in pairs():
                if not label:
                    continue
                for form in decoration_forms(label):
                    checked += 1
                    with self.subTest(vocabulary=name, key=key, form=form):
                        got = resolve(form)
                        self.assertIsNotNone(
                            got,
                            f"{name}: {form!r} resolved to None. That is a "
                            f"member's saved value disappearing.")
                        self.assertEqual(got, key)
        self.assertGreater(checked, 2000, "the sweep stopped covering the set")

    def test_decoration_alone_never_becomes_a_match(self):
        """Stripping harder must not turn junk into a false positive — the
        failure mode on the other side of this fix."""
        junk = ("🎸", "✨🔥", "1⃣", "   ", "", None, "🎛️ ✨")
        for name, pairs in REGISTRY.items():
            _key, _label, resolve = next(iter(pairs()))
            for value in junk:
                with self.subTest(vocabulary=name, junk=value):
                    self.assertIsNone(resolve(value))

    def test_a_genuinely_unknown_value_stays_unknown(self):
        for name, pairs in REGISTRY.items():
            _key, _label, resolve = next(iter(pairs()))
            with self.subTest(vocabulary=name):
                self.assertIsNone(resolve("definitely not a real entry 9137"))


class RegistryIsComplete(SimpleTestCase):
    """The gap this file closes is a vocabulary nobody remembered to cover.

    If a new normalizer appears and isn't in REGISTRY, this fails and names it
    — which is the whole point. Adding one to REGISTRY is two lines; finding
    out in production that a member's data stopped resolving is not.
    """

    # {registry name: (module, attribute)} — the single-value resolvers, the
    # ones that turn one stored string into one catalog key.
    EXPECTED = {
        "personaz.normalize_persona_key": (personaz, "normalize_persona_key"),
        "personaz.skill_key_for": (personaz, "skill_key_for"),
        "genrez.normalize_genre": (genrez, "normalize_genre"),
        "vstz.normalize_key": (vstz_catalog, "normalize_key"),
    }

    # Deliberately out of scope, with the reason — so "not covered" is always a
    # decision somebody made rather than something nobody noticed.
    NOT_RESOLVERS = {
        # returns a dict, and keeps unrecognised names on purpose
        "normalize_skill",
        "normalize_start",           # a date parser, not a vocabulary
        "normalize_genres",          # list helper, wraps normalize_genre
        "normalize_genres_of_kind",  # list helper
        "normalize_keys",            # list helper, wraps normalize_key
        "normalize_personas",        # list helper, wraps normalize_persona_key
    }

    def test_every_known_normalizer_is_registered(self):
        for name in self.EXPECTED:
            with self.subTest(normalizer=name):
                self.assertIn(name, REGISTRY)

    def test_no_module_grew_a_normalizer_we_are_not_testing(self):
        """Catches the next one being added without a contract test."""
        covered = {attr for _module, attr in self.EXPECTED.values()}
        for module in {m for m, _ in self.EXPECTED.values()}:
            found = {n for n in dir(module)
                     if (n.startswith("normalize") or n.endswith("_key_for"))
                     and callable(getattr(module, n))}
            missing = found - covered - self.NOT_RESOLVERS
            with self.subTest(module=module.__name__):
                self.assertEqual(
                    missing, set(),
                    f"{module.__name__} has a resolver missing from REGISTRY "
                    f"in this file — add it, or list it in NOT_RESOLVERS with "
                    f"a reason. A stored value nothing can resolve vanishes "
                    f"silently, which is how this bug got shipped four times.")
