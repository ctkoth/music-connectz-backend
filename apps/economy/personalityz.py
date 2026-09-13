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

# ---------------------------------------------------------------- the test

"""A questionnaire, which is the ONLY honest way this field gets filled in
for somebody who does not already know their letters.

The toggles came first and stay: a member who knows their type says so in one
tap. But "what's your type?" is a question most people cannot answer, and the
alternative a platform reaches for next is inferring it from behaviour — which
is the line personalityz.py exists to hold. A questionnaire is the third
option: still a declaration, just one made an answer at a time.

Two properties keep it on the right side of the substance rule:

* **Neither side of any axis scores higher.** There is no total, no percentile
  and no "rare type". `clarity` says how CONSISTENTLY somebody answered, not
  how well — a 55% Introvert has not done worse than a 95% one, and the copy
  says so wherever it renders.
* **A tie stays unsaid.** An axis answered exactly down the middle returns "-"
  rather than a coin flip, which is the same three-state rule the column has
  had from the start. Being genuinely in the middle is an answer.
"""

# 5-point, symmetric. The number is how far toward the statement's own side
# the answer pushes, so a bank with equal statements on each side cannot lean.
CHOICES = (
    (-2, "Not me at all"),
    (-1, "Not really"),
    (0, "In the middle"),
    (1, "Sounds like me"),
    (2, "Exactly me"),
)
_MAX = max(abs(v) for v, _ in CHOICES)

# Six statements per side per axis. BALANCE IS LOAD-BEARING: an axis with more
# statements on one side measures agreeableness, not personality — people say
# yes more than no, so an unbalanced bank hands everybody the same letter.
# `test_personalityz` asserts it rather than trusting the eye.
BANK = {
 "ie": [
  ("A long session with a room full of people leaves me charged up", "E"),
  ("I do my best writing alone, with the door shut", "I"),
  ("I'd rather play the room than play to a camera by myself", "E"),
  ("After a show I want quiet, not the afterparty", "I"),
  ("I think out loud, and the idea arrives while I'm talking", "E"),
  ("I need to have worked it out before I say it", "I"),
  ("Meeting new collaborators is the fun part, not the cost", "E"),
  ("A group chat with twenty people in it drains me", "I"),
  ("I'll happily jump on a live with someone I just met", "E"),
  ("My best ideas come on a walk on my own", "I"),
  ("Silence in a session makes me want to fill it", "E"),
  ("I turn down more sessions than I take, on purpose", "I"),
 ],
 "ns": [
  ("I hear where a track could go before I hear what it is", "N"),
  ("I notice the hi-hat is 3ms late before I notice the mood", "S"),
  ("I'd rather sketch ten ideas than finish one properly", "N"),
  ("Give me the reference track and I'll match it exactly", "S"),
  ("I care more about what a song means than how it was made", "N"),
  ("I keep detailed notes of settings that worked", "S"),
  ("I trust a hunch about a direction over the data", "N"),
  ("I want the brief in writing before I start", "S"),
  ("I like work that leaves something unresolved", "N"),
  ("A plan I can follow step by step is a good plan", "S"),
  ("I'm drawn to sounds nobody has used yet", "N"),
  ("I'd rather perfect a familiar sound than chase a new one", "S"),
 ],
 "tf": [
  ("Tell me the mix is wrong and why; don't soften it", "T"),
  ("How feedback is delivered matters as much as what it says", "F"),
  ("I pick collaborators on skill, not on whether we click", "T"),
  ("I won't work with someone talented if the vibe is off", "F"),
  ("A fair split is the one the numbers support", "T"),
  ("A fair split is the one everyone feels good about", "F"),
  ("I can cut a verse I love if it doesn't serve the track", "T"),
  ("I'll keep a part because of what it meant to whoever played it", "F"),
  ("Criticism of my work isn't criticism of me", "T"),
  ("A harsh note on my work stays with me for days", "F"),
  ("In a disagreement I argue the point, not the person", "T"),
  ("I'd rather lose the argument than damage the relationship", "F"),
 ],
 "jp": [
  ("I set a release date and I hit it", "J"),
  ("A release is done when it's done", "P"),
  ("I finish one track before starting the next", "J"),
  ("I have thirty unfinished ideas open right now", "P"),
  ("I plan a session before I get in the room", "J"),
  ("The best sessions are the ones nobody planned", "P"),
  ("Deadlines help me; they don't stress me", "J"),
  ("I do my best work in the last hour before it's due", "P"),
  ("I like knowing what the week looks like", "J"),
  ("I'd rather keep the day open and see what happens", "P"),
  ("An unfinished project nags at me until it's closed", "J"),
  ("Leaving things open keeps them alive", "P"),
 ],
}


