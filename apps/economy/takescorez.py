"""The coach's memory, and everything that needed one.

For the whole life of this app the coach produced five scores, handed them to
the browser and forgot them. `TakeAnalysis` kept librosa's read of one upload;
`TrainingProfile` kept XP and a streak; nothing kept a score. So the blueprint's
intelligence layer had no material to work with, and `instruments`' own caveat
had to say Consistency, Voice Health and Goal Match "come from your history,
not a single clip" — an honest refusal with no history behind it to serve.

Two things live here:

* **Recording** a take's scores (`record`), which is four lines at the one call
  site that already has every value in hand.
* **Reading them back as findings** — the detected range, the trend, the
  weakest dimension, the strain level, and the three history scores a single
  take genuinely cannot show.

THE RULES THIS FOLLOWS, which are the ones already written down
---------------------------------------------------------------

**Nothing here invents a number.** Every finding returns `None` with a reason
when the history is too thin, and the reason is served so a screen can print
it. A member with two takes has not got a bad consistency score; they have not
got one. That is the substance rule's own test applied backwards: a number
that would move without the underlying thing moving must not be shown.

**Strain is derived, never counted.** There is no strain column. A counter is
a number that can drift out of step with what happened; a history is one that
can be argued with — the same call `LilithPayout` made about daily caps. It
also means recovery clears itself: the window rolls, so three quiet days
genuinely end it and nothing has to remember to.

**A safety block is not a tier feature.** The blueprint is explicit that AI and
automation may not override recovery warnings, so `recovery_block` refuses the
hard difficulties for a strained member at every tier, StatZ included. It is
the one refusal in this app that a subscription cannot buy past.
"""
import re
from datetime import timedelta

from django.utils import timezone

from .instruments import profile_for_app, scores_for
from .models import CoachAgreement, InstrumentProfile, TakeScore

# A dimension at or under this, out of the coach's 1-10, is a low. Not a
# failure — a low. Four out of ten on breath is a real reading and one of them
# means nothing; it is the repeat that matters, which is what THRESHOLD is for.
LOW_AT = 4

# How many lows in the window before it is strain rather than a bad day. The
# member's own answer to "how quickly do you feel it" picks the column, which
# is the only thing `fatigue_sensitivity` does — it may never move a score,
# because how quickly somebody tires is not how good they are.
THRESHOLD = {"high": 2, "normal": 3, "low": 4}
DEFAULT_SENSITIVITY = "normal"

# Strain is a thing about the last few days, not about a career. Three days
# because that is roughly how long vocal fatigue takes to settle, and because a
# window a member cannot outlast is a punishment rather than a warning.
WINDOW_HOURS = 72

# Which dimensions say somebody is pushing too hard. Not every low score is a
# health signal — a low Delivery is a performance note and a low Breath is a
# body one, and treating them the same would put somebody in recovery for
# sounding bored.
STRAIN_DIMENSIONS = ("breath", "range")

# The difficulties a strained member is held back from. Named from
# `instruments.DIFFICULTIES` rather than retyped as a rule about "advanced".
HARD = ("performer", "stageboss")

# How far back "lately" goes for the history scores. Two weeks: long enough
# that one missed day is not a collapse, short enough that last month's habit
# is not still being reported as this month's.
RECENT_DAYS = 14
# Below this many takes in the window, every history finding is None. Three is
# the smallest number from which "twice out of three" means anything at all.
MIN_TAKES = 3


# ------------------------------------------------------------- recording

_NOTE = re.compile(r"\b([A-G])([#b♯♭]?)([0-8])\b")
_SEMI = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _midi(note):
    m = _NOTE.fullmatch(note)
    if not m:
        return None
    letter, acc, octv = m.groups()
    n = _SEMI[letter] + (1 if acc in ("#", "♯") else -1 if acc in ("b", "♭") else 0)
    return (int(octv) + 1) * 12 + n


def parse_range(text, ranges):
    """Pull a range class and its note edges out of the coach's own prose.

    The coach answers `range_profile` as a sentence on purpose — it is asked to
    say when a take is too short to tell rather than guess, and prose is how it
    says that. So this parses conservatively and returns blanks rather than a
    reading it is not sure of: a range invented from four bars is, in the
    prompt's own words, a lie somebody will build a warm-up around, and one
    invented from a sentence afterwards is the same lie with an extra step.

    Returns (class_key, low_note, high_note), any of which may be "".
    """
    text = str(text or "")
    if not text:
        return "", "", ""

    lower = text.lower()
    cls = ""
    for key, label in ranges or []:
        # The label carries an emoji ("Bass 🧔‍♂️"); match the word, not the mark.
        word = label.split()[0].lower()
        if re.search(rf"\b{re.escape(word)}\b", lower) or re.search(rf"\b{re.escape(key)}\b", lower):
            cls = key
            break

    notes = [f"{m.group(1)}{m.group(2)}{m.group(3)}" for m in _NOTE.finditer(text)]
    low = high = ""
    if len(notes) >= 2:
        pitched = sorted(((_midi(n), n) for n in notes if _midi(n) is not None))
        # An octave apart at minimum. Two notes five semitones apart in a
        # sentence are far more likely to be an example than a range, and a
        # "range" narrower than a fifth is not one anybody should train against.
        if len(pitched) >= 2 and pitched[-1][0] - pitched[0][0] >= 12:
            low, high = pitched[0][1], pitched[-1][1]
    return cls, low, high


def read_of(payload):
    """The coach's read, trimmed to what the history shows and exports.

    Whitelisted field by field: it is stored for good and shown to the member
    later, so nothing the model volunteers rides in, and the transcribed lyrics
    (`lyrics_read`) are deliberately NOT kept.
    """
    def lines(v, n=6):
        return [str(x)[:300] for x in v][:n] if isinstance(v, list) else []
    practice = [{"what": str(p.get("what", ""))[:200], "why": str(p.get("why", ""))[:300],
                 "how": str(p.get("how", ""))[:400]}
                for p in (payload.get("practice") or []) if isinstance(p, dict) and p.get("what")][:3]
    out = {"verdict": str(payload.get("verdict", ""))[:400],
           "strengths": lines(payload.get("strengths")), "fixes": lines(payload.get("fixes")),
           "practice": practice}
    for key, field in (("exact", "score_exact"), ("hook", "hook_score"), ("feelz", "feelz_score")):
        v = payload.get(field)
        if isinstance(v, (int, float)):
            out[key] = v
    # The rest of what the coach said about the take, so a share or post made from the HISTORY is as
    # complete as one made from the live result — an audit found it thinner: no where-they-are / aiming
    # at, no song score, no style read, no next drill, and none of it on the card.
    for k, n in (("now", 600), ("goal", 600), ("style_fit", 600), ("range_profile", 600),
                 ("next_drill", 300), ("song_why", 400)):
        if payload.get(k):
            out[k] = str(payload[k])[:n]
    if isinstance(payload.get("song_score"), (int, float)):
        out["song_score"] = payload["song_score"]
    if payload.get("feelz_emotion"):
        out["feelz_emotion"] = str(payload["feelz_emotion"])[:60]
    # The reasons travel with the numbers: a HookZ or FeelZ with no sentence beside it is the
    # "score with no description" this app does not ship. Only kept when the number is.
    # Whether each one is INSIDE the overall the member was shown, so a row can say "counts" or
    # "beside" truthfully instead of assuming. Old takes carry neither flag and say nothing.
    for field in ("hook_counted", "feelz_counted"):
        if isinstance(payload.get(field), bool) and field.split("_")[0] in out:
            out[field] = payload[field]
    if "feelz" in out and isinstance(payload.get("feelz_tips"), list):
        from .vocalcoach import _feelz_tips
        tips = _feelz_tips(payload["feelz_tips"], out["feelz"], payload.get("feelz_cause") or "")   # one shape, one cleaner
        if tips:
            out["feelz_tips"] = tips
    if "feelz" in out:
        from .vocalcoach import _feelz_cause
        c = _feelz_cause(payload.get("feelz_cause"), out["feelz"])
        if c:
            out["feelz_cause"] = c
    if isinstance(payload.get("mix_tips"), list) and payload.get("feelz_cause") != "performance":
        from .vocalcoach import _mix_tips
        mix = _mix_tips(payload["mix_tips"])
        if mix:
            out["mix_tips"] = mix
    for key, field in (("hook_why", "hook_why"), ("feelz_why", "feelz_why")):
        if payload.get(field) and key.split("_")[0] in out:
            out[key] = str(payload[field])[:400]
    return {k: v for k, v in out.items() if v not in ("", [], None)}


