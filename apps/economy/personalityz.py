"""PersonalitieZ — four declared axes, one filter, every search.

A member says which side of four axes they sit on and every search on this
platform can filter by it: VybeZ's dating grid, CollabZ, BattleZ, VenueZ,
MessageZ. One declaration, one filter, one list of axes — not a dating field
that four other screens grow their own copy of.

**It is a DECLARATION, and that is what makes it allowed here.** CLAUDE.md's
substance rule is that every skill, score and rating must measure the real
thing, and the test it gives is "could a member get a good one without getting
good?" This never has to answer that question, because there is no good one:
an axis has two sides and neither is better. So three lines are load-bearing
and none of them may be crossed later for convenience:

- **It never touches a measurement.** No rating, median, skill level,
  leaderboard position or price moves because somebody typed a letter. It
  filters WHO you see and changes nothing about what anyone is called.
- **Nothing is inferred.** It is not scored from posts, takes, message
  patterns or anything else. A "we detected you're an Extravert" would be
  `directz_ai_rating` wearing a personality quiz — a number derived from form
  activity, presented as a fact about a person. If we ever want a real one, it
  is a questionnaire somebody knowingly fills in, stored as a separate
  declared answer.
- **Undeclared is a THIRD state, everywhere.** `-` is not "average" and not a
  default; it is "hasn't said". The search that hides it says so out loud —
  see `filter_reason`.

**Deliberately not called MBTI.** Myers-Briggs is somebody's trademark and the
four-letter codes are in general use; this ships as four axes with their own
plain-English labels, with no type nicknames and no personality descriptions,
which is also the honest scope — we are storing what a member told us, not
publishing a theory of them.
"""

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

# The four axes, in the order they are worn in a code. `code` is the letter
# that lands in that slot of the stored string.
AXES = (
    {"key": "ie", "question": "Where your energy comes from",
     "left": {"code": "I", "label": "Introvert", "blurb": "Recharges alone"},
     "right": {"code": "E", "label": "Extravert", "blurb": "Recharges around people"}},
    {"key": "ns", "question": "What you notice first",
     "left": {"code": "N", "label": "Intuitive", "blurb": "Patterns and where it's going"},
     "right": {"code": "S", "label": "Sensing", "blurb": "Detail and what's in front of you"}},
    {"key": "tf", "question": "How you decide",
     "left": {"code": "T", "label": "Thinking", "blurb": "Logic first"},
     "right": {"code": "F", "label": "Feeling", "blurb": "People first"}},
    {"key": "jp", "question": "How you run a day",
     "left": {"code": "J", "label": "Judging", "blurb": "Planned"},
     "right": {"code": "P", "label": "Perceiving", "blurb": "Open-ended"}},
)

# "hasn't said" — a third state in every slot, never a default side. A member
# who declares two axes and not the other two is stored as e.g. "IN--", which
# is a complete answer to two questions rather than an incomplete answer to
# four.
UNSET = "-"

_SLOT = {a["key"]: i for i, a in enumerate(AXES)}
_LETTERS = {a["key"]: (a["left"]["code"], a["right"]["code"]) for a in AXES}

# Every letter that may appear anywhere, and where. Asserted on import rather
# than trusted: two axes sharing a letter would make a code ambiguous and the
# filter silently wrong, which is the kind of thing that ships.
_ALL = [c for pair in _LETTERS.values() for c in pair]
assert len(set(_ALL)) == len(_ALL), "two axes share a letter"
assert len(AXES) == 4


def clean_code(value):
    """Normalize whatever arrived into a 4-slot code, or "" for nothing said.

    Takes the code itself ("INFP", "in", "IN--") or a per-axis dict
    ({"ie": "I", "tf": "F"}), because the screen that sets this is a row of
    two-way toggles and the one that imports it is a text field. Anything
    unrecognised in a slot becomes UNSET rather than failing the save — a
    profile write must never be refused over a letter, and a wrong letter
    silently kept would be worse than a blank one.
    """
    slots = [UNSET] * len(AXES)

    if isinstance(value, dict):
        for key, letter in value.items():
            slot = _SLOT.get(str(key).strip().lower())
            if slot is None:
                continue
            letter = str(letter or "").strip().upper()[:1]
            if letter in _LETTERS[AXES[slot]["key"]]:
                slots[slot] = letter
    else:
        text = str(value or "").strip().upper()
        # Positional: slot i takes the i-th character, and only if that
        # character is one of THAT axis's two letters. So "INFP" reads
        # straight and "PFNI" reads as nothing rather than as a reversal.
        for i, letter in enumerate(text[:len(AXES)]):
            if letter in _LETTERS[AXES[i]["key"]]:
                slots[i] = letter

    code = "".join(slots)
    return "" if code == UNSET * len(AXES) else code


def as_dict(code):
    """A stored code back as {axis_key: letter}, skipping what wasn't said."""
    code = (code or "").ljust(len(AXES), UNSET)
    return {a["key"]: code[i] for i, a in enumerate(AXES) if code[i] != UNSET}


def matches(code, wanted):
    """Does this member's code satisfy every axis the searcher picked?

    `wanted` is {axis_key: letter}. AND across axes, like every other filter
    in MembersView. **An undeclared axis never matches** — a search for
    Introverts that returned everyone who said nothing would be a filter that
    does not filter, and the searcher would never know. The count of who was
    dropped for that reason goes back with the results instead.
    """
    mine = as_dict(code)
    return all(mine.get(key) == letter for key, letter in wanted.items())


def wanted_from(params):
    """Read the axis filters off a querystring: ?ie=I&tf=F.

    Also accepts `personality=INFP` as a shorthand for all four at once, which
    is what a shared link carries.
    """
    wanted = {}
    whole = clean_code(params.get("personality", ""))
    if whole:
        wanted.update(as_dict(whole))
    for axis in AXES:
        letter = str(params.get(axis["key"]) or "").strip().upper()[:1]
        if letter in _LETTERS[axis["key"]]:
            wanted[axis["key"]] = letter
    return wanted


def filter_reason(wanted, undeclared):
    """What the searcher needs told when a filter is on.

    An empty grid has two completely different causes — nobody matches, or
    nobody has said — and they look identical. On a platform where this field
    is new, the second one is almost always the real answer, and letting
    somebody conclude "there are no Introverts here" from a field nobody has
    filled in yet is the emptiest kind of wrong.
    """
    if not wanted or not undeclared:
        return ""
    return (f"{undeclared} member{'s' if undeclared != 1 else ''} hidden for not having "
            "said — an axis nobody declared is not an axis they're the other side of.")


class PersonalityAxesView(APIView):
    """GET /api/economy/personalityz/ — the four axes and their two sides.

    Published rather than retyped, for the reason CLAUDE.md gives about tier
    numbers: a list stated in three places reads three ways within a year. The
    profile screen renders these as toggles, every search renders them as
    filters, and VybeZ renders them as a grid — three surfaces, one list.

    Open logged-out. A stranger reading the join page should be able to see
    what the platform will ask them, and there is nothing here about anybody.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({
            "axes": AXES,
            "unset": UNSET,
            # Said out loud because a client would otherwise have to guess
            # from the shape, and the guess ("blank means the left side") is
            # the one that breaks the whole design.
            "note": ("Each axis has two sides and neither is better — this is a "
                     "declaration, never a score, and it never moves a rating, a "
                     "skill level or a leaderboard position. An axis you haven't "
                     "answered stays unanswered; it is not filled in for you."),
        })