# How many statements per AXIS each depth asks. Basic is four (two a side) —
# short enough to finish cold, balanced enough to mean something. Three a side
# is impossible to balance, which is why it is not three.
DEPTHS = {"basic": 4, "advanced": 12}


def questions(depth="basic"):
    """The statements to ask, interleaved across axes.

    Interleaved rather than grouped: twelve Introvert-or-Extravert statements
    in a row tells somebody what is being measured and invites them to answer
    the picture they have of themselves instead of the question. Taking them
    a side at a time also keeps each depth balanced by construction.
    """
    per = DEPTHS.get(depth, DEPTHS["basic"])
    picked = {}
    for axis, rows in BANK.items():
        left, right = [], []
        for i, (text, side) in enumerate(rows):
            (left if side == _LETTERS[axis][0] else right).append((i, text, side))
        half = per // 2
        picked[axis] = sorted(left[:half] + right[:half])
    out = []
    for n in range(per):
        for axis in (a["key"] for a in AXES):
            if n < len(picked[axis]):
                i, text, side = picked[axis][n]
                out.append({"id": f"{axis}-{i}", "axis": axis, "side": side, "text": text})
    return out


def score(answers, depth="basic"):
    """{question_id: -2..2} → the code, and how clear each axis came out.

    `clarity` is |net| over the most that axis could have scored, as a
    percentage. It is NOT a quality: it says the answers pointed one way
    consistently, and somebody genuinely balanced is not worse at being a
    person. Nothing in this codebase may rank on it — `test_personalityz`
    asserts no rating, median or leaderboard reads it.
    """
    asked = {q["id"]: q for q in questions(depth)}
    nets = {a["key"]: 0 for a in AXES}
    counted = {a["key"]: 0 for a in AXES}
    valid = {v for v, _ in CHOICES}

    for qid, raw in (answers or {}).items():
        q = asked.get(qid)
        if not q:
            continue
        try:
            v = int(raw)
        except (TypeError, ValueError):
            continue
        if v not in valid:
            continue
        left, right = _LETTERS[q["axis"]]
        # Toward the statement's own side, whichever side that is.
        nets[q["axis"]] += v if q["side"] == right else -v
        counted[q["axis"]] += 1

    slots, clarity = {}, {}
    for axis in nets:
        left, right = _LETTERS[axis]
        net, n = nets[axis], counted[axis]
        if not n or net == 0:
            # Unanswered, or answered exactly down the middle. Both are "not
            # said" — never a guess, and never the left side by default.
            clarity[axis] = 0
            continue
        slots[axis] = right if net > 0 else left
        clarity[axis] = round(100 * abs(net) / (n * _MAX))

    return {
        "code": clean_code(slots),
        "clarity": clarity,
        "answered": sum(counted.values()),
        "asked": len(asked),
    }


class PersonalityTestView(APIView):
    """GET the questions, POST the answers. Open logged-out, on purpose.

    The trial take is the one door on this platform that has ever converted a
    stranger, and the reason is that it hands them a fact about THEMSELVES
    before asking for anything. This is the same shape with a much lower floor:
    no microphone, no permission prompt, no performance — sixteen statements
    and a result. The register CTA is "save this", not "sign up".

    A logged-in member's result is saved to their profile; a visitor's is
    theirs to keep or lose, and the response says which happened rather than
    implying a save that did not occur.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        depth = request.query_params.get("depth", "basic")
        if depth not in DEPTHS:
            depth = "basic"
        qs = questions(depth)
        return Response({
            "depth": depth,
            "questions": qs,
            "count": len(qs),
            "choices": [{"value": v, "label": l} for v, l in CHOICES],
            "depths": [{"key": k, "questions": v * len(AXES)} for k, v in DEPTHS.items()],
            "axes": AXES,
            # Said before the first question rather than after the result,
            # which is the cost/gain rule pointed at a questionnaire: what you
            # are about to spend is your time, and what comes back is four
            # letters and nothing else.
            "note": ("Neither side of any axis is better and there is no total score. "
                     "An axis you answer down the middle stays unanswered — being in "
                     "the middle is an answer, not a failure to have a personality."),
        })

    def post(self, request):
        depth = str((request.data or {}).get("depth") or "basic")
        if depth not in DEPTHS:
            depth = "basic"
        result = score((request.data or {}).get("answers") or {}, depth)

        saved = False
        if request.user.is_authenticated:
            from .models import profile_for
            prof = profile_for(request.user)
            prof.personality = result["code"]
            prof.personality_detail = {"clarity": result["clarity"], "depth": depth}
            prof.save(update_fields=["personality", "personality_detail"])
            saved = True

        return Response({
            **result,
            "depth": depth,
            "axes": as_dict(result["code"]),
            # Never implied. A visitor's result lives in their browser until
            # they make an account, and saying "saved" to somebody with no
            # account is the kind of small lie that gets found out at login.
            "saved": saved,
        })
