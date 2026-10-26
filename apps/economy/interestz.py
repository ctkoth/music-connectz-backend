"""Interests, brands and suggested strengths — what a member says they like, and what
that tends to go with.

A member speaks (or types) about their work; the words are scanned against a CLOSED
list of interests and brands, and the member PICKS which of the matches are theirs.
Then, for the persona they are building, the table in `interestz_table.RULES` offers
strengths that interest tends to go with — "you draw by hand, so you may be
dexterous" — each with its reason, and the member accepts or declines.

**This is a suggestion, and it stays one until the member says so.** The codebase
already drew this line twice. `personaz` keeps interests as "never inferred and never
scored", and PersonalitieZ is declared, not detected, because "we detected you're an
Extravert" would be `directz_ai_rating` wearing a quiz. A strength here is the same
kind of thing: it is stored only when the member sends it, it is shown as theirs, and
NOTHING reads it as a measurement. No rating, skill level, median, price or search
rank moves because somebody is called dexterous. `test_interestz` fails if a second
reader appears.

What is not stored: the transcript. The scan runs on text in the request and returns
matches; only the interests, brands and strengths the member PICKS are kept, on the
persona. Speech reaches this endpoint as text the member already has — the keyboard's
voice clip door (`keyz/transcribe/`, metered and priced before the mic) turns it into
words first, so this adds no new audio path and no new thing to disclose.

A brand is something a member likes. It unlocks nothing, is shared with nobody and is
not an ad-targeting profile.
"""
import re

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import personaz
from .interestz_table import BRANDS, INTERESTS, MAX_PICKS, RULES, TRAITS
from .models import profile_for

TEXT_MAX = 6000

RULE = ("Suggestions, not scores. A strength here is what an interest tends to go with, "
        "offered with its reason; it is saved only if you accept it, shown as yours, and "
        "never changes a rating, a skill level or where you appear.")
KEPT = "Nothing you said is stored. Only the interests, brands and strengths you pick are kept."

_PATTERNS = {}


