"""SubstanceZ: which substances, and how often — one list, owned here.

The substance list was typed twice (ProfileZ.jsx and metricz.py, in different
orders) and the frequencies were two words and a legacy placeholder. Both live
here now and are SERVED (`GET /api/economy/substancez/`), so no screen retypes
either — a client that spelled out the scale itself would be the second place
"often" is defined.

**A frequency is a declaration, never a measurement.** Nothing is inferred
from anything else a member does, it never moves a rating or a score, and it is
adult-only wherever it is shown to other people (metricz, the `uses` search).

**The scale has to mean the same thing to everybody.** "Often" is a different
number to different people, so each step carries a plain-language `hint`
("most weeks") that is shown beside the choice. A scale people read three ways
is decoration wearing a measurement's clothes.

**Known drift, accepted.** Rows saved under the old two-step scale hold
`sometimes` / `often` with no definition behind them (`often` was the top step,
so a daily user's only choice). They are kept as stored and now read under the
defined scale — "a few times a month" / "most weeks" — rather than being reset
to `yes`, which would throw away what members actually told us. The cost is
that an old `often` may be a daily user whom an "up to often" search lets
through; they fix it by picking `daily`, and the profile screen shows what each
step means beside the choice. Re-labelling them is a one-line migration if that
trade is ever judged wrong.

**Nothing is guessed.** A selection saved before frequency existed is kept as
`"yes"` — we know they picked it, we do not know how often — and the profile
screen asks them to say, rather than rounding it to "sometimes". Unknown
stances from a client fall back to the same placeholder, and unknown substance
KEYS are dropped: the closed list is what the filter, the counts and the card
can all read, and a stored key no screen can name is a row nobody can clear.
"""

SUBSTANCES = [
    ("cigarettes", "Cigarettes", "🚬"),
    ("caffeine", "Caffeine", "☕"),
    ("alcohol", "Alcohol", "🍺"),
    ("thc", "THC", "🍃"),
    ("dxm", "DXM", "🧴"),
    ("adderall", "Adderall", "💊"),
    ("benzos", "Benzos", "💊"),
    ("opioids", "Opioids", "💊"),
    ("heroin", "Heroin", "💉"),
    ("crack", "Crack", "💎"),
    ("meth", "Meth", "💎"),
]
SUBSTANCE_KEYS = [s[0] for s in SUBSTANCES]

# Lowest to highest. The ORDER is the meaning: `rank()` and the "up to"
# search both read it, so a step inserted in the wrong place changes who a
# filter hides. `sometimes` and `often` are the two that already existed and
# keep their stored names; `rarely` and `daily` were added around them.
FREQUENCIES = [
    ("rarely", "Rarely", "a few times a year"),
    ("sometimes", "Sometimes", "a few times a month"),
    ("often", "Often", "most weeks"),
    ("daily", "Daily", "every day, or nearly"),
]
FREQUENCY_KEYS = [f[0] for f in FREQUENCIES]
STANCES = tuple(FREQUENCY_KEYS)

# Saved before frequency existed. Kept distinct rather than guessed.
STANCE_LEGACY = "yes"
# "use" predates this file and may sit in old rows; it reads as active.
ACTIVE_STANCES = {"use", *FREQUENCY_KEYS, STANCE_LEGACY}


def rank(stance):
    """0-based position on the scale, or None when the frequency is unknown
    (the legacy placeholder, or a stance this code has never heard of)."""
    return FREQUENCY_KEYS.index(stance) if stance in FREQUENCY_KEYS else None


def within(stance, max_frequency):
    """Is this declared stance at or below `max_frequency` ("okay with up to
    sometimes")?

    An UNKNOWN frequency is not within any limit below the top: a search that
    says "up to sometimes" cannot promise a member who only said "yes", and
    guessing in the searcher's favour is the dishonest direction. At the top
    of the scale everything is within, which is the same as no limit.
    """
    if max_frequency not in FREQUENCY_KEYS:
        return False
    r = rank(stance)
    if r is None:
        return max_frequency == FREQUENCY_KEYS[-1]
    return r <= FREQUENCY_KEYS.index(max_frequency)


def clean_substances(value):
    """Normalize whatever the client sent into {key: stance}.

    Accepts the current dict form and the legacy list form, so an older client
    keeps working and an already-saved list is repaired on the next write.
    """
    known = set(SUBSTANCE_KEYS)
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:40]:
            key = str(k)[:40]
            if key not in known:
                continue
            stance = str(v or "").lower()
            out[key] = stance if stance in STANCES else STANCE_LEGACY
        return out
    if isinstance(value, list):
        return {str(k)[:40]: STANCE_LEGACY for k in value[:40] if str(k)[:40] in known}
    return {}


def visible_substances(p, viewer, audience=None):
    """The declarations of profile `p` that `viewer` is entitled to read.

    ONE reader, because every path that turns a declaration into something
    another member can see or search on (the `uses` and avoid filters, the
    frequency on a card, a member's profile) has to answer the same two
    questions, and answering them at each call site is how three of them came
    to answer neither:

    * **The wall.** SubstanceZ is adult-only in both directions: a minor's
      stored declarations are read as empty (nobody is matched, filtered or
      told anything about a minor's use) and a minor viewer reads nothing of
      anyone else's.
    * **The member's own setting.** `substances` is PRIVATE unless they opened
      it in VisibilitieZ. A hidden declaration is read as undeclared — which
      is also what makes "steer clear of people who use X" safe: if a hidden
      user were filtered OUT by it, the filter would tell the searcher they use X.

    `viewer` None is an anonymous viewer, so a caller that forgets to pass one
    fails closed.
    """
    from .models import adult_only_reason, profile_is_minor
    from .visibility import can_see
    if profile_is_minor(p) or not can_see(p, "substances", viewer, audience):
        return {}
    # The wall runs both ways: a minor VIEWER reads nothing of anyone else's.
    # (Your own row is always yours; can_see already let the owner through.)
    if (viewer is not None and getattr(viewer, "is_authenticated", False)
            and viewer.pk != p.user_id and adult_only_reason(viewer)):
        return {}
    return clean_substances(p.substances)


def scale():
    """The served shape: what ProfileZ renders and nothing else retypes."""
    return {
        "substances": [{"key": k, "label": l, "emoji": e} for k, l, e in SUBSTANCES],
        "frequencies": [{"key": k, "label": l, "hint": h} for k, l, h in FREQUENCIES],
        "legacy": STANCE_LEGACY,
    }