def record(user, app_key, payload, *, difficulty="", genre="", target="",
           style="", upload=None, source="", ref="", context=None):
    """Keep one coached take. Best-effort — a score must reach the member
    whether or not it reaches the table.

    Swallowing here is the same call `signbonus.try_award` makes: the thing the
    member paid for is the coaching, and a bookkeeping failure must never turn
    a successful take into an error. What it costs is one missing row in a
    trend, which is recoverable; what the alternative costs is the take.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return None
    try:
        prof = profile_for_app(app_key)
        # The take's OWN dimension set, including the optional writing score
        # when the member asked for one. Whitelisting against the profile's
        # five would drop it on the floor — the coach would show a Writing
        # chip and the history would never have heard of it.
        dims = scores_for(app_key, lyrics=bool(payload.get("rated_lyrics")),
                          mix=bool(payload.get("rated_mix")))
        # Whitelisted against the instrument's own dimensions, so a key the
        # model invents cannot reach the column — the same guard the payload
        # itself already passes through in `score_take`.
        scores = {k: v for k, v in (payload.get("scores") or {}).items()
                  if k in dims and isinstance(v, int)}
        # The number the member was SHOWN. This used to be the plain mean of the
        # dimensions, which is not what the coach reports (it leans on strengths,
        # and counts HookZ and FeelZ), so the history disagreed with the score a
        # member had just been given. Falls back to the mean for a payload that
        # carries no overall.
        shown = payload.get("score")
        overall = (shown if isinstance(shown, int) and 1 <= shown <= 10
                   else round(sum(scores.values()) / len(scores)) if scores else None)
        weakest = min(scores, key=lambda k: scores[k]) if scores else ""
        cls, low, high = parse_range(payload.get("range_profile"), prof["ranges"])
        return TakeScore.objects.create(
            user=user, app_key=app_key, scores=scores, overall=overall,
            weakest=weakest, difficulty=str(difficulty or "")[:16],
            genre=str(genre or "")[:60], target=str(target or "")[:60],
            style=str(style or "")[:60],
            range_class=cls, low_note=low, high_note=high,
            upload=upload, source=str(source or "")[:16], ref=str(ref or "")[:64],
            # What the coach heard, kept so a later gear-advice run can tie its
            # reasons to THIS take. Not a purchase: upgrades.items is the paid part.
            upgrades=({"context": context} if context else {}),
            read=read_of(payload),
        )
    except Exception:                                       # pragma: no cover
        return None


# --------------------------------------------------------------- reading

# One screen (`progress`) asks the same two questions of the same tables a dozen times — the
# declarations five times, and "the last 14 days of takes" three. `_memo` is set for the length of
# that one call only and is None everywhere else, so no other caller (and no write path) can read a
# stale answer. The lists it hands back are only ever iterated or copied, never mutated in place.
import contextvars                                                    # noqa: E402
_memo = contextvars.ContextVar("takescorez_memo", default=None)


def profile_row(user, app_key):
    """The member's declarations for this instrument. Never auto-created on a
    read — an empty row for every member who ever opened a coach is a table of
    nothing, and `get_or_create` on a GET is a write on a read."""
    memo = _memo.get()
    key = ("row", user.pk, app_key)
    if memo is not None and key in memo:
        return memo[key]
    row = InstrumentProfile.objects.filter(user=user, app_key=app_key).first()
    if memo is not None:
        memo[key] = row
    return row


def _recent(user, app_key, *, hours=None, days=None, limit=200):
    memo = _memo.get()
    key = ("recent", user.pk, app_key, hours, days, limit)
    if memo is not None and key in memo:
        return memo[key]
    since = timezone.now() - (timedelta(hours=hours) if hours else timedelta(days=days))
    out = list(TakeScore.objects.filter(user=user, app_key=app_key, created_at__gte=since)[:limit])
    if memo is not None:
        memo[key] = out
    return out


def detected(user, app_key):
    """The range the coach last actually heard, and when.

    The member's own `confirmed_range` is NOT consulted here and must not be:
    this is the measurement and that is the declaration, and the point of
    keeping both is that a member can see the two disagree. Collapsing them
    into one field is how a declaration quietly becomes a finding.
    """
    row = (TakeScore.objects.filter(user=user, app_key=app_key)
           .exclude(range_class="").first())
    if not row:
        return {"range": "", "low": "", "high": "", "at": None,
                "why": "No take has been long enough to read a range from yet."}
    return {"range": row.range_class, "low": row.low_note, "high": row.high_note,
            "at": row.created_at.isoformat(), "why": ""}


def strain(user, app_key):
    """How hard this member has been pushing, from their last few days of takes.

    Derived every time rather than counted, so recovery is real: the window
    rolls, and three days without a low genuinely clears it. Nothing has to
    remember to reset anything, which is the failure mode a counter would have.
    """
    prof = profile_for_app(app_key)
    watched = [d for d in STRAIN_DIMENSIONS if d in prof["scores"]]
    if not watched:
        # A drummer has no breath score. Saying "no strain detected" for an
        # instrument that cannot produce the signal would be a clean bill of
        # health nobody examined.
        return {"level": "unmeasured", "lows": 0, "threshold": None, "flags": [],
                "why": f"{prof['label']} takes aren't scored on anything that "
                       "reads as strain, so this isn't measured here."}

    row = profile_row(user, app_key)
    sens = (row.fatigue_sensitivity if row and row.fatigue_sensitivity
            else DEFAULT_SENSITIVITY)
    threshold = THRESHOLD.get(sens, THRESHOLD[DEFAULT_SENSITIVITY])

    takes = _recent(user, app_key, hours=WINDOW_HOURS)
    flags = {}
    for t in takes:
        for d in watched:
            v = (t.scores or {}).get(d)
            if isinstance(v, int) and v <= LOW_AT:
                flags[d] = flags.get(d, 0) + 1
    lows = sum(flags.values())

    level = "strain" if lows >= threshold else "watch" if lows >= threshold - 1 else "clear"
    labels = prof["scores"]
    named = ", ".join(f"{labels.get(d, d)} ×{n}" for d, n in sorted(flags.items()))
    why = {
        "clear": "Nothing in the last few days reads as strain.",
        "watch": f"{named} in the last {WINDOW_HOURS // 24} days. One more and "
                 f"the hard difficulties go quiet for a bit.",
        "strain": f"{named} in the last {WINDOW_HOURS // 24} days. Easier work "
                  f"until that settles — it clears itself.",
    }[level]
    return {"level": level, "lows": lows, "threshold": threshold,
            "flags": sorted(flags), "sensitivity": sens, "why": why}


def recovery_block(user, app_key, difficulty):
    """The reason this take may not be attempted at this difficulty, or None.

    **No tier buys past this**, and that is the blueprint's rule rather than a
    preference: "AI or automation features must not override recovery, health,
    or safety warnings." It is the only refusal in this app a subscription
    cannot lift, so it holds one line and holds it for everybody.

    It never blocks a take outright — a limit that says whether rather than how
    much is a door out (`catalog.py`), and here it would also be the wrong
    safety answer: somebody told they may not sing today will sing anyway,
    somewhere that is not counting.
    """
    if str(difficulty or "").lower() not in HARD:
        return None
    s = strain(user, app_key)
    if s["level"] != "strain":
        return None
    return {"blocked_difficulty": difficulty, "allowed": ["starter", "builder"],
            "why": s["why"], "level": s["level"]}


def weakest(user, app_key):
    """Which dimension to drill, from the last two weeks rather than one take.

    One take's worst score is noise — everybody has an off dimension on any
    given day. What repeats is a weak spot, which is the difference between
    Auto-Weakspot Detect and a coincidence.
    """
    takes = _recent(user, app_key, days=RECENT_DAYS)
    if len(takes) < MIN_TAKES:
        return {"key": "", "label": "", "average": None,
                "why": f"{len(takes)} of {MIN_TAKES} takes. One take's worst "
                       "score is a bad day, not a weak spot."}
    # Every dimension this member has actually been scored on, writing
    # included — a weak spot the coach can name but the history cannot is a
    # weak spot nobody can act on.
    dims = scores_for(app_key, lyrics=True)
    sums = {}
    for t in takes:
        for k, v in (t.scores or {}).items():
            if k in dims and isinstance(v, int):
                sums.setdefault(k, []).append(v)
    if not sums:
        return {"key": "", "label": "", "average": None, "why": "No scored dimensions yet."}
    key = min(sums, key=lambda k: sum(sums[k]) / len(sums[k]))
    avg = sum(sums[key]) / len(sums[key])
    return {"key": key, "label": dims.get(key, key), "average": round(avg, 1),
            "takes": len(takes), "why": ""}


def trend(user, app_key, days=RECENT_DAYS):
    """Per-dimension movement: the first half of the window against the second.

    Both halves carry their own count, for the reason FunnelZ's headline does:
    a dimension that moved from one take to one take has not moved.
    """
    takes = sorted(_recent(user, app_key, days=days), key=lambda t: t.created_at)
    dims = scores_for(app_key, lyrics=True)
    if len(takes) < MIN_TAKES * 2:
        return {"rows": [], "why": f"{len(takes)} of {MIN_TAKES * 2} takes. A trend "
                                   "drawn through fewer is a line through two dots."}
    half = len(takes) // 2
    rows = []
    for k, label in dims.items():
        early = [t.scores[k] for t in takes[:half] if isinstance((t.scores or {}).get(k), int)]
        late = [t.scores[k] for t in takes[half:] if isinstance((t.scores or {}).get(k), int)]
        if not early or not late:
            continue
        a, b = sum(early) / len(early), sum(late) / len(late)
        rows.append({"key": k, "label": label, "was": round(a, 1), "now": round(b, 1),
                     "change": round(b - a, 1), "was_n": len(early), "now_n": len(late)})
    return {"rows": sorted(rows, key=lambda r: r["change"]), "why": ""}


# ------------------------- the three a single take genuinely cannot show

def consistency(user, app_key):
    """Days trained out of the last fourteen, on the coach's own 1-10 scale.

    This is the honest version of what `_HISTORY_CAVEAT` declined to score.
    It measures showing up, which is effort — and effort is allowed to move XP
    and a streak but never a rating, so this is reported as a habit and is
    kept out of anything that ranks members.
    """
    takes = _recent(user, app_key, days=RECENT_DAYS)
    if len(takes) < MIN_TAKES:
        return {"score": None, "days": len({t.created_at.date() for t in takes}),
                "of": RECENT_DAYS,
                "why": f"{len(takes)} of {MIN_TAKES} takes so far."}
    days = len({t.created_at.date() for t in takes})
    return {"score": max(1, round(10 * days / RECENT_DAYS)), "days": days,
            "of": RECENT_DAYS, "why": ""}


def voice_health(user, app_key):
    """The inverse of strain, said as a score because the blueprint asks for
    one. Never a judgement about the member: a 4 here means the last few days
    were heavy, not that somebody has a bad voice."""
    s = strain(user, app_key)
    if s["level"] == "unmeasured":
        return {"score": None, "level": s["level"], "why": s["why"]}
    score = {"clear": 10, "watch": 6, "strain": 3}[s["level"]]
    return {"score": score, "level": s["level"], "why": s["why"]}


def goal_match(user, app_key):
    """How close recent takes read to the range the member said they are after.

    Returns None until there IS a goal — a goal-match score against no goal is
    the emptiest number this file could produce, and the answer to it is the
    control that sets one rather than a zero.
    """
    row = profile_row(user, app_key)
    goal = row.goal_range if row else ""
    if not goal:
        return {"score": None, "goal": "", "why": "No goal range set yet.",
                "open_in": {"tab": app_key, "target": f"{app_key}:goal"}}
    reads = [t.range_class for t in _recent(user, app_key, days=RECENT_DAYS * 4)
             if t.range_class]
    if len(reads) < MIN_TAKES:
        return {"score": None, "goal": goal, "matched": len(reads),
                "why": f"{len(reads)} of {MIN_TAKES} takes long enough to read a "
                       "range from."}
    hit = sum(1 for r in reads if r == goal)
    return {"score": max(1, round(10 * hit / len(reads))), "goal": goal,
            "matched": hit, "of": len(reads), "why": ""}


def bridge(user, app_key):
    """Auto-Goal Bridge: where they read now, where they said they're going,
    and whether those are the same place. It proposes nothing it cannot
    support — with no goal or no reading it returns the missing half."""
    row = profile_row(user, app_key)
    now = detected(user, app_key)
    goal = row.goal_range if row else ""
    ranges = dict(profile_for_app(app_key)["ranges"])
    if not goal:
        return {"from": now, "to": "", "same": None,
                "why": "Set a goal range and every take gets scored against it."}
    if not now["range"]:
        return {"from": now, "to": goal, "to_label": ranges.get(goal, goal),
                "same": None, "why": now["why"]}
    return {"from": now, "from_label": ranges.get(now["range"], now["range"]),
            "to": goal, "to_label": ranges.get(goal, goal),
            "same": now["range"] == goal,
            "why": ("Your takes already read as your goal — Safe Strengthen work "
                    "from here." if now["range"] == goal else
                    "Bridge work: the drills between the two.")}


_HARD_LABEL = {"performer": "Performer", "stageboss": "Stage Boss"}
_EASY_LABEL = {"starter": "Starter", "builder": "Builder"}


def _bare(label):
    """A dimension's name without its emoji — 'Breath 🫁' reads as 'Breath' inside a
    sentence. The emoji stays on the chart; here it would be decoration."""
    import re
    return re.sub(r"\s*[^\w\s'&/-].*$", "", str(label)).strip() or str(label)


def _join(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1] if items else ""


def strain_rule(prof):
    """The fatigue setting, said as what it DOES.

    The screen used to say only that it "changes when the app eases you off the hard
    settings", which names the mechanism and not the result. A member picking
    between three options needs to know what each one costs them: how many weak
    takes it takes before Performer and Stage Boss are held back. The numbers come
    from THRESHOLD, LOW_AT and WINDOW_HOURS above, so the sentence cannot drift
    from the rule it describes.

    Empty for an instrument the coach cannot read strain from (a drummer has no
    breath score) — the screen hides the control there, as it always has.
    """
    watched = [_bare(prof["scores"][d]) for d in STRAIN_DIMENSIONS if d in prof["scores"]]
    if not watched:
        return {}
    names = _join(watched)
    days = WINDOW_HOURS // 24
    hard = " and ".join(_HARD_LABEL[d] for d in HARD)
    easy = " and ".join(_EASY_LABEL[d] for d in _EASY_LABEL)
    rows = []
    for key, label in InstrumentProfile.SENSITIVITY:
        n = THRESHOLD[key]
        rows.append({
            "key": key, "label": label, "lows_needed": n,
            "result": f"{hard} are held back after {n} low {names} scores in {days} days.",
        })
    return {
        "low_at": LOW_AT, "window_hours": WINDOW_HOURS, "days": days, "dimensions": watched,
        "rows": rows,
        "summary": (f"A low score is {LOW_AT} out of 10 or under on {names}. This setting is how "
                    f"many of them, in the last {days} days, it takes before the coach holds "
                    f"{hard} back and keeps you on {easy} until they roll off."),
        "never": (f"It never blocks {easy}, never changes a score, and no plan lifts it — "
                  "it is a health rule, not a feature."),
    }


# ----------------------------------------------------------------- exports

PUNCHLINE_LOW = 5   # at or under this, the punchlines are what the writer is offered for


def _score_text(take, label):
    r = take.read or {}
    shown = r.get("exact", take.overall)
    return f"{label} take · {shown}/10" if shown is not None else f"{label} take"


def _read_text(take, label):
    """The take as a draft another app can open: the score, the coach's one-line
    verdict, what worked and what to fix. Built here, once, so every destination
    carries the same words and no screen composes a second version."""
    r = take.read or {}
    # No title line here: PostZ, MessageZ and JournalZ each show the title
    # separately and join it to this, so repeating it would print it twice.
    lines = []
    if take.genre or take.style:
        lines.append(" · ".join(x for x in (take.genre, take.style) if x))
    if r.get("verdict"):
        lines += ["", r["verdict"]] if lines else [r["verdict"]]
    if r.get("strengths"):
        lines += ["", "What worked:"] + [f"· {x}" for x in r["strengths"]]
    if r.get("fixes"):
        lines += ["", "Fix this:"] + [f"· {x}" for x in r["fixes"]]
    extras = extras_of(r)
    if extras:
        lines += [""] + [f"{e['label']} {e['value']}/10" + (f" — {e['detail']}" if e["detail"] else "") for e in extras]
        for e in extras:
            if e.get("tips"):
                lines += ["", f"To bring more feeling ({e['label']}):"] + [
                    f"· {x['label']}: {x['what']}" + (f" Why: {x['why']}" if x.get("why") else "")
                    + (f" How: {x['how']}" if x.get("how") else "") for x in e["tips"]]
    mix = mix_tips_of(r)
    if mix:
        lines += ["", "Mix suggestions:"] + [
            f"· {x['what']}" + (f" Why: {x['why']}" if x["why"] else "") + (f" How: {x['how']}" if x["how"] else "")
            for x in mix]
    return "\n".join(lines)[:4000]


# Breath is the one weakness that is trained away from the screen, so its door is
# not a writer: it is a free practice app, and it says so before it is pressed.
BREATH_DOOR = {"key": "breathz", "label": "Train your breath", "tab": "breathz", "target": "breathz-pacer",
               "carry": {}, "cost": None,
               "note": "Free — guided breathing for exactly this. It earns XP for turning up and never "
                       "changes a score; your next take's Breath score is the measure."}


def fixer_door(app_key, dim, *, genre="", style="", price=None):
    """The paid writer for ONE weak lyric dimension, with its price and its
    royalty said before it is pressed. None when no writer covers `dim`."""
    from .sentencez import FIXER_FOR_DIM, FIXERS
    kind = FIXER_FOR_DIM.get(dim)
    if not kind:
        return None
    f = FIXERS[kind]
    return {"key": kind, "label": f"Write better {f['noun']}", "tab": "sentenceconnectz",
            "target": "sentencez-write",
            "carry": {"kind": kind, "genre": genre, "style": style},
            "cost": ({"resource": "promptz", "amount": price["amount"],
                      "free_today": price["free_today"]} if price else None),
            "note": (f"Five {f['noun']} with why each works, ranked by what members rate highest. "
                     "If you use one in a release, battle or deal, K-Oth's royalty applies to the "
                     "part you keep. A failed run is not charged.")}


def fixer_doors(take, *, price=None):
    """{dimension: door} for every lyric dimension this take scored low."""
    out = {}
    for dim, v in (take.scores or {}).items():
        if isinstance(v, int) and v <= PUNCHLINE_LOW:
            d = fixer_door(take.app_key, dim, genre=take.genre, style=take.style, price=price)
            if d:
                out[dim] = d
    hook = (take.read or {}).get("hook")
    if isinstance(hook, (int, float)) and hook <= PUNCHLINE_LOW:
        d = fixer_door(take.app_key, "hook", genre=take.genre, style=take.style, price=price)
        if d:
            out["hook"] = d
    return out


PROMO_NOTE = ("Makes the public share link (free), then writes a post about this score — your words "
              "stay yours: it uses only what the coach said, never an invented number — in a box "
              "you can copy. A failed run is not charged. If you keep it and use it in a release, "
              "battle or deal, K-Oth's royalty applies to the part you keep.")


PROMO_KINDS = {
    "post": {"label": "Write a promo post", "door": "promopost"},
    "caption": {"label": "Write an Instagram caption", "door": "promocaption"},
}


def promo_door(take, *, price=None, kind="post"):
    """The one-press way from a past take to words a member can paste anywhere:
    the share link, plus a Sentence ConnectZ piece (a post, or an Instagram caption)
    built from it. Priced on the control before it is pressed — it is a paid run,
    and the member already spent a credit on the take itself."""
    if take.overall is None or kind not in PROMO_KINDS:
        return None
    return {"key": PROMO_KINDS[kind]["door"], "label": PROMO_KINDS[kind]["label"], "kind": "promo",
            "promo_kind": kind, "tab": take.app_key,
            "target": f"{take.app_key}-promo", "carry": {}, "id": take.pk,
            "cost": ({"resource": "promptz", "amount": price["amount"],
                      "free_today": price["free_today"]} if price else None),
            "note": PROMO_NOTE}


def promo_topic(take, label, url, human=False):
    """The brief the writer is given for a take's promo post — assembled HERE, from
    what the server stored when the coach answered, never from anything a client
    sends (a promo for "10/10" on a take that scored 4 is the card's own failure
    case with copy on top). `url` is the public share page, to be included as is."""
    r = take.read or {}
    shown = r.get("exact", take.overall)
    facts = [f"Instrument: {label}",
             f"Score the AI coach gave this take: {shown}/10"]
    if take.genre or take.style:
        facts.append("Genre / style: " + " · ".join(x for x in (take.genre, take.style) if x))
    if r.get("verdict"):
        facts.append(f"The coach's own verdict: {r['verdict']}")
    for x in (r.get("strengths") or [])[:2]:
        facts.append(f"What worked: {x}")
    facts.append(f"Link to the card (include it exactly once, unchanged): {url}")
    rules = ["Write a post the performer will publish about THIS result, in the first person.",
             "Use only the facts above. Do not invent plays, followers, awards, quotes or any other number.",
             "Name the AI coach as the source of the score; never imply the AI performed or wrote the take."]
    rules.append("Say the performance is human-made, AI-scored." if human else
                 "Do not say whether the performance is human-made.")
    return "\n".join(["Facts:", *[f"- {f}" for f in facts], "", "Rules:", *[f"- {x}" for x in rules]])


def exports_for(take, label, *, price=None):
    """Where a recent take can go next — the one list, with what each costs.

    A take is a score and a read sitting still, and until this list the history
    was a dead end: a number with a date. Each destination carries `carry`, the
    take in the shape that app fills its form from, and `note`, which says what
    pressing it does AND what it costs before it is pressed.

    Honest about what is kept: the recording is only here when the take came from
    a post or a journal entry (`open_in`); a take recorded in the coach was
    scored and not stored, so what travels is the score and the coach's read,
    never audio, and nothing here pretends otherwise.
    """
    title, body = _score_text(take, label), _read_text(take, label)
    out = [
        {"key": "postz", "label": "Draft a post", "tab": "postz", "target": "composer",
         "carry": {"title": title, "description": body}, "cost": None,
         "note": "The score and the coach's read as a draft. PostZ states its price on the Post button; nothing is posted until you press it."},
        {"key": "messagez", "label": "Message it", "tab": "messagez", "target": "messagez-compose",
         "carry": {"title": title, "description": body}, "cost": None,
         "note": "Opens a message with the read in it. Free to draft; a first message to someone costs Energy, stated in MessageZ before you send."},
        {"key": "journalz", "label": "Add to journal", "tab": "journalz", "target": "journalz-composer",
         "carry": {"title": title, "description": body}, "cost": None,
         "note": "Today's entry, private until you share it."},
    ]
    # First among the doors that go OUT of the app: the member already paid for
    # this session, and a score they are proud of is the cheapest promotion this
    # platform has. The link and card say only what the coach said.
    out.insert(0, {"key": "share", "label": "Share this score", "kind": "share", "tab": take.app_key,
                   "target": "", "carry": {}, "cost": None,
                   "note": ("A public link and card with the score and the coach's own one-line verdict, "
                            "made from what the coach actually said. Free — and anyone who joins from it "
                            "earns you the referral reward.")})
    # The promo doors stay second (and third) after Share — that order is pinned and the screen relies
    # on it — and "Post it" follows them, so the free way to put a take on PostZ sits right beside
    # the paid writer's.
    at = 1
    for kind in PROMO_KINDS:
        promo = promo_door(take, price=price, kind=kind)
        if promo:
            out.insert(at, promo)
            at += 1
    out.insert(at, post_take_door(take))
    breath = (take.scores or {}).get("breath")
    if isinstance(breath, int) and breath <= PUNCHLINE_LOW:
        out.append(BREATH_DOOR)
    if take.weakest:
        out.append({"key": "drills", "label": "Practise the weak spot", "tab": take.app_key,
                    "target": f"{take.app_key}-drills", "carry": {}, "cost": None,
                    "note": "Free — the drills for what scored lowest."})
    for dim, door in fixer_doors(take, price=price).items():
        out.append(door)
    if take.source == "post" and take.ref.startswith("post:"):
        try:
            pid = int(take.ref.split(":", 1)[1])
        except ValueError:
            pid = None
        if pid:
            out.append({"key": "battlez", "label": "Enter it in a battle", "tab": "battlez",
                        "target": "battlez:main", "carry": {"kind": "post", "post_id": pid},
                        "cost": None, "note": "Its post goes in as the entry; BattleZ states any stake before you confirm."})
    if take.overall is not None:
        from . import takelessons
        read = take.read or {}
        exact = read.get("exact") if isinstance(read.get("exact"), (int, float)) else take.overall
        dim = profile_for_app(take.app_key)["scores"].get(take.weakest or "", "")
        out.append(takelessons.collab_door(take.app_key, exact, genre=take.genre, weakest_label=dim,
                                           take_id=take.pk))
    if take.share_token:
        out.append({"key": "viewz", "label": "See how its link is doing", "tab": "viewz", "target": "viewz-links",
                    "carry": {}, "cost": None,
                    "note": "Free — how often the link was opened. Opens are counted; who opened a link is not recorded."})
    out.append({"key": "download", "label": "Download this take", "kind": "download", "tab": take.app_key,
                "target": "", "id": take.pk, "carry": {}, "cost": None,
                "note": "Free — the score, every dimension and the coach's read as a file "
                        "(text or JSON). The recording is its own download when it was kept."})
    return out


def post_take_door(take):
    """"Post it": the take as a PostZ post that plays, with its score and the coach's feedback.

    The note says before the press whether the recording goes with it — a take is scored and not
    stored unless the member ticked Keep this take, so most are not playable, and a door that
    implied otherwise would be a promise the post then breaks. Free; it counts as one of the
    day's submissions, which the panel states with the real numbers."""
    kept = bool(take.upload_id) and not (take.upload and take.upload.missing_since)
    return {"key": "post_take", "label": "Post it — score & feedback", "kind": "post_take",
            "tab": "postz", "target": "", "id": take.pk, "carry": {}, "cost": None,
            "note": ("A PostZ post with the score and the coach's feedback" +
                     (", and the recording — so anyone with the link can play it. " if kept else
                      ". This take wasn't kept, so there is no recording to play; tick Keep this take "
                      "before you record next time to make a take playable by link. ") +
                     "Free. You choose what goes in, and it counts as one of today's submissions.")}