def _pattern(alias):
    if alias not in _PATTERNS:
        _PATTERNS[alias] = re.compile(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", re.I)
    return _PATTERNS[alias]


def _hits(text, table):
    """Keys of `table` whose label or alias appears as a whole word in `text`."""
    found = []
    for key, row in table.items():
        names = (row[0].lower(),) + tuple(row[2])
        if any(_pattern(n).search(text) for n in names):
            found.append(key)
    return found


def scan(text):
    """(interest keys, brand keys) mentioned in `text`. A closed list can only find
    what is on it, which is why nothing sensitive can come out of a transcript."""
    text = str(text or "")[:TEXT_MAX]
    if not text.strip():
        return [], []
    return _hits(text, INTERESTS), _hits(text, BRANDS)


def _words(persona):
    out = set(re.findall(r"[a-z]+", str(persona.get("name") or persona.get("key") or "").lower()))
    for s in persona.get("skills") or []:
        name = s.get("name") if isinstance(s, dict) else s
        out |= set(re.findall(r"[a-z]+", str(name or "").lower()))
    return out


def suggest(persona, interest_keys):
    """Strengths the table offers for this persona and these interests, each with why.

    One row per trait: two rules that point at the same trait are merged, with both
    reasons and both interests, so the member reads one suggestion, not two.
    """
    words = _words(persona or {})
    have = set(interest_keys)
    out = {}
    for who, wants, trait, because in RULES:
        if trait not in TRAITS:
            continue
        if not any(w.startswith(stem) for stem in who for w in words):
            continue
        hit = [k for k in wants if k in have]
        if not hit:
            continue
        row = out.setdefault(trait, {"key": trait, "label": TRAITS[trait][0], "emoji": TRAITS[trait][1],
                                     "because": [], "from": [], "inferred": True, "scored": False})
        if because not in row["because"]:
            row["because"].append(because)
        for k in hit:
            if INTERESTS[k][0] not in row["from"]:
                row["from"].append(INTERESTS[k][0])
    return list(out.values())


def _persona(profile, key):
    """(index, cleaned persona) for `key`, matched on key or name."""
    for i, raw in enumerate(profile.personas or []):
        p = personaz.clean_persona(raw)
        if key and key in (p.get("key"), p.get("name")):
            return i, p
    return None, None


def _pick(wanted, table):
    return [k for k in dict.fromkeys(wanted or []) if k in table][:MAX_PICKS]


class InterestCatalogView(APIView):
    """GET → everything a member can pick, and the rule, before they say a word."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "rule": RULE, "kept": KEPT, "scored": False,
            "interests": [{"key": k, "label": v[0], "emoji": v[1]} for k, v in INTERESTS.items()],
            "brands": [{"key": k, "label": v[0], "category": v[1]} for k, v in BRANDS.items()],
            "traits": [{"key": k, "label": v[0], "emoji": v[1]} for k, v in TRAITS.items()],
        })


class InterestScanView(APIView):
    """POST {text, persona? | persona_key?} → what was mentioned, and what it might go with.

    Reads and returns; writes nothing. The member picks from this and saves with
    `interestz/save/`."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        d = request.data or {}
        interests, brands = scan(d.get("text"))
        persona = None
        if isinstance(d.get("persona"), dict):
            # The screen may be editing a persona that isn't saved yet; the name
            # and skills are all the table reads, and nothing is written.
            persona = personaz.clean_persona(d.get("persona"))
        elif d.get("persona_key"):
            _, persona = _persona(profile_for(request.user), str(d.get("persona_key")))
            if persona is None:
                return Response({"detail": "That persona isn't on your profile yet. Add it in ProfileZ, then come back."},
                                status=status.HTTP_404_NOT_FOUND)
        # What they already declared counts too, so a suggestion doesn't vanish
        # because it wasn't mentioned in this clip.
        declared = []
        if persona:
            declared = [k for k, v in INTERESTS.items()
                        if v[0].lower() in {str(i).strip().lower() for i in persona.get("interests", [])}]
        keys = list(dict.fromkeys(interests + declared))
        return Response({
            "interests": [{"key": k, "label": INTERESTS[k][0], "emoji": INTERESTS[k][1]} for k in interests],
            "brands": [{"key": k, "label": BRANDS[k][0], "category": BRANDS[k][1]} for k in brands],
            "suggestions": suggest(persona, keys) if persona else [],
            "rule": RULE, "kept": KEPT, "scored": False,
        })


class InterestSaveView(APIView):
    """POST {persona_key, interests[], brands[], strengths[]} → the persona, saved.

    Brands and strengths are REPLACED by what is sent (the member's list is what
    they send); interests are added to the ones already there. Keys outside the
    closed lists are dropped, never refused, as every profile write does."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        d = request.data or {}
        profile = profile_for(request.user)
        i, persona = _persona(profile, str(d.get("persona_key") or ""))
        if persona is None:
            return Response({"detail": "That persona isn't on your profile yet. Add it in ProfileZ, then come back."},
                            status=status.HTTP_404_NOT_FOUND)
        have = list(persona.get("interests", []))
        lower = {x.lower() for x in have}
        for k in _pick(d.get("interests"), INTERESTS):
            label = INTERESTS[k][0]
            if label.lower() not in lower:
                have.append(label)
                lower.add(label.lower())
        persona["interests"] = have[:personaz.MAX_TAGS]
        persona["declared_brands"] = _pick(d.get("brands"), BRANDS)
        persona["declared_strengths"] = _pick(d.get("strengths"), TRAITS)
        cleaned = personaz.clean_persona(persona)
        rows = list(profile.personas or [])
        rows[i] = cleaned
        profile.personas = rows
        profile.save(update_fields=["personas", "updated_at"])
        return Response({"persona": cleaned, "kept": KEPT, "scored": False})
