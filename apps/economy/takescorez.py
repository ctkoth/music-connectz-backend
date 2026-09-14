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
from .models import InstrumentProfile, TakeScore

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


def record(user, app_key, payload, *, difficulty="", genre="", target="",
           style="", upload=None, source="", ref=""):
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
        dims = scores_for(app_key, lyrics=bool(payload.get("rated_lyrics")))
        # Whitelisted against the instrument's own dimensions, so a key the
        # model invents cannot reach the column — the same guard the payload
        # itself already passes through in `score_take`.
        scores = {k: v for k, v in (payload.get("scores") or {}).items()
                  if k in dims and isinstance(v, int)}
        overall = round(sum(scores.values()) / len(scores)) if scores else None
        weakest = min(scores, key=lambda k: scores[k]) if scores else ""
        cls, low, high = parse_range(payload.get("range_profile"), prof["ranges"])
        return TakeScore.objects.create(
            user=user, app_key=app_key, scores=scores, overall=overall,
            weakest=weakest, difficulty=str(difficulty or "")[:16],
            genre=str(genre or "")[:60], target=str(target or "")[:60],
            style=str(style or "")[:60],
            range_class=cls, low_note=low, high_note=high,
            upload=upload, source=str(source or "")[:16], ref=str(ref or "")[:64],
        )
    except Exception:                                       # pragma: no cover
        return None


# --------------------------------------------------------------- reading

def profile_row(user, app_key):
    """The member's declarations for this instrument. Never auto-created on a
    read — an empty row for every member who ever opened a coach is a table of
    nothing, and `get_or_create` on a GET is a write on a read."""
    return InstrumentProfile.objects.filter(user=user, app_key=app_key).first()


def _recent(user, app_key, *, hours=None, days=None, limit=200):
    since = timezone.now() - (timedelta(hours=hours) if hours else timedelta(days=days))
    return list(TakeScore.objects.filter(user=user, app_key=app_key,
                                         created_at__gte=since)[:limit])


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


def trend(user, app_key):
    """Per-dimension movement: the first half of the window against the second.

    Both halves carry their own count, for the reason FunnelZ's headline does:
    a dimension that moved from one take to one take has not moved.
    """
    takes = sorted(_recent(user, app_key, days=RECENT_DAYS), key=lambda t: t.created_at)
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


def progress(user, app_key):
    """Everything the history knows, in one call. It renders as a screen."""
    prof = profile_for_app(app_key)
    row = profile_row(user, app_key)
    takes = TakeScore.objects.filter(user=user, app_key=app_key)[:10]
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
        "sensitivities": [{"key": k, "label": l} for k, l in InstrumentProfile.SENSITIVITY],
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
        "takes": [{"id": t.pk, "overall": t.overall, "scores": t.scores,
                   "weakest": t.weakest, "difficulty": t.difficulty,
                   "range_class": t.range_class, "low": t.low_note, "high": t.high_note,
                   "at": t.created_at.isoformat(),
                   "open_in": ({"tab": "postz", "target": t.ref} if t.source == "post"
                               else {"tab": "journalz", "target": "journalz-entries"}
                               if t.source == "journal" else None)}
                  for t in takes],
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
        return Response(progress(request.user, self.app_key))


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