def share_payload(take):
    """The take as the coach gave it, in the shape a share row keeps — built from
    what the SERVER stored when it answered, never from anything a client sends.
    A share card that took its number from a request is "10/10 from the AI coach"
    for a take that scored 4, with our name on it."""
    r = take.read or {}
    from .challengez import challenge_tag
    out = {"score": take.overall, "scores": take.scores or {}, "verdict": r.get("verdict", ""),
           "strengths": r.get("strengths", []), "fixes": r.get("fixes", []),
           "practice": r.get("practice", []), "genre": take.genre, "style": take.style}
    for key, field in (("exact", "score_exact"), ("hook", "hook_score"), ("feelz", "feelz_score")):
        if key in r:
            out[field] = r[key]
    for k in ("hook_why", "feelz_why", "feelz_emotion", "now", "goal", "style_fit", "range_profile",
              "next_drill", "song_why", "song_score"):
        if r.get(k) not in (None, ""):
            out[k] = r[k]
    # HookZ, FeelZ and what / why / how, already cleaned by the one cleaner — what a card or a post
    # shows beside the score. A share does not recompute them and nothing a client sends reaches them.
    ex, mix = extras_of(r), mix_tips_of(r)
    if ex:
        out["extras"] = ex
    if mix:
        out["mix_tips"] = mix
    # The week's challenge, when THIS take answers it — judged by when it was made,
    # not when it was shared, so a take from Tuesday shared on Friday still counts.
    tag = challenge_tag(take.app_key, take.genre, take.difficulty, take.created_at)
    if tag:
        out["challenge"] = tag
    return out


