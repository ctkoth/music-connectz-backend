"""BodieZ BodyMap — a filterable read over a member's own training log.

**This describes the log. It never scores the body**, and the difference is
the reason the module exists in this shape.

A logged set is a number somebody typed about themselves. There is no
microphone and no model watching, so nothing in the system can disagree with
the claim — which means the substance rule's test (*could a member get a good
number without getting good?*) answers itself the instant any of this is
called a strength score. It would be a worse failure than `directz_ai_rating`,
which at least measured real properties of a real artifact before drawing the
wrong conclusion from them.

So every number below is a statement about the LOG:

- `sets_logged`, `reps_logged` — counts of rows the member wrote.
- `volume_logged_lbs` — those rows multiplied out. Self-reported, and named
  so that it cannot be read as a measurement of strength.
- `last_trained` / `days_since` — timestamps we own. The one genuinely
  unfakeable thing here: a member can claim any weight, but they cannot claim
  to have opened the app on a day they did not.
- `coverage` — a WORD, and relative to the member's own other muscle groups,
  never to another member's.

Two things follow from that and must not rot:

- **Nothing here is ranked across members.** Showing somebody their own log
  back is honest; putting typed lifts on a leaderboard invents the incentive
  to inflate them with nothing in place to catch it. There is no `_for_all`
  in this file and there should never be one.
- **`coverage` is a label, not a score.** "untouched" and "heavy" describe a
  member's own distribution. A 0-10 number would be the same fabrication with
  a decimal point.
"""
from datetime import timedelta

from django.db.models import Count, F, FloatField, Max, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (EQUIPMENT_CHOICES, MUSCLE_GROUPS, PATTERN_CHOICES,
                     WorkoutSession, WorkoutSet)

MUSCLE_KEYS = [k for k, _ in MUSCLE_GROUPS]
MUSCLE_LABELS = dict(MUSCLE_GROUPS)
EQUIPMENT_KEYS = [k for k, _ in EQUIPMENT_CHOICES]
PATTERN_KEYS = [k for k, _ in PATTERN_CHOICES]

DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 365

# What a member would want to DO with a row, per muscle group. A screen that
# says "quads: untouched" and offers nowhere to go is the read-only surface
# the cross-pollination rule exists to close.
OPEN_IN = {"tab": "bodiez", "target": "bodiez:exercises"}


def _coverage(sets_here, mean_sets):
    """A word for how this group sits against the member's OWN average.

    Deliberately not a 0-10. `volume_logged_lbs` beside it already carries the
    quantity, in a unit the member can check; a second number with an invented
    denominator would add no information and would read as a verdict.
    """
    if sets_here == 0:
        return "untouched"
    if mean_sets <= 0:
        return "steady"
    if sets_here < mean_sets * 0.5:
        return "light"
    if sets_here > mean_sets * 1.5:
        return "heavy"
    return "steady"


def _trend_pct(now_vol, prev_vol):
    """Change in logged volume against the member's own previous window.

    This is the closest thing to a real training measurement available here,
    and it is honest for one specific reason: it compares a member only to
    themselves. Progressive overload IS the thing strength training is trying
    to produce, so a rising tonnage against your own last four weeks means
    what it appears to mean — no verification of the absolute numbers needed,
    because whatever a member's habits are when they type a set, they are the
    same habits in both windows.

    `None` when there is no prior volume: 0 → 50 is not "+100%", it is a
    member who has just started, and inventing a percentage there would put
    the biggest number in the app next to the least information.
    """
    if not prev_vol:
        return None
    return round(((now_vol - prev_vol) / prev_vol) * 100, 1)