def share_take(take):
    """The public share token for a take, minted once and then reused. "" when
    there is no score to share (a take with nothing scored has no card)."""
    from .models import ScoreShare, mint_score_share
    row = ScoreShare.objects.filter(token=take.share_token).first() if take.share_token else None
    if row:
        # A link minted before HookZ / FeelZ / what-why-how existed is filled in, never replaced: only
        # keys it does not have are added, so a declaration or a recap already on it is untouched.
        fresh = share_payload(take)
        have = row.payload or {}
        add = {k: v for k, v in fresh.items() if k not in have}
        if add:
            row.payload = {**have, **add}
            row.save(update_fields=["payload"])
        return take.share_token
    token = mint_score_share(take.app_key, share_payload(take), user=take.user, genre=take.genre)
    if token:
        TakeScore.objects.filter(pk=take.pk).update(share_token=token)
        take.share_token = token
    return token


def personal_best(user, app_key):
    """The member's highest overall on this instrument, and how many takes there are.

    A personal best is the most shareable thing a score can be that is not a high
    score: it is about THEM, it needs no comparison with anybody, and a beginner can
    have one on their third take. It is only claimed once there is something to be
    best against (three takes), and only for the take that first tops the rest."""
    from django.db.models import Count, Max
    rated = TakeScore.objects.filter(user=user, app_key=app_key, overall__isnull=False)
    agg = rated.aggregate(best=Max("overall"), n=Count("id"))
    # The take that FIRST reached the best, found once here. take_row used to ask "was there an
    # earlier take with this score?" per row, which is one query per take for every take that
    # ties the best — and members tie their best often, on a list that can show 200.
    first = (rated.filter(overall=agg["best"]).order_by("created_at", "id").values_list("pk", flat=True).first()
             if agg["best"] is not None else None)
    return agg["best"], agg["n"], first