def bodymap_for(user, *, days=DEFAULT_WINDOW_DAYS, muscles=None,
                equipment=None, pattern=None):
    """Per-muscle-group aggregates over one member's own log.

    Every filter narrows the SAME query — the whole map is one database round
    trip plus nothing, because a screen that renders twelve muscle groups must
    not cost twelve queries.

    A group filtered OUT is absent from `groups` rather than present with
    zeroes: a filter that still shows you what you filtered away is not a
    filter. A group that is simply untrained inside the window IS present,
    with `coverage: "untouched"` — that absence is the single most useful
    thing this read has to say, so it must not be silence.
    """
    now = timezone.now()
    since = now - timedelta(days=days)
    prev_since = since - timedelta(days=days)

    def _scoped(qs):
        if muscles:
            qs = qs.filter(muscle_group__in=muscles)
        if equipment:
            qs = qs.filter(equipment__in=equipment)
        if pattern:
            qs = qs.filter(pattern__in=pattern)
        return qs

    qs = _scoped(WorkoutSet.objects.filter(session__user=user,
                                           session__started_at__gte=since))

    # The previous equal-length window, for trend. Two queries for the whole
    # map rather than one — a per-group trend read would be twelve more, on a
    # screen that renders twelve groups at once.
    prev_rows = _scoped(WorkoutSet.objects.filter(
        session__user=user,
        session__started_at__gte=prev_since,
        session__started_at__lt=since,
    )).values("muscle_group").annotate(
        volume_logged_lbs=Coalesce(
            Sum(F("reps") * Coalesce(F("weight_lbs"), 0.0),
                output_field=FloatField()),
            0.0, output_field=FloatField()),
    )
    prev_volume = {r["muscle_group"]: r["volume_logged_lbs"] for r in prev_rows}

    rows = qs.values("muscle_group").annotate(
        sets_logged=Count("id"),
        reps_logged=Coalesce(Sum("reps"), 0),
        volume_logged_lbs=Coalesce(
            Sum(F("reps") * Coalesce(F("weight_lbs"), 0.0),
                output_field=FloatField()),
            0.0, output_field=FloatField()),
        last_trained=Max("session__started_at"),
        sessions_touching=Count("session_id", distinct=True),
    )
    by_key = {r["muscle_group"]: r for r in rows}

    # The mean is taken across groups the member ACTUALLY trained. Including
    # the untouched ones would drag it toward zero and quietly relabel a
    # neglected group as "steady" — the one reading this feature exists to
    # avoid giving.
    trained = [r["sets_logged"] for r in by_key.values() if r["sets_logged"]]
    mean_sets = (sum(trained) / len(trained)) if trained else 0.0

    # Which groups the answer covers: the filter when one was given, the whole
    # taxonomy otherwise.
    shown = list(muscles) if muscles else MUSCLE_KEYS

    total_volume = sum(r["volume_logged_lbs"] for r in by_key.values())

    groups = []
    for key in shown:
        r = by_key.get(key)
        last = r["last_trained"] if r else None
        volume = r["volume_logged_lbs"] if r else 0.0
        groups.append({
            "muscle_group": key,
            "label": MUSCLE_LABELS.get(key, key),
            "sets_logged": r["sets_logged"] if r else 0,
            "reps_logged": r["reps_logged"] if r else 0,
            # Weight x reps: the standard volume-load measure. In pounds,
            # because a quantity with a unit is one the member can check
            # against their own notebook. An index would not be.
            "volume_logged_lbs": round(volume, 1),
            # What share of the member's own training this group took. This is
            # the honest version of "am I balanced" — a proportion of their
            # own total, which needs no comparison to anybody else to mean
            # something.
            "volume_share_pct": (round(volume / total_volume * 100, 1)
                                 if total_volume else 0.0),
            # Against their own previous window of the same length.
            "volume_trend_pct": _trend_pct(volume, prev_volume.get(key, 0.0)),
            "sessions_touching": r["sessions_touching"] if r else 0,
            "last_trained": last.isoformat() if last else None,
            "days_since": (now - last).days if last else None,
            "coverage": _coverage(r["sets_logged"] if r else 0, mean_sets),
            **OPEN_IN,
        })

    return {
        "window_days": days,
        "total_volume_lbs": round(total_volume, 1),
        "groups": groups,
        # Said out loud, on the payload, so a client cannot render this as a
        # fitness assessment without contradicting the thing it is rendering.
        "measures": "volume you logged, compared with your own previous "
                    "window — not a strength rating, and not comparable "
                    "between members",
    }


def _multi(request, param, allowed):
    """Read a repeatable/comma-joined filter value, or raise on an unknown key.

    An unrecognised filter is refused rather than dropped. Silently ignoring
    `?muscle=quadd` would answer with every muscle group and look exactly like
    a filter that ran — which is worse than an error, because the member acts
    on the wrong answer believing they narrowed it.
    """
    raw = request.query_params.getlist(param)
    values = []
    for chunk in raw:
        values.extend(p.strip() for p in chunk.split(",") if p.strip())
    unknown = [v for v in values if v not in allowed]
    if unknown:
        raise ValueError(
            f"Unknown {param}: {', '.join(sorted(set(unknown)))}. "
            f"Pick from: {', '.join(allowed)}.")
    return values


class BodyMapView(APIView):
    """`GET /api/economy/bodiez/bodymap/` — the filterable log read.

    `?muscle=quads,glutes&equipment=barbell&pattern=hinge&days=90`
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            muscles = _multi(request, "muscle", MUSCLE_KEYS)
            equipment = _multi(request, "equipment", EQUIPMENT_KEYS)
            pattern = _multi(request, "pattern", PATTERN_KEYS)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            days = int(request.query_params.get("days") or DEFAULT_WINDOW_DAYS)
        except (TypeError, ValueError):
            return Response({"detail": "days must be a whole number of days."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not 1 <= days <= MAX_WINDOW_DAYS:
            return Response({"detail": f"days must be between 1 and {MAX_WINDOW_DAYS}."},
                            status=status.HTTP_400_BAD_REQUEST)

        data = bodymap_for(request.user, days=days, muscles=muscles,
                           equipment=equipment, pattern=pattern)
        # The client builds its filter controls from these rather than
        # retyping the taxonomy — the same reason a tier number is never
        # hardcoded into a screen.
        data["filters"] = {
            "muscle": [{"key": k, "label": v} for k, v in MUSCLE_GROUPS],
            "equipment": [{"key": k, "label": v} for k, v in EQUIPMENT_CHOICES],
            "pattern": [{"key": k, "label": v} for k, v in PATTERN_CHOICES],
        }
        return Response(data)


class WorkoutSessionView(APIView):
    """`GET /api/economy/bodiez/sessions/` · `POST` to log one.

    Free at every tier, and that is a decision rather than an omission: a
    member who cannot record that they trained does not upgrade, they stop
    opening the tab. Nothing here charges ⚡ or pays 🍥 — see the module
    docstring in `bodymap.py` for why self-reported work must not pay a
    farmable resource.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sessions = (WorkoutSession.objects.filter(user=request.user)
                    .prefetch_related("sets")[:50])
        return Response({"sessions": [{
            "id": s.id,
            "started_at": s.started_at.isoformat(),
            "duration_minutes": s.duration_minutes,
            "notes": s.notes,
            "sets": [{
                "exercise_name": w.exercise_name,
                "muscle_group": w.muscle_group,
                "equipment": w.equipment,
                "pattern": w.pattern,
                "reps": w.reps,
                "weight_lbs": w.weight_lbs,
                "duration_seconds": w.duration_seconds,
            } for w in s.sets.all()],
        } for s in sessions]})

    def post(self, request):
        d = request.data or {}
        raw_sets = d.get("sets") or []
        if not isinstance(raw_sets, list) or not raw_sets:
            return Response({"detail": "Log at least one set."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Validated BEFORE the session row is written, so a bad set cannot
        # leave an empty session behind to be counted as a day trained.
        cleaned = []
        for i, s in enumerate(raw_sets):
            if not isinstance(s, dict):
                return Response({"detail": f"Set {i + 1} isn't a set."},
                                status=status.HTTP_400_BAD_REQUEST)
            muscle = str(s.get("muscle_group") or "").strip()
            if muscle not in MUSCLE_KEYS:
                return Response(
                    {"detail": f"Set {i + 1}: unknown muscle group {muscle!r}. "
                               f"Pick from: {', '.join(MUSCLE_KEYS)}."},
                    status=status.HTTP_400_BAD_REQUEST)
            equip = str(s.get("equipment") or "other").strip()
            patt = str(s.get("pattern") or "other").strip()
            weight = s.get("weight_lbs")
            try:
                weight = float(weight) if weight not in (None, "") else None
            except (TypeError, ValueError):
                return Response({"detail": f"Set {i + 1}: weight isn't a number."},
                                status=status.HTTP_400_BAD_REQUEST)
            cleaned.append(WorkoutSet(
                exercise_name=str(s.get("exercise_name") or "").strip()[:80],
                muscle_group=muscle,
                equipment=equip if equip in EQUIPMENT_KEYS else "other",
                pattern=patt if patt in PATTERN_KEYS else "other",
                reps=max(0, int(s.get("reps") or 0)),
                weight_lbs=weight,
                duration_seconds=max(0, int(s.get("duration_seconds") or 0)),
            ))

        session = WorkoutSession.objects.create(
            user=request.user,
            started_at=timezone.now(),
            duration_minutes=max(0, int(d.get("duration_minutes") or 0)),
            notes=str(d.get("notes") or "")[:2000],
        )
        for w in cleaned:
            w.session = session
        WorkoutSet.objects.bulk_create(cleaned)

        return Response({"id": session.id, "sets": len(cleaned)},
                        status=status.HTTP_201_CREATED)