def _lessons_of(take, read, ctx):
    """The teach / learn call-to-action for a take, from the number the member was SHOWN
    (the exact score, else the overall). Only where a context was built — the history list
    builds one for the whole list, so forty low takes cost one teachers query."""
    if ctx is None:
        return None
    from . import takelessons
    score = read.get("exact")
    score = score if isinstance(score, (int, float)) else take.overall
    try:
        dim = profile_for_app(take.app_key)["scores"].get(take.weakest or "", "")
        return takelessons.lessons_for(score, ctx, weakest_label=dim)
    except Exception:                                        # pragma: no cover
        return None


HOOK_LABEL, FEELZ_LABEL = "HookZ 🪝", "FeelZ 💗"
EXTRAS_NOTE = ("HookZ is the hook and FeelZ is how much of the feeling comes through. Each counts in your "
               "overall like any other dimension — the strongest parts weigh most, so a take that moves people "
               "is not held down by one rough spot — and only when the coach found one to judge; a missing "
               "one is absent, never a 0.")


def _cause_for_row(r):
    from .vocalcoach import FEELZ_CAUSES, _feelz_cause
    c = _feelz_cause(r.get("feelz_cause"), r.get("feelz"))
    return {"key": c, "label": FEELZ_CAUSES[c]} if c else None


def _tips_for_row(r):
    """Tips as [{kind, label, tip}], from this take's read — tolerant of the plain-string shape an
    earlier build stored, and empty unless the FeelZ really is low."""
    from .vocalcoach import _feelz_tips
    return _feelz_tips(r.get("feelz_tips"), r.get("feelz"), r.get("feelz_cause") or "")


def mix_tips_of(r):
    from .vocalcoach import _mix_tips
    r = r or {}
    return [] if r.get("feelz_cause") == "performance" else _mix_tips(r.get("mix_tips"))


def extras_of(read):
    """HookZ and FeelZ as labelled rows with their reasons — the server's words, absent when the coach
    found nothing to judge (a warm-up has no hook), never a 0."""
    r = read or {}
    out = []
    if isinstance(r.get("hook"), (int, float)):
        out.append({"key": "hook", "label": HOOK_LABEL, "value": r["hook"], "detail": r.get("hook_why", ""),
                    "counted": r.get("hook_counted")})
    if isinstance(r.get("feelz"), (int, float)):
        emo = r.get("feelz_emotion", "")
        why = r.get("feelz_why", "")
        out.append({"key": "feelz", "label": FEELZ_LABEL, "value": r["feelz"],
                    "detail": " — ".join(x for x in ((f"Felt: {emo}" if emo else ""), why) if x),
                    "counted": r.get("feelz_counted"), "emotion": emo,
                    "tips": _tips_for_row(r), "cause": _cause_for_row(r)})
    return out


def take_row(take, label, price=None, best=None, lessons_ctx=None):
    r = take.read or {}
    top, n, first = best if best else (None, 0, None)
    is_pb = bool(top is not None and n >= MIN_TAKES and take.overall == top and take.pk == first)
    from .logz_outcomes import file_of
    return {"pb": is_pb, "file": file_of(take), "share_url": f"/s/{take.share_token}" if take.share_token else "",
            "id": take.pk, "overall": take.overall, "exact": r.get("exact"), "scores": take.scores,
            "weakest": take.weakest, "difficulty": take.difficulty, "genre": take.genre,
            "style": take.style, "target": take.target, "range_class": take.range_class,
            "low": take.low_note, "high": take.high_note, "at": take.created_at.isoformat(),
            "read": r, "extras": extras_of(r), "extras_note": EXTRAS_NOTE, "mix_tips": mix_tips_of(r),
            "open_in": ({"tab": "postz", "target": take.ref} if take.source == "post"
                        else {"tab": "journalz", "target": "journalz-entries"}
                        if take.source == "journal" else None),
            "lessons": _lessons_of(take, r, lessons_ctx),
            "exports": exports_for(take, label, price=price)}


RECAP_DAYS = 30


def recap(user, app_key):
    """A month of takes, as the member would tell it: how many, the best, what climbed,
    what is strongest, how many days they showed up.

    Built from the stored takes alone — the same ones the history shows — and absent
    (None) below three takes: a "month" of one take is not a recap, it is a score.
    Spotify's Wrapped works because it is the person's own data in a shareable shape;
    this is that, and it only ever says what is in the data."""
    takes = _recent(user, app_key, days=RECAP_DAYS, limit=500)
    if len(takes) < MIN_TAKES:
        return None
    dims = scores_for(app_key, lyrics=True)
    overalls = [t.overall for t in takes if t.overall is not None]
    sums = {}
    for t in takes:
        for k, v in (t.scores or {}).items():
            if k in dims and isinstance(v, int):
                sums.setdefault(k, []).append(v)
    strongest = None
    if sums:
        k = max(sums, key=lambda x: sum(sums[x]) / len(sums[x]))
        strongest = {"key": k, "label": dims[k], "average": round(sum(sums[k]) / len(sums[k]), 1)}
    climb = None
    for r in trend(user, app_key, days=RECAP_DAYS).get("rows", []):
        if r["change"] > 0 and r["was_n"] >= 2 and r["now_n"] >= 2 and (climb is None or r["change"] > climb["change"]):
            climb = {"key": r["key"], "label": r["label"], "was": r["was"], "now": r["now"], "change": r["change"]}
    exacts = [t.read.get("exact") for t in takes if isinstance((t.read or {}).get("exact"), (int, float))]
    return {"days": RECAP_DAYS, "takes": len(takes), "best": max(overalls) if overalls else None,
            "best_exact": max(exacts) if exacts else None,
            "days_shown_up": len({t.created_at.date() for t in takes}),
            "strongest": strongest, "climb": climb}


WIN_AT = 0.5          # a dimension up by this much, on enough takes, is worth saying so
PROBLEM_AT = 5.5      # average at or under this across the window is a problem area
STRENGTH_AT = 6.5     # average at or over this is a strength worth saying so


def coaching(user, app_key, price=None):
    """What to celebrate, what to watch, and what to work on — in one place.

    Wins and alerts come from the same two-halves trend the history already
    shows, with its same refusal to draw a line through two dots; a problem area
    is a dimension whose average over the window is low, and each one carries the
    free way to work on it (the drills) and, where a writer exists, the paid one
    with its price and its royalty stated up front. The sentences are the
    server's: a screen that worded its own congratulations would be one more
    place the numbers could be rounded kindly.
    """
    prof = profile_for_app(app_key)
    tr = trend(user, app_key)
    wins, alerts = [], []
    for r in tr.get("rows", []):
        if r["was_n"] < 2 or r["now_n"] < 2:
            continue
        move = f"{r['label']} {r['was']} → {r['now']}"
        if r["change"] >= WIN_AT:
            wins.append({**r, "text": f"{move}. That is the work showing — keep going."})
        elif r["change"] <= -WIN_AT:
            alerts.append({**r, "text": f"{move}. Down over the same stretch — a bad week or something that "
                                        "changed? The drill below is the quick way back."})
    takes = _recent(user, app_key, days=RECENT_DAYS)
    dims = scores_for(app_key, lyrics=True)
    sums = {}
    for t in takes:
        for k, v in (t.scores or {}).items():
            if k in dims and isinstance(v, int):
                sums.setdefault(k, []).append(v)
        hook = (t.read or {}).get("hook")
        if isinstance(hook, (int, float)):
            sums.setdefault("hook", []).append(hook)
    last = takes[0] if takes else None
    problems = []
    for k, vals in sums.items():
        if len(vals) < MIN_TAKES:
            continue
        avg = sum(vals) / len(vals)
        if avg > PROBLEM_AT:
            continue
        helps = [{"key": "drills", "label": "Drill it", "tab": app_key, "target": f"{app_key}-drills",
                  "carry": {}, "cost": None, "note": "Free — the drills for this."}]
        if k == "breath":
            helps.insert(0, BREATH_DOOR)
        fix = fixer_door(app_key, k, genre=getattr(last, "genre", ""), style=getattr(last, "style", ""), price=price)
        if fix:
            helps.append(fix)
        problems.append({"key": k, "label": dims.get(k, "HookZ 🪝" if k == "hook" else k),
                         "average": round(avg, 1), "takes": len(vals), "help": helps})
    problems.sort(key=lambda p: p["average"])
    # What they are good at, said as plainly as what they are not. A screen that
    # only ever names the weak spot reads as a telling-off; "you're strong at
    # this" is as true, as measured, and the half people stay for.
    strengths = []
    for k, vals in sums.items():
        if len(vals) >= MIN_TAKES and sum(vals) / len(vals) >= STRENGTH_AT:
            strengths.append({"key": k, "label": dims.get(k, "HookZ 🪝" if k == "hook" else k),
                              "average": round(sum(vals) / len(vals), 1), "takes": len(vals)})
    strengths.sort(key=lambda x: -x["average"])
    agreed = dict(CoachAgreement.objects.filter(user=user, app_key=app_key).values_list("area", "agree"))
    for row in (*problems, *strengths):
        row["agreed"] = agreed.get(row["key"])
    return {"wins": wins, "alerts": alerts, "problems": problems[:4], "strengths": strengths[:3],
            "from_last_take": ((last.read or {}).get("fixes") or [])[:3] if last else [],
            "worked_last_take": ((last.read or {}).get("strengths") or [])[:3] if last else []}


# ------------------------------------------------------------ downloads
#
# A member's takes are theirs: the score, the coach's read and, where it was kept, the
# recording. These build the FILE — one take as a readable report, or the whole history
# as a spreadsheet — from what the server stored, for that member's own takes only. The
# lyrics the coach transcribed are never in them because they are never stored.
# The screen turns the text into a download itself, so no download link needs a login
# header the browser cannot send.

def _labels(app_key):
    return dict(scores_for(app_key, lyrics=True, mix=True))


def take_report_text(take, label, labels=None):
    """One take as a plain-text report: when, the score, every dimension with its
    name, then what the coach said. Absent numbers are said to be absent."""
    labels = labels or _labels(take.app_key)
    r = take.read or {}
    shown = r.get("exact", take.overall)
    lines = [f"{label} take — {timezone.localtime(take.created_at):%Y-%m-%d %H:%M}",
             f"Overall: {shown}/10" if shown is not None else "Overall: not scored"]
    ctx = " · ".join(x for x in (take.genre, take.style, take.difficulty, take.range_class) if x)
    if ctx:
        lines.append(ctx)
    if take.scores:
        lines += ["", "Scores:"] + [f"  {labels.get(k, k)}: {v}/10" for k, v in take.scores.items()]
    for key, name in (("hook", "HookZ"), ("feelz", "FeelZ")):
        if isinstance(r.get(key), (int, float)):
            lines.append(f"  {name}: {r[key]}/10")
    if r.get("verdict"):
        lines += ["", "Verdict:", f"  {r['verdict']}"]
    for key, head in (("strengths", "What worked"), ("fixes", "Fix this")):
        if r.get(key):
            lines += ["", f"{head}:"] + [f"  · {x}" for x in r[key]]
    if r.get("practice"):
        lines += ["", "Practise this:"] + [
            "  · " + " — ".join(x for x in (p.get("what"), p.get("why"), p.get("how")) if x)
            for p in r["practice"] if isinstance(p, dict)]
    if not r:
        lines += ["", "(This take was scored before the coach's read was kept, so only the score is here.)"]
    # Gear advice is a separate PromptZ spend (coach_upgrades.py) that stores
    # its result on this same take — it has to leave with the take's own
    # export, or a member who paid for it can save everything about this take
    # except the one thing they paid extra for.
    upgrades = (take.upgrades or {}).get("items")
    if upgrades:
        lines += ["", "Gear and settings advice:"]
        for it in upgrades:
            lines.append(f"  [{it.get('category', 'other')}] {it.get('heading', '')}")
            if it.get("advice"):
                lines.append(f"    {it['advice']}")
            for s in it.get("settings") or []:
                lines.append(f"    · {s}")
            for p in it.get("products") or []:
                lines.append(f"    Product: {p.get('name', '')}")
    lines += ["", "Scored by the AI coach on Music ConnectZ. The score is the coach's reading of one take, "
                  "not a measure of you."]
    return "\n".join(lines)


def history_rows(user, app_key):
    """Every take, oldest first, as flat dicts — the spreadsheet's rows."""
    labels = _labels(app_key)
    dims = list(labels)
    rows = []
    for t in TakeScore.objects.filter(user=user, app_key=app_key).order_by("created_at"):
        r = t.read or {}
        row = {"date": timezone.localtime(t.created_at).strftime("%Y-%m-%d %H:%M"),
               "overall": r.get("exact", t.overall), "genre": t.genre, "style": t.style,
               "difficulty": t.difficulty, "register": t.range_class}
        for k in dims:
            v = (t.scores or {}).get(k)
            row[labels[k]] = v if isinstance(v, int) else ""
        row["hook"] = r.get("hook", "")
        row["feelz"] = r.get("feelz", "")
        row["verdict"] = r.get("verdict", "")
        row["worked"] = " | ".join(r.get("strengths", []) or [])
        row["fix"] = " | ".join(r.get("fixes", []) or [])
        rows.append(row)
    return rows


def _csv_safe(v):
    """A spreadsheet runs a cell that starts with = + - @ as a formula. A verdict is
    model text, so a leading one is made a literal instead of an instruction."""
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") and not v.lstrip("+-").replace(".", "", 1).isdigit() else v


def history_csv(rows):
    import csv
    import io
    if not rows:
        return ""
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(rows[0]))
    w.writeheader()
    for r in rows:
        w.writerow({k: _csv_safe(v) for k, v in r.items()})
    return out.getvalue()


RECENT_TAKES = 10          # the screen's first page
ALL_TAKES_CAP = 200        # "show all" — bounded, because every row carries its doors


def progress(user, app_key, limit=RECENT_TAKES):
    """Everything the history knows, in one call. It renders as a screen.

    `limit` is how many past takes are listed (newest first). The screen asks for
    the first ten and offers "show all N" — it used to stop at ten with no way to
    reach the rest, so a member with twenty-three takes saw ten and no sign of the
    other thirteen."""
    token = _memo.set({})
    try:
        return _progress(user, app_key, limit)
    finally:
        _memo.reset(token)


def _progress(user, app_key, limit):
    prof = profile_for_app(app_key)
    row = profile_row(user, app_key)
    rule = strain_rule(prof)
    takes = TakeScore.objects.filter(user=user, app_key=app_key).select_related("upload")[:limit]
    from .crosspost import coach_price
    price = coach_price(user)          # read once, not once per row
    best = personal_best(user, app_key)
    from . import takelessons
    lessons_ctx = takelessons.context(user, app_key)
    return {
        "app_key": app_key, "label": prof["label"],
        "dimensions": [{"key": k, "label": v} for k, v in prof["scores"].items()],
        "declared": {
            "confirmed_range": row.confirmed_range if row else "",
            "goal_range": row.goal_range if row else "",
            "fatigue_sensitivity": (row.fatigue_sensitivity if row else "") or DEFAULT_SENSITIVITY,
            "bpm_low": row.bpm_low if row else None,
            "bpm_high": row.bpm_high if row else None,
        },
        "ranges": [{"key": k, "label": l} for k, l in prof["ranges"]],
        # `result` is new: what picking each one DOES, so the screen can say so
        # beside the choice. `key` and `label` are unchanged for older clients.
        "sensitivities": ([{"key": r["key"], "label": r["label"], "lows_needed": r["lows_needed"],
                            "result": r["result"]} for r in rule["rows"]]
                          if rule else [{"key": k, "label": l} for k, l in InstrumentProfile.SENSITIVITY]),
        "strain_rule": ({k: v for k, v in rule.items() if k != "rows"} if rule else {}),
        "detected": detected(user, app_key),
        "bridge": bridge(user, app_key),
        "strain": strain(user, app_key),
        "weakest": weakest(user, app_key),
        "trend": trend(user, app_key),
        # The three the caveat says a single clip cannot show. They are here
        # rather than on the take for exactly that reason, and each says why
        # when it has nothing yet instead of printing a number it cannot back.
        "history_scores": {
            "consistency": consistency(user, app_key),
            "voice_health": voice_health(user, app_key),
            "goal_match": goal_match(user, app_key),
        },
        "takes": [take_row(t, prof["label"], price, best, lessons_ctx) for t in takes],
        # The number a "beat it tomorrow" nudge points at: the member's best overall on this
        # coach across ALL their takes, not just the rows listed. None until there is one.
        "personal_best": best[0] if best else None,
        "coaching": coaching(user, app_key, price),
        "recap": recap(user, app_key),
        "total_takes": TakeScore.objects.filter(user=user, app_key=app_key).count(),
    }


# ----------------------------------------------------------------- the API

from rest_framework import status                                  # noqa: E402
from rest_framework.permissions import IsAuthenticated              # noqa: E402
from rest_framework.response import Response                        # noqa: E402
from rest_framework.views import APIView                            # noqa: E402


class ProgressView(APIView):
    """GET /api/<key>/progress/ — the history, and what it concludes.

    `app_key` is bound per instrument in `music_connectz/urls.py`, the same way
    the coach and the trial are, so a new instrument gets this for free rather
    than needing a list edited in a second place.
    """
    permission_classes = [IsAuthenticated]
    app_key = "singz"

    def get(self, request):
        limit = ALL_TAKES_CAP if request.query_params.get("takes") == "all" else RECENT_TAKES
        return Response(progress(request.user, self.app_key, limit=limit))


class ShareTakeView(APIView):
    """POST /api/<key>/take/<id>/share/ — the public link for one of YOUR past takes.

    Idempotent: the same take gives the same link. The card is read off what the
    server stored when the coach answered; nothing in the request can change it."""
    permission_classes = [IsAuthenticated]
    app_key = "singz"

    def post(self, request, pk):
        take = TakeScore.objects.filter(pk=pk, user=request.user, app_key=self.app_key).first()
        if not take:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        token = share_take(take)
        if not token:
            return Response({"detail": "That take has no score to share."}, status=status.HTTP_409_CONFLICT)
        return Response({"share_url": f"/s/{token}", "score": take.overall,
                         "exact": (take.read or {}).get("exact")})


class TakePromoView(APIView):
    """/api/<key>/take/<id>/promo/ — a promo post for one of YOUR past takes.

    GET says what it costs and whether it can run, before anything is spent. POST
    mints the share link (free, idempotent), writes the post through Sentence
    ConnectZ's own writer — so the price, the daily allowance, "a failed run is
    not charged" and the saved piece are exactly the writer's — and answers the
    text with the link in it, for a box with a Copy button. Whether the card says
    human-made is the member's own declaration on that share, never ours to add."""
    permission_classes = [IsAuthenticated]
    app_key = "singz"

    def _take(self, request, pk):
        return TakeScore.objects.filter(pk=pk, user=request.user, app_key=self.app_key).first()

    def get(self, request, pk):
        take = self._take(request, pk)
        if not take or take.overall is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        from .crosspost import coach_price
        price = coach_price(request.user)
        return Response({"cost": {"resource": "promptz", "amount": price["amount"],
                                  "free_today": price["free_today"]}, "note": PROMO_NOTE,
                         "share_url": f"/s/{take.share_token}" if take.share_token else ""})

    def post(self, request, pk):
        from django.conf import settings
        from .models import ScoreShare
        from .sentencez import write_piece
        take = self._take(request, pk)
        if not take:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        token = share_take(take)
        if not token:
            return Response({"detail": "That take has no score to promote."}, status=status.HTTP_409_CONFLICT)
        row = ScoreShare.objects.filter(token=token).first()
        human = bool((row.payload or {}).get("human")) if row else False
        base = (getattr(settings, "FRONTEND_URL", "") or "https://musicconnectz.net").rstrip("/")
        url = f"{base}/s/{token}"
        label = profile_for_app(self.app_key)["label"]
        kind = str((request.data or {}).get("kind") or "post")
        if kind not in PROMO_KINDS:
            kind = "post"
        from .sentencez import clean_hashtags
        resp = write_piece(request.user, kind, promo_topic(take, label, url, human),
                           hashtags=clean_hashtags((request.data or {}).get("hashtags")),
                           genre=take.genre or "",
                           spend_note=f"{'Promo post' if kind == 'post' else 'Instagram caption'} — {label} take",
                           extra_inputs={"promo_take": take.pk})
        if resp.status_code == status.HTTP_201_CREATED:
            resp.data = {**resp.data, "share_url": f"/s/{token}", "link": url}
        return resp


class TakePostView(APIView):
    """/api/<key>/take/<id>/post/ — one of YOUR takes as a PostZ post.

    GET says what is available and what it counts against, before anything is made. POST makes
    the post through `postz.create_post` — the same daily cap, sanitising and zodiac hooks as the
    composer, never a second path — from what the SERVER stored: the score and the coach's read
    come from the share row by token (so a client cannot post a number the coach did not give),
    and the recording is the member's own kept upload, by stable address. The member chooses
    score, feedback and recording separately; nothing is included they did not tick.

    When BOTH score and feedback go, the post carries the coach's own read card (`coach_token`),
    which is the labelled, structured version; either alone goes as plain text, because the card
    cannot show half of itself."""
    permission_classes = [IsAuthenticated]
    app_key = "singz"

    def _take(self, request, pk):
        return (TakeScore.objects.filter(pk=pk, user=request.user, app_key=self.app_key)
                .select_related("upload").first())

    def get(self, request, pk):
        from .logz_outcomes import file_of
        from .models import submission_cap_for, submissions_used_today
        take = self._take(request, pk)
        if not take or take.overall is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        label = profile_for_app(self.app_key)["label"]
        f = file_of(take, request)
        return Response({
            "title": _score_text(take, label), "feedback": _read_text(take, label),
            "file": f, "cost": None,
            "submissions": {"used": submissions_used_today(request.user), "cap": submission_cap_for(request.user)},
            "note": post_take_door(take)["note"],
        })

    def post(self, request, pk):
        from django.conf import settings
        from .postz import create_post
        take = self._take(request, pk)
        if not take or take.overall is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        d = request.data or {}
        on = lambda k, default=True: str(d.get(k, default)).strip().lower() in ("1", "true", "yes", "on")
        inc_score, inc_feedback, inc_recording = on("score"), on("feedback"), on("recording")
        label = profile_for_app(self.app_key)["label"]
        vis = str(d.get("visibility") or "public").lower()
        if vis not in ("public", "restricted"):
            vis = "public"
        payload = {"title": _score_text(take, label) if inc_score else f"{label} take",
                   "description": _read_text(take, label) if inc_feedback else
                   " · ".join(x for x in (take.genre, take.style) if x),
                   "genre": take.genre or "", "visibility": vis}
        carded = inc_score and inc_feedback
        if carded:
            token = share_take(take)
            if token:
                payload["coach_token"] = token
                payload["score_visibility"] = "" if vis == "public" else "members"   # "" is the widest setting: public
        recorded = False
        if inc_recording:
            from .logz_outcomes import file_of
            f = file_of(take, request)
            if f.get("kept") and f.get("url"):
                payload["media_url"] = f["url"]
                payload["media_type"] = "video" if str(f.get("content_type", "")).startswith("video") else "audio"
                recorded = True
        post, _info, err = create_post(request.user, payload)
        if err:
            body, code = err
            return Response(body, status=code)
        base = (getattr(settings, "FRONTEND_URL", "") or "https://musicconnectz.net").rstrip("/")
        return Response({"post_id": post.pk, "url": f"/p/{post.pk}", "link": f"{base}/p/{post.pk}",
                         "included": {"score": inc_score, "feedback": inc_feedback, "card": carded and bool(post.score),
                                      "recording": recorded},
                         "playable": recorded}, status=status.HTTP_201_CREATED)


class TakeDownloadView(APIView):
    """GET /api/<key>/take/<id>/download/?format=txt|json — one of YOUR takes as a file's contents."""
    permission_classes = [IsAuthenticated]
    app_key = "singz"

    def get(self, request, pk):
        take = TakeScore.objects.filter(pk=pk, user=request.user, app_key=self.app_key).first()
        if not take:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        label = profile_for_app(self.app_key)["label"]
        stamp = timezone.localtime(take.created_at).strftime("%Y%m%d-%H%M")
        if request.query_params.get("format") == "json":
            import json
            row = take_row(take, label)
            body = {k: row[k] for k in ("id", "at", "overall", "exact", "scores", "genre", "style", "difficulty",
                                        "range_class", "read")}
            # Paid for separately (coach_upgrades.py) but stored on this take —
            # a member's own export of a take has to include everything they
            # bought for it, not just the score.
            if (take.upgrades or {}).get("items"):
                body["upgrades"] = {"summary": take.upgrades.get("summary", ""), "items": take.upgrades["items"]}
            return Response({"filename": f"{self.app_key}-take-{stamp}.json", "content_type": "application/json",
                             "text": json.dumps(body, indent=2, ensure_ascii=False)})
        return Response({"filename": f"{self.app_key}-take-{stamp}.txt", "content_type": "text/plain",
                         "text": take_report_text(take, label)})


class TakesExportView(APIView):
    """GET /api/<key>/takes/export/?format=csv|json — your WHOLE history in this app, as a file's contents."""
    permission_classes = [IsAuthenticated]
    app_key = "singz"

    def get(self, request):
        rows = history_rows(request.user, self.app_key)
        if not rows:
            return Response({"detail": "No takes to export yet."}, status=status.HTTP_404_NOT_FOUND)
        today = timezone.localdate().isoformat()
        if request.query_params.get("format") == "json":
            import json
            return Response({"filename": f"{self.app_key}-takes-{today}.json", "content_type": "application/json",
                             "count": len(rows), "text": json.dumps(rows, indent=2, ensure_ascii=False)})
        return Response({"filename": f"{self.app_key}-takes-{today}.csv", "content_type": "text/csv",
                         "count": len(rows), "text": history_csv(rows)})


class ShareWinView(APIView):
    """POST /api/<key>/win/<dimension>/share/ — a card for a measured improvement.

    A good score is the obvious thing to show people; a climb from a bad one is the
    better story, and the one a beginner can tell. The numbers come from the same
    trend the coaching board shows (computed here, from the stored takes — nothing in
    the request), so nobody can mint "Flow 2 → 9" for a dimension that did not move."""
    permission_classes = [IsAuthenticated]
    app_key = "singz"

    def post(self, request, dim):
        from .models import ScoreShare
        import secrets
        win = next((w for w in coaching(request.user, self.app_key).get("wins", []) if w["key"] == dim), None)
        if not win:
            return Response({"detail": "That one hasn't moved enough yet to show."},
                            status=status.HTTP_409_CONFLICT)
        # One card per win per day: pressing share twice is the same card.
        for row in ScoreShare.objects.filter(user=request.user, app_key=self.app_key,
                                             created_at__gte=timezone.now() - timedelta(days=1))[:30]:
            p = (row.payload or {}).get("progress") or {}
            if p.get("key") == dim and p.get("now") == win["now"]:
                return Response({"share_url": f"/s/{row.token}"})
        progress = {"key": dim, "label": win["label"], "was": win["was"], "now": win["now"],
                    "days": RECENT_DAYS}
        row = ScoreShare.objects.create(
            token=secrets.token_urlsafe(12)[:16], app_key=self.app_key,
            score=max(1, min(10, int(round(win["now"])))),
            verdict=f"{win['label']} went from {win['was']} to {win['now']} in {RECENT_DAYS} days.",
            genre="", user=request.user,
            payload={"progress": progress, "score_exact": win["now"]})
        return Response({"share_url": f"/s/{row.token}"})


class ShareRecapView(APIView):
    """POST /api/<key>/recap/share/ — a card for the member's month.

    Minted from the stored takes (never from the request), once per day: pressing it
    twice is the same card. Needs three takes in the window — below that there is no
    month to show."""
    permission_classes = [IsAuthenticated]
    app_key = "singz"

    def post(self, request):
        from .models import ScoreShare
        import secrets
        r = recap(request.user, self.app_key)
        if not r or r["best"] is None:
            return Response({"detail": "A month needs at least three scored takes to show."},
                            status=status.HTTP_409_CONFLICT)
        today = timezone.localdate().isoformat()
        for row in ScoreShare.objects.filter(user=request.user, app_key=self.app_key,
                                             created_at__gte=timezone.now() - timedelta(days=1))[:30]:
            if ((row.payload or {}).get("recap") or {}).get("on") == today:
                return Response({"share_url": f"/s/{row.token}"})
        bits = [f"{r['takes']} takes in {r['days']} days", f"best {r['best_exact'] or r['best']}"]
        if r["climb"]:
            bits.append(f"{r['climb']['label']} {r['climb']['was']} → {r['climb']['now']}")
        if r["strongest"]:
            bits.append(f"strongest: {r['strongest']['label']}")
        row = ScoreShare.objects.create(
            token=secrets.token_urlsafe(12)[:16], app_key=self.app_key, score=r["best"],
            verdict=". ".join(bits) + ".", genre="", user=request.user,
            payload={"recap": {**r, "on": today},
                     **({"score_exact": r["best_exact"]} if r["best_exact"] else {})})
        return Response({"share_url": f"/s/{row.token}"})


class AgreeView(APIView):
    """POST /api/<key>/agree/ {area, agree} — "yes, that is what to work on" /
    "no, that's wrong". The member's own answer about one area, replacing the last."""
    permission_classes = [IsAuthenticated]
    app_key = "singz"

    def post(self, request):
        d = request.data or {}
        area = str(d.get("area", "")).strip()
        valid = set(scores_for(self.app_key, lyrics=True)) | {"hook"}
        if area not in valid or not isinstance(d.get("agree"), bool):
            return Response({"detail": "Say which area, and yes or no."}, status=status.HTTP_400_BAD_REQUEST)
        CoachAgreement.objects.update_or_create(
            user=request.user, app_key=self.app_key, area=area, defaults={"agree": d["agree"]})
        return Response({"area": area, "agree": d["agree"]})


class GameProfileView(APIView):
    """GET / PATCH /api/<key>/profile/ — the blueprint's per-app game profile.

    The endpoint `GameProfilePanel.jsx` has been calling since it was written.
    It 404'd, a bare `.catch(() => {})` swallowed it, and both the RapZ and
    SingZ panels silently rendered nothing — a whole screen that looked like a
    feature nobody had built, when the data was all there and only the door was
    missing.
    """
    permission_classes = [IsAuthenticated]
    app_key = "singz"

    def get(self, request):
        return Response(game_profile(request.user, self.app_key))

    def patch(self, request):
        d = request.data
        row, _ = InstrumentProfile.objects.get_or_create(user=request.user,
                                                         app_key=self.app_key)
        fields = []
        if "top_styles" in d:
            # Three, the blueprint's number, enforced here rather than trusted
            # from the client — the panel caps it at three and a panel is not
            # a rule.
            styles = [str(x)[:32] for x in (d.get("top_styles") or []) if str(x).strip()]
            row.top_styles = styles[:3]
            fields.append("top_styles")
        for key, field in (("bpm_min", "bpm_low"), ("bpm_max", "bpm_high")):
            if key in d:
                try:
                    n = int(d[key])
                    setattr(row, field, n if 20 <= n <= 400 else None)
                except (TypeError, ValueError):
                    setattr(row, field, None)
                fields.append(field)
        for field in ("goal_low", "goal_high"):
            if field in d:
                # A note name or nothing. Junk clears rather than 400s, the
                # same call `clean_code` makes about a personality letter: a
                # profile write must not fail over one bad character.
                v = str(d.get(field) or "").strip().upper()[:8]
                setattr(row, field, v if _NOTE.fullmatch(v) else "")
                fields.append(field)
        if fields:
            row.save(update_fields=fields + ["updated_at"])
        return Response(game_profile(request.user, self.app_key))


class GoalView(APIView):
    """POST /api/<key>/goal/ — the member's own declarations.

    Separate from the coach on purpose. What the coach hears is a measurement
    and this is a statement of intent, and a screen that let one overwrite the
    other would quietly turn "what I'm working towards" into "what you are".
    """
    permission_classes = [IsAuthenticated]
    app_key = "singz"

    def post(self, request):
        d = request.data
        prof = profile_for_app(self.app_key)
        valid = {k for k, _ in prof["ranges"]}
        row, _ = InstrumentProfile.objects.get_or_create(user=request.user,
                                                         app_key=self.app_key)
        fields = []
        for field in ("confirmed_range", "goal_range"):
            if field in d:
                v = str(d.get(field) or "").strip().lower()
                # An unrecognised range clears rather than 400s, exactly as
                # `personalityz.clean_code` treats an unknown letter: a profile
                # write must not fail over one bad value, and a wrong range
                # silently kept is worse than a blank.
                setattr(row, field, v if v in valid else "")
                fields.append(field)
        if "fatigue_sensitivity" in d:
            v = str(d.get("fatigue_sensitivity") or "").strip().lower()
            row.fatigue_sensitivity = v if v in THRESHOLD else ""
            fields.append("fatigue_sensitivity")
        for field in ("bpm_low", "bpm_high"):
            if field in d:
                try:
                    n = int(d[field])
                    setattr(row, field, n if 20 <= n <= 400 else None)
                except (TypeError, ValueError):
                    setattr(row, field, None)
                fields.append(field)
        if fields:
            row.save(update_fields=fields + ["updated_at"])
        return Response(progress(request.user, self.app_key))


# ------------------------------------------------- the game profile panel

# How many takes at a difficulty, scoring at least this, unlock the one above.
# The blueprint's rule for both apps — RapZ: "Boss Mode unlocks after passing 3
# style runs in the previous difficulty"; SingZ: "Stage Boss unlocks only after
# the user passes required Builder or Performer missions."
#
# It is computed from `TakeScore` rather than stored as a flag, for the reason
# strain is: a flag is a number that can drift from what happened, and a
# history can be argued with. It also means the unlock cannot be granted by
# anything except takes that actually scored.
BOSS_NEEDS_TAKES = 3
BOSS_NEEDS_SCORE = 6
BOSS_AT = "performer"


def boss_unlocked(user, app_key):
    """Has this member earned the top difficulty?

    Deliberately NOT "have they done three takes" — three takes that scored
    well. The substance rule's own test: turning up is worth something, but it
    is not worth being called good, and an unlock is a claim about being good.
    """
    return TakeScore.objects.filter(
        user=user, app_key=app_key, difficulty=BOSS_AT,
        overall__gte=BOSS_NEEDS_SCORE,
    ).count() >= BOSS_NEEDS_TAKES


def game_profile(user, app_key):
    """The blueprint's per-app profile, in the shape the panel already asks for.

    Every value here already existed somewhere — the detected range in
    `TakeScore`, the goal and BPM in `InstrumentProfile`, the fatigue read in
    `strain()`. What was missing was the endpoint: `GameProfilePanel.jsx` has
    been calling `/api/<key>/profile/` since it was written and getting a 404 a
    bare `.catch(() => {})` swallowed, so both panels rendered nothing at all.

    `range_work_allowed` is the SAME judgement `recovery_block` makes, read
    from the same place. Two answers to "is this member straining" would
    disagree, and the one on this panel is the one telling somebody it is safe
    to push their voice.
    """
    row = profile_row(user, app_key)
    heard = detected(user, app_key)
    s = strain(user, app_key)
    return {
        "app_key": app_key,
        "boss_unlocked": boss_unlocked(user, app_key),
        # RapZ's half.
        "top_styles": list(row.top_styles or []) if row else [],
        "bpm_min": row.bpm_low if row else None,
        "bpm_max": row.bpm_high if row else None,
        # SingZ's half. The detected edges are what the coach HEARD; the goal
        # edges are what the member SAID. Kept apart, like everywhere else.
        "detected_low": heard["low"],
        "detected_high": heard["high"],
        "detected_range": heard["range"],
        "goal_low": row.goal_low if row else "",
        "goal_high": row.goal_high if row else "",
        "goal_range": row.goal_range if row else "",
        # Recovery overrides progression — the blueprint's rule, and the one
        # thing on this panel a tier cannot buy past.
        "range_work_allowed": s["level"] != "strain",
        "strain": s,
    }
