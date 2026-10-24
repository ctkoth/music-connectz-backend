"""BodieZ — strength-training, workout-planning, and now a Jefit-style
routine board scheduled the way Lilith schedules a task.

v1 shipped a movement library, saved routines, and a live/finished session
log with sets and weight, plus a progress read (total volume and session
count) so a member can see the number move.

This adds the piece the blueprint calls out by name — the same
Inbox/Today/Upcoming/Anytime/Someday scheduler Lilith already has, applied to
a routine instead of a task. `BODIEZ_BUCKETS` is BodieZ's own tuple (see
models.py for why it isn't a shared one with Lilith's `BUCKETS`), and
`BodieZBoardView` answers the same "one open, one request" question
`lilith_taskz.LilithBoardView` does: five buckets is five lists to render,
and a board assembled from five round trips is a board that flickers.

This also adds BodyMap and Coach, and both follow the substance rule the same
way `vocalcoach.py` does — every number traces to a logged, FINISHED set.
Nothing here is an AI model, on purpose: "Coach" in the blueprint reads as a
recommendation engine, and a recommendation engine that cannot show its work
is exactly the `directz_ai_rating` failure with a friendlier name. So both are
arithmetic over `BodieZSet` rows, not a call to Gemini —

- **BodyMap** (`BodieZBodyMapView`) buckets each muscle group into
  recent/balanced/overworked/undertrained/untrained from real session dates
  and set counts in a trailing window. No routine's PLAN counts — "leg day" on
  a routine isn't a leg day until a set gets logged, same as everywhere else
  in this file.
- **Coach** (`BodieZCoachView`) compares each exercise's most recent logged
  session against its previous one — same weight with equal-or-more reps
  suggests adding weight, a weight drop is a deload, no weighted sets at all
  falls back to a rep-count comparison, and an exercise untouched past
  `STALE_DAYS` gets flagged to reintroduce or swap. Every recommendation
  carries `why`, in the member's own numbers — "same 60kg, same-or-more reps
  (8 vs 7)" — because a recommendation with no visible arithmetic behind it is
  a black box wearing a coach's name, and that is the thing this whole rule
  exists to keep out of the app.

This also adds Goals (`BodieZGoalsView`), and it holds the same line: four
kinds, `BODIEZ_GOAL_KINDS`, and every one reads its progress off data this app
already logs rather than trusting the member's own report of how they're
doing —

- **strength** — an exercise + a target weight. Progress is the best
  matching set ever logged, same "read the real rows" the Coach uses.
- **frequency** — sessions per week, read off the trailing 7 days.
- **count** — a lifetime finished-session target ("complete 100 workouts").
- **bodyweight** — the one kind that needs a number nothing else in this app
  logs, so `BodieZWeightLog` is a bare check-in (weight + timestamp, nothing
  else) — not the start of Nutrition or body composition, which stays
  explicitly out of scope. Progress reads the STARTING value snapshotted at
  goal creation against the latest log, so "losing 15 pounds" and "gaining
  15 pounds" both compute correctly from the same two numbers.

There is deliberately no fifth "custom" kind with a member-typed target and
nothing to check it against — that would be a goal the substance rule's own
test answers yes to ("could a member get a good number without doing the
work?"), so `achieved` is never a checkbox a member ticks themselves.

Deliberately still NOT built here: Nutrition, Community, Recovery, and
XP/streak rewards. The last one is worth explaining rather than just omitting
— XP here would need its own wallet column (nothing in this codebase has a
general per-user XP total; LilithPayout.xp is Lilith-specific) and a decision
about whether a logged set is "effort" in the sense the substance rule allows
XP for. That is a real design question, not a gap to fill silently, so it
stays a follow-up.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (BODIEZ_BUCKETS, BODIEZ_DAY_TAGS, BODIEZ_GOAL_KINDS, BodieZAccess,
                     BodieZCustomDay, BodieZExercise, BodieZGoal, BodieZRecoveryLog, BodieZRoutine, BodieZStepLog, BodieZSession, BodieZSet,
                     BodieZWeightLog, StudentRelationship)

_BUCKET_KEYS = {k for k, _ in BODIEZ_BUCKETS}
_DAY_TAG_KEYS = {k for k, _ in BODIEZ_DAY_TAGS}


def _exercise_dict(ex):
    return {"id": ex.id, "name": ex.name, "muscle_group": ex.muscle_group,
            "equipment": ex.equipment, "demo_url": ex.demo_url,
            "positions": ex.position_list, "needs_arms": ex.needs_arms,
            "needs_legs": ex.needs_legs, "one_arm_ok": ex.one_arm_ok,
            "one_leg_ok": ex.one_leg_ok, "custom": ex.created_by_id is not None}


# Who can do what. ONE function decides, and the exercise list carries its
# answer as `accessible` on every row, so the client renders a flag instead of
# re-deriving the rule — a second copy of "unusable legs implies seated" is
# how a screen ends up offering a standing lift to somebody who cannot stand.
SEATED_OR_LYING = {"seated", "lying"}


def accessible(ex, access):
    """True if a member with this `BodieZAccess` (or None, meaning no
    restrictions) can do this exercise."""
    if access is None:
        return True
    if not access.arms_ok and ex.needs_arms:
        return False
    if access.one_arm_only and ex.needs_arms and not ex.one_arm_ok:
        return False
    if not access.legs_ok and ex.needs_legs:
        return False
    if access.one_leg_only and ex.needs_legs and not ex.one_leg_ok:
        return False
    # Unusable legs implies no standing — a standing exercise is a leg
    # exercise whatever muscle it is filed under.
    must_sit = access.seated_or_lying_only or not access.legs_ok
    if must_sit and not (SEATED_OR_LYING & set(ex.position_list)):
        return False
    return True


def _access_dict(access):
    return {
        "seated_or_lying_only": bool(access and access.seated_or_lying_only),
        "arms_ok": True if access is None else access.arms_ok,
        "one_arm_only": bool(access and access.one_arm_only),
        "legs_ok": True if access is None else access.legs_ok,
        "one_leg_only": bool(access and access.one_leg_only),
    }


class BodieZAccessView(APIView):
    """GET/PUT /api/economy/bodiez/access/ — what the member's body can do.
    Written only by the member, about themselves; it filters what BodieZ
    offers and changes nothing about what they are scored on."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_access_dict(BodieZAccess.objects.filter(user=request.user).first()))

    def put(self, request):
        d = request.data or {}

        def flag(key, default):
            v = d.get(key, default)
            if isinstance(v, bool):
                return v
            if isinstance(v, str) and v.lower() in ("true", "false", "1", "0"):
                return v.lower() in ("true", "1")
            return None

        row, _ = BodieZAccess.objects.get_or_create(user=request.user)
        for key in ("seated_or_lying_only", "arms_ok", "one_arm_only", "legs_ok", "one_leg_only"):
            v = flag(key, getattr(row, key))
            if v is None:
                return Response({"error": f"{key} must be true or false."},
                                status=status.HTTP_400_BAD_REQUEST)
            setattr(row, key, v)
        # No arms is the stricter answer; keeping one-arm on beside it would
        # be two answers that contradict each other.
        if not row.arms_ok:
            row.one_arm_only = False
        if not row.legs_ok:
            row.one_leg_only = False
        row.save()
        return Response(_access_dict(row))


# Corey's real credential, stated once here rather than on every video — a
# citation repeated 30 times is 30 places it can drift the moment it needs a
# correction, the same reasoning `catalog.py`'s tier numbers already follow.
# It travels on the LIBRARY response (every demo video comes from this same
# list) rather than per-exercise, because the claim is about who recorded the
# set, not about any one clip.
DEMO_CREDIT = "Demonstrated by an IFPA-certified trainer."


# Real, published rep/set/rest prescriptions, one per training goal — never a
# model's guess and never typed twice. A "Build a routine" button that picked
# exercises without saying how many sets or reps would be the substance
# rule's failure case with a barbell in it: a routine a member could follow
# blindly and get nothing from, because the actual training stimulus (volume,
# intensity, rest) never got specified. Each scheme cites the source it comes
# from, in the member's own words, so "why 8-12 reps" has an answer beyond
# "the app said so" — the same standard `_HISTORY_CAVEAT` already holds Coach
# to for what a single take can and can't show.
#
# Four goals now, not the many an exercise-science textbook would name,
# because four is what a member choosing a routine actually decides between:
# strength, muscle gain, toning, slimming.
#
# Strength is keyed "strength_training", never "strength" — BodieZGoal
# already has a "strength" KIND driven by logged 1RM progress (a personal
# target: "bench 225"), and this dict is a training PROTOCOL (a rep/set/rest
# prescription a routine follows). Both showing as "Strength" on the same
# screen would read as one feature, and they answer different questions —
# "what am I aiming for" versus "how should today's session be loaded". The
# label stays "Strength" because that's what a member is choosing; the KEY
# is what stays distinct, since that's what a second writer would collide on.
GOALS = {
    "muscle_gain": {
        "label": "Muscle gain",
        "sets": 4, "reps_low": 8, "reps_high": 12, "rest_seconds": 75,
        "why": ("Moderate load, moderate reps, short-to-moderate rest — the range "
                "most consistently associated with hypertrophy across training "
                "studies, because it maximizes total volume load without the "
                "fatigue cost of near-maximal singles."),
        "citation": ("American College of Sports Medicine. (2009). Progression "
                     "models in resistance training for healthy adults. Medicine "
                     "& Science in Sports & Exercise, 41(3), 687-708; Schoenfeld, "
                     "B. J. (2010). The mechanisms of muscle hypertrophy and their "
                     "application to resistance training. Journal of Strength and "
                     "Conditioning Research, 24(10), 2857-2872."),
    },
    "toning": {
        "label": "Toning (muscular endurance)",
        "sets": 3, "reps_low": 15, "reps_high": 20, "rest_seconds": 45,
        "why": ("Lighter load for more reps, shorter rest — builds the muscular "
                "endurance and definition most people mean by \"toning\" without "
                "the heavier loading hypertrophy training calls for."),
        "citation": ("American College of Sports Medicine. (2009). Progression "
                     "models in resistance training for healthy adults. Medicine "
                     "& Science in Sports & Exercise, 41(3), 687-708."),
    },
    "fat_loss": {
        "label": "Slimming (fat loss)",
        "sets": 3, "reps_low": 12, "reps_high": 15, "rest_seconds": 30,
        "why": ("Short rest between sets keeps heart rate elevated through the "
                "whole session — closer to circuit training than traditional "
                "lifting — which raises total energy expenditure per session. "
                "Real fat loss still runs on a sustained calorie deficit; this "
                "changes how the session trains, not that."),
        "citation": ("Kraemer, W. J., & Ratamess, N. A. (2004). Fundamentals of "
                     "resistance training: Progression and exercise prescription. "
                     "Medicine & Science in Sports & Exercise, 36(4), 674-688."),
    },
    "strength_training": {
        "label": "Strength",
        "sets": 5, "reps_low": 3, "reps_high": 5, "rest_seconds": 180,
        "why": ("Heavy load, low reps, long rest between sets — the range that "
                "builds maximal force output rather than size. Reps this low "
                "can't be trained to failure safely without a spotter or a "
                "power rack, so the rest is long enough for near-full recovery "
                "between sets rather than the shorter rest hypertrophy work uses."),
        "citation": ("National Academy of Sports Medicine. (2022). NASM Essentials "
                     "of Personal Fitness Training (7th ed.) — OPT Model, Phase 4: "
                     "Maximal Strength; American College of Sports Medicine. (2009). "
                     "Progression models in resistance training for healthy adults. "
                     "Medicine & Science in Sports & Exercise, 41(3), 687-708."),
    },
}


# One split per training-day count, 1 through 6 — what "Build a Routine"
# had NEVER offered: a member could only ever get one routine, one exercise
# per muscle group, whatever they clicked. Asked outright "does this cover
# every muscle across a real week", the honest answer used to be no, and
# this is that gap closed rather than talked around.
#
# Each split is a real, named convention — full body, upper/lower,
# push/pull/legs, a body-part split — not an invented one; see Baechle &
# Earle (2008) for the same set discussed as standard programming choices.
#
# The "arms rides on both Push and Pull days" compromise that used to sit
# here is GONE, not just reworded: migration 0145 split the library's old
# "arms" bucket into biceps, triceps and forearms, so Push and Pull can each
# get the muscle that actually belongs to them (triceps on Push, biceps and
# forearms on Pull) instead of a duplicated blanket bucket standing in for
# data this app didn't have. Same for "legs" -> upper_legs/lower_legs and
# "core" -> abs. Body-part split's own "Arms" day still groups biceps,
# triceps and forearms together — that one's a day-count constraint (five
# days/week means five routines, not eight), not a data gap.
SPLITS = {
    1: {"label": "1 day/week — Full Body",
        "days": [{"label": "Full Body", "muscles": ["chest", "back", "shoulders", "biceps", "triceps",
                                                       "forearms", "upper_legs", "lower_legs", "abs", "glutes"]}]},
    2: {"label": "2 days/week — Upper / Lower",
        "days": [
            {"label": "Upper", "muscles": ["chest", "back", "shoulders", "biceps", "triceps", "forearms"]},
            {"label": "Lower", "muscles": ["upper_legs", "lower_legs", "abs", "glutes"]},
        ]},
    3: {"label": "3 days/week — Push / Pull / Legs",
        "days": [
            {"label": "Push", "muscles": ["chest", "shoulders", "triceps"]},
            {"label": "Pull", "muscles": ["back", "biceps", "forearms"]},
            {"label": "Legs", "muscles": ["upper_legs", "lower_legs", "abs", "glutes"]},
        ]},
    4: {"label": "4 days/week — Upper / Lower x2",
        "days": [
            {"label": "Upper A", "muscles": ["chest", "back", "shoulders", "biceps", "triceps", "forearms"]},
            {"label": "Lower A", "muscles": ["upper_legs", "lower_legs", "abs", "glutes"]},
            {"label": "Upper B", "muscles": ["chest", "back", "shoulders", "biceps", "triceps", "forearms"]},
            {"label": "Lower B", "muscles": ["upper_legs", "lower_legs", "abs", "glutes"]},
        ]},
    5: {"label": "5 days/week — Body-part split",
        "days": [
            {"label": "Chest", "muscles": ["chest"]},
            {"label": "Back", "muscles": ["back"]},
            {"label": "Shoulders", "muscles": ["shoulders"]},
            {"label": "Arms", "muscles": ["biceps", "triceps", "forearms"]},
            {"label": "Legs", "muscles": ["upper_legs", "lower_legs", "abs", "glutes"]},
        ]},
    6: {"label": "6 days/week — Push / Pull / Legs x2",
        "days": [
            {"label": "Push A", "muscles": ["chest", "shoulders", "triceps"]},
            {"label": "Pull A", "muscles": ["back", "biceps", "forearms"]},
            {"label": "Legs A", "muscles": ["upper_legs", "lower_legs", "abs", "glutes"]},
            {"label": "Push B", "muscles": ["chest", "shoulders", "triceps"]},
            {"label": "Pull B", "muscles": ["back", "biceps", "forearms"]},
            {"label": "Legs B", "muscles": ["upper_legs", "lower_legs", "abs", "glutes"]},
        ]},
}


def _routine_dict(r):
    return {"id": r.id, "title": r.title, "description": r.description,
            "exercises": r.exercises, "bucket": r.bucket, "day_tag": r.day_tag,
            "custom_day_id": r.custom_day_id,
            "goal": r.goal, "source": r.source,
            "scheduled_for": r.scheduled_for.isoformat() if r.scheduled_for else None,
            "updated_at": r.updated_at.isoformat()}


# Until this moment the weight box was labelled kg for everyone, so a US
# member typed pounds into it and the number was stored as kilograms (35 lb
# saved as 35 kg, read back as 77 lb). Sets from before it can be re-read as
# pounds by their owner — only by their owner, because only they know which
# unit they meant.
from datetime import datetime, timezone as _tz  # noqa: E402
LB_SWITCH_AT = datetime(2026, 10, 2, 19, 20, tzinfo=_tz.utc)
KG_PER_LB = Decimal("0.45359237")


def _lb_fix_scope(user):
    sets = BodieZSet.objects.filter(session__user=user, created_at__lt=LB_SWITCH_AT,
                                    weight_kg__isnull=False, converted_from_lb=False)
    routines = [r for r in BodieZRoutine.objects.filter(user=user, updated_at__lt=LB_SWITCH_AT)
                if any(isinstance(e, dict) and e.get("weight_kg") not in (None, "")
                       and not e.get("lb_fixed") for e in (r.exercises or []))]
    return sets, routines


class BodieZLbFixView(APIView):
    """GET how many pre-pounds weights this member has; POST converts them."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sets, routines = _lb_fix_scope(request.user)
        sample = sets.order_by("-created_at").first()
        return Response({
            "cutoff": LB_SWITCH_AT.isoformat(),
            "sets": sets.count(), "routines": len(routines),
            "example_kg": float(sample.weight_kg) if sample else None,
        })

    def post(self, request):
        sets, routines = _lb_fix_scope(request.user)
        n = 0
        for x in sets:
            x.weight_kg = (x.weight_kg * KG_PER_LB).quantize(Decimal("0.01"))
            x.converted_from_lb = True
            x.save(update_fields=["weight_kg", "converted_from_lb"])
            n += 1
        for r in routines:
            for e in r.exercises:
                if isinstance(e, dict) and e.get("weight_kg") not in (None, "") and not e.get("lb_fixed"):
                    e["weight_kg"] = round(float(e["weight_kg"]) * float(KG_PER_LB), 2)
                    e["lb_fixed"] = True
            # update() so updated_at does not move — the routine was not edited.
            BodieZRoutine.objects.filter(id=r.id).update(exercises=r.exercises)
        return Response({"sets": n, "routines": len(routines)})


# A 50-rep bodyweight set is real; 32767 (the column's ceiling) is a typo.
MAX_REPS_PER_SET = 1000


ONE_SIDED = {"": "", "arm": "one arm", "leg": "one leg"}


def _clean_side(raw):
    """"" | "arm" | "leg", or None when it is something else."""
    raw = "" if raw is None else str(raw).strip().lower()
    return raw if raw in ONE_SIDED else None


def _lane(s):
    """A set's comparison lane: same exercise, done the same way."""
    return (s.exercise_id, s.one_sided)


def _lane_name(name, side):
    return f"{name} ({ONE_SIDED[side]})" if side else name


def _set_dict(s):
    return {"id": s.id, "exercise_id": s.exercise_id, "exercise_name": s.exercise.name,
            "set_number": s.set_number, "reps": s.reps,
            "weight_kg": float(s.weight_kg) if s.weight_kg is not None else None,
            "one_sided": s.one_sided, "position": s.position,
            "rest_seconds": s.rest_seconds, "created_at": s.created_at.isoformat()}


def _session_dict(sess, sets=None):
    sets = sets if sets is not None else list(sess.sets.select_related("exercise"))
    # The member's order where they set one (typed in, edited or dragged), else the order
    # it happened. The model's own ordering is per-exercise set number, which interleaves.
    sets = sorted(sets, key=lambda s: (s.position, s.id))
    return {
        "id": sess.id,
        "routine_id": sess.routine_id,
        "routine_title": sess.routine.title if sess.routine_id and sess.routine else None,
        "routine_goal": sess.routine.goal if sess.routine_id and sess.routine else "",
        "started_at": sess.started_at.isoformat(),
        "ended_at": sess.ended_at.isoformat() if sess.ended_at else None,
        "backfilled": sess.backfilled,
        "notes": sess.notes,
        "sets": [_set_dict(s) for s in sets],
    }


class BodieZExercisesView(APIView):
    """GET /api/economy/bodiez/exercises/ — the movement library, everyone's,
    read-only. Nothing here is per-user, so there is no write endpoint."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = BodieZExercise.objects.visible(request.user)
        muscle = request.query_params.get("muscle_group")
        if muscle:
            rows = rows.filter(muscle_group=muscle)
        # demo_credit only when at least one row in the library actually has
        # a video — an unearned credential line on a library with no clips to
        # its name would be exactly the kind of claim the substance rule
        # exists to keep off screen.
        credit = DEMO_CREDIT if BodieZExercise.objects.library().exclude(demo_url="").exists() else ""
        access = BodieZAccess.objects.filter(user=request.user).first()
        # EVERY exercise is returned, each flagged. A member's old sessions and
        # routines still name exercises they can no longer pick, and those rows
        # must keep their names; hiding is the picker's job, via `accessible`.
        # What THIS member has actually logged, from finished sessions only —
        # one grouped query for the whole library, never one per row. Absent
        # (not zero) for an exercise they have never done, so "done before"
        # is a fact about their history and not a default.
        done = {r["exercise_id"]: r for r in
                BodieZSet.objects.filter(session__user=request.user, session__ended_at__isnull=False)
                .values("exercise_id").annotate(times=Count("session_id", distinct=True),
                                                last=Max("session__started_at"))}
        def _done(e):
            d = done.get(e.id)
            return ({"times_done": d["times"], "last_done": d["last"].isoformat()} if d
                    else {"times_done": 0, "last_done": None})
        return Response({
            "exercises": [{**_exercise_dict(e), **_done(e), "accessible": accessible(e, access)} for e in rows],
            "demo_credit": credit,
            "access": _access_dict(access),
        })


class BodieZExerciseHistoryView(APIView):
    """GET /api/economy/bodiez/exercises/<id>/history/ — this member's own
    most recent logged sets against this exercise, from a FINISHED session.

    This is the Jefit signature feature: showing "last time: 3x8 @ 60kg"
    beside the input while logging today's set. It has to be a real number
    off a real row, never a suggested target — a logger that pre-fills last
    time's numbers as a DEFAULT is fine (the member can change them); a
    logger that invents a number because nothing was logged yet is the
    substance rule's failure case wearing a progress tracker's clothes.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, exercise_id):
        # Last time done THE SAME WAY: a one-arm row is not last week's two-arm row.
        side = _clean_side(request.query_params.get("one_sided")) or ""
        last_set = (BodieZSet.objects
                    .filter(session__user=request.user, session__ended_at__isnull=False,
                            exercise_id=exercise_id, one_sided=side)
                    .order_by("-session__started_at", "-set_number")
                    .select_related("session")
                    .first())
        if not last_set:
            return Response({"last_session": None})
        sets = (BodieZSet.objects
                .filter(session=last_set.session_id, exercise_id=exercise_id, one_sided=side)
                .order_by("set_number"))
        return Response({
            "last_session": {
                "started_at": last_set.session.started_at.isoformat(),
                "sets": [_set_dict(s) for s in sets],
            },
        })


MAX_CUSTOM_DAYS = 20
MAX_CUSTOM_EXERCISES = 200
_MUSCLES = {k for k, _ in BodieZExercise.MUSCLE_CHOICES}
_EQUIPMENT = {k for k, _ in BodieZExercise.EQUIPMENT_CHOICES}
_POSITIONS = [k for k, _ in BodieZExercise.POSITION_CHOICES]


def _flag(v, default):
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.lower() in ("true", "false", "1", "0"):
        return v.lower() in ("true", "1")
    return None


class BodieZCustomExerciseView(APIView):
    """POST /api/economy/bodiez/exercises/custom/ — make an exercise of your own.

    {name, muscle_group, equipment, positions: [..], needs_arms?, needs_legs?,
     one_arm_ok?, one_leg_ok?}

    Private to the member. The movement tags are THEIR statement about their
    own exercise, and the same access filter then applies to it as to the
    library — so a custom lift tagged "needs arms" is hidden from a member who
    cannot use theirs, exactly like a library one. Untagged defaults are the
    cautious ones (needs everything, standing).

    A name that is already in the library is refused with that exercise's id:
    a second "Bench Press" would split the member's history across two rows and
    quietly break their records, which compare by exercise.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        d = request.data or {}
        name = " ".join(str(d.get("name") or "").split())
        if not 2 <= len(name) <= 80:
            return Response({"detail": "Give the exercise a name of 2 to 80 characters."},
                            status=status.HTTP_400_BAD_REQUEST)
        muscle, equipment = d.get("muscle_group"), d.get("equipment")
        if muscle not in _MUSCLES:
            return Response({"detail": "Pick the muscle it works."}, status=status.HTTP_400_BAD_REQUEST)
        if equipment not in _EQUIPMENT:
            return Response({"detail": "Pick the equipment it uses."}, status=status.HTTP_400_BAD_REQUEST)
        raw_pos = d.get("positions")
        if isinstance(raw_pos, str):
            raw_pos = [p for p in raw_pos.split(",") if p]
        positions = [p for p in _POSITIONS if p in (raw_pos or [])]  # canonical order, junk dropped
        if not positions:
            return Response({"detail": "Say how it can be done: standing, seated, lying, kneeling or on the floor."},
                            status=status.HTTP_400_BAD_REQUEST)
        flags = {k: _flag(d.get(k), default) for k, default in
                 (("needs_arms", True), ("needs_legs", True), ("one_arm_ok", False), ("one_leg_ok", False))}
        if None in flags.values():
            return Response({"detail": "Those options must be yes or no."}, status=status.HTTP_400_BAD_REQUEST)

        clash = BodieZExercise.objects.library().filter(name__iexact=name).first()
        if clash:
            return Response({"detail": f"{clash.name} is already in the library — use that one so your history stays together.",
                             "existing_id": clash.id}, status=status.HTTP_400_BAD_REQUEST)
        mine = BodieZExercise.objects.filter(created_by=request.user)
        own = mine.filter(name__iexact=name).first()
        if own:
            return Response({"detail": f"You already made {own.name}.", "existing_id": own.id},
                            status=status.HTTP_400_BAD_REQUEST)
        if mine.count() >= MAX_CUSTOM_EXERCISES:
            return Response({"detail": f"You can keep {MAX_CUSTOM_EXERCISES} custom exercises. Delete one you don't use."},
                            status=status.HTTP_400_BAD_REQUEST)

        ex = BodieZExercise.objects.create(created_by=request.user, name=name, muscle_group=muscle,
                                           equipment=equipment, positions=",".join(positions), **flags)
        access = BodieZAccess.objects.filter(user=request.user).first()
        return Response({**_exercise_dict(ex), "times_done": 0, "last_done": None,
                         "accessible": accessible(ex, access)}, status=status.HTTP_201_CREATED)


class BodieZCustomExerciseDetailView(APIView):
    """DELETE /api/economy/bodiez/exercises/custom/{id}/ — only your own, and
    only while nothing uses it. Deleting would erase logged sets (they cascade)
    and leave routines naming an exercise that no longer exists."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, exercise_id):
        ex = BodieZExercise.objects.filter(id=exercise_id, created_by=request.user).first()
        if not ex:
            return Response({"detail": "Exercise not found."}, status=status.HTTP_404_NOT_FOUND)
        in_routine = any(isinstance(e, dict) and e.get("exercise_id") == ex.id
                         for r in BodieZRoutine.objects.filter(user=request.user) for e in (r.exercises or []))
        if (BodieZSet.objects.filter(exercise=ex).exists() or in_routine
                or BodieZGoal.objects.filter(exercise=ex).exists()):
            return Response({"detail": "It's in your history, a routine or a goal, so it can't be deleted."},
                            status=status.HTTP_400_BAD_REQUEST)
        ex.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _own_custom_day(user, raw):
    """None for blank, the row for one of the member's own days, "bad" for
    anything else — somebody else's day id must read exactly like a missing
    one, so ids can't be probed."""
    if raw in (None, "", 0, "0"):
        return None
    try:
        return BodieZCustomDay.objects.get(id=int(raw), user=user)
    except (BodieZCustomDay.DoesNotExist, TypeError, ValueError):
        return "bad"


def _custom_day_dict(d):
    return {"id": d.id, "name": d.name}


class BodieZCustomDaysView(APIView):
    """GET/POST /api/economy/bodiez/custom-days/ — the member's own named days."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = BodieZCustomDay.objects.filter(user=request.user)
        return Response({"custom_days": [_custom_day_dict(d) for d in rows], "max": MAX_CUSTOM_DAYS})

    def post(self, request):
        name = " ".join(str(request.data.get("name") or "").split())[:30]
        if not name:
            return Response({"detail": "A day needs a name."}, status=status.HTTP_400_BAD_REQUEST)
        mine = BodieZCustomDay.objects.filter(user=request.user)
        if mine.count() >= MAX_CUSTOM_DAYS:
            return Response({"detail": f"You can keep {MAX_CUSTOM_DAYS} custom days. Delete one to add another."},
                            status=status.HTTP_400_BAD_REQUEST)
        if mine.filter(name__iexact=name).exists():
            return Response({"detail": f"You already have a day called {name}."},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(_custom_day_dict(BodieZCustomDay.objects.create(user=request.user, name=name)),
                        status=status.HTTP_201_CREATED)


class BodieZCustomDayDetailView(APIView):
    """DELETE /api/economy/bodiez/custom-days/{id}/ — routines on that day
    keep everything and simply lose the tag."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, day_id):
        deleted, _ = BodieZCustomDay.objects.filter(id=day_id, user=request.user).delete()
        if not deleted:
            return Response({"detail": "Day not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BodieZRoutinesView(APIView):
    """GET/POST /api/economy/bodiez/routines/

    GET carries each routine's Coach rating out of 10, read off the member's own
    FINISHED sessions (see `routine_coach_ratings`). It is progress, not
    attendance, so it is None until a lift in the routine has two comparable
    sessions."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = list(BodieZRoutine.objects.filter(user=request.user))
        rated = routine_coach_ratings(request.user, rows)
        out = []
        for r in rows:
            d = _routine_dict(r)
            d.update(rated[r.id])
            out.append(d)
        return Response({"routines": out, "rating_caveat": RATING_CAVEAT})

    def post(self, request):
        # Cut to the column: SQLite ignores varchar length and Postgres does
        # not, so an over-long title passed every test and 500'd in production.
        title = str(request.data.get("title") or "").strip()[:80]
        if not title:
            return Response({"detail": "Routine needs a title."}, status=status.HTTP_400_BAD_REQUEST)
        exercises = request.data.get("exercises")
        if not isinstance(exercises, list):
            exercises = []
        # Validate every exercise id up front rather than storing a routine
        # that silently 404s a card the moment somebody starts a session
        # from it.
        ids = [e.get("exercise_id") for e in exercises if isinstance(e, dict) and e.get("exercise_id")]
        valid_ids = set(BodieZExercise.objects.visible(request.user).filter(id__in=ids).values_list("id", flat=True))
        bad = [i for i in ids if i not in valid_ids]
        if bad:
            return Response({"detail": f"Unknown exercise id(s): {bad}"}, status=status.HTTP_400_BAD_REQUEST)
        bucket = request.data.get("bucket")
        bucket = bucket if bucket in _BUCKET_KEYS else "inbox"
        day_tag = request.data.get("day_tag")
        day_tag = day_tag if day_tag in _DAY_TAG_KEYS else ""
        custom_day = _own_custom_day(request.user, request.data.get("custom_day_id"))
        if custom_day == "bad":
            return Response({"detail": "That day isn't one of yours."}, status=status.HTTP_400_BAD_REQUEST)
        if custom_day:
            day_tag = ""
        description = str(request.data.get("description") or "").strip()[:200]
        goal = request.data.get("goal") or ""
        if goal and goal not in GOALS:
            return Response({"detail": f"goal must be one of {sorted(GOALS)}, or blank."},
                            status=status.HTTP_400_BAD_REQUEST)
        # Only the two a client can honestly claim: it built this by hand, or
        # one of the Coach builders did. "session" and "trial" are set by the
        # server paths that actually do those things.
        source = request.data.get("source")
        source = source if source in CLIENT_SOURCES else "member"
        routine = BodieZRoutine.objects.create(user=request.user, title=title, exercises=exercises,
                                                bucket=bucket, day_tag=day_tag, description=description,
                                                goal=goal, custom_day=custom_day or None, source=source)
        return Response(_routine_dict(routine), status=status.HTTP_201_CREATED)


CLIENT_SOURCES = {"member", "coach"}


class BodieZRoutineCopyView(APIView):
    """POST /api/economy/bodiez/routines/{id}/copy/ — a new routine that starts
    as a copy of this one, so a member can change it without losing the one
    they already run. The copy is theirs ("member"), whoever built the
    original: from here on they are the one editing it."""
    permission_classes = [IsAuthenticated]

    def post(self, request, routine_id):
        src = BodieZRoutine.objects.filter(id=routine_id, user=request.user).first()
        if src is None:
            return Response({"detail": "Routine not found."}, status=status.HTTP_404_NOT_FOUND)
        title = str(request.data.get("title") or f"{src.title} (copy)").strip()[:80]
        r = BodieZRoutine.objects.create(
            user=request.user, title=title, description=src.description,
            exercises=[dict(e) for e in (src.exercises or []) if isinstance(e, dict)],
            bucket="inbox", day_tag=src.day_tag, custom_day=src.custom_day, goal=src.goal, source="member")
        return Response(_routine_dict(r), status=status.HTTP_201_CREATED)


SHARE_SALT = "bodiez.routine.share"
SHARE_DAYS = 30


class BodieZRoutineShareView(APIView):
    """POST /api/economy/bodiez/routines/{id}/share/ — a code another member can
    paste to get their own copy. It is a signed, expiring token naming ONE
    routine (no table, nothing to clean up); it grants a read of that routine and
    nothing else, and the owner changing or deleting it later changes or ends what
    the code gives. Free at every tier: sharing a plan is not a resource move."""
    permission_classes = [IsAuthenticated]

    def post(self, request, routine_id):
        from django.core import signing
        r = BodieZRoutine.objects.filter(id=routine_id, user=request.user).first()
        if r is None:
            return Response({"detail": "Routine not found."}, status=status.HTTP_404_NOT_FOUND)
        code = signing.dumps({"r": r.id}, salt=SHARE_SALT)
        return Response({"code": code, "expires_in_days": SHARE_DAYS, "title": r.title})


class BodieZRoutineRedeemView(APIView):
    """POST /api/economy/bodiez/routines/redeem/ {code} — copy a shared routine
    into the caller's own list as theirs. Only LIBRARY exercises travel: another
    member's custom lifts are private to them, so they are left out and the count
    is said rather than silently shrinking the routine."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.core import signing
        code = str((request.data or {}).get("code") or "").strip()
        try:
            data = signing.loads(code, salt=SHARE_SALT, max_age=SHARE_DAYS * 86400)
        except signing.BadSignature:
            return Response({"detail": "That code isn't valid, or it expired. Ask for a new one."},
                            status=status.HTTP_400_BAD_REQUEST)
        src = BodieZRoutine.objects.filter(id=data.get("r")).first()
        if src is None:
            return Response({"detail": "The member who shared this has since deleted it."},
                            status=status.HTTP_404_NOT_FOUND)
        rows = [e for e in (src.exercises or []) if isinstance(e, dict)]
        ok = set(BodieZExercise.objects.library().filter(
            id__in=[e.get("exercise_id") for e in rows if isinstance(e.get("exercise_id"), int)]
        ).values_list("id", flat=True))
        kept = [dict(e) for e in rows if e.get("exercise_id") in ok]
        for i, e in enumerate(kept):
            e["order"] = i
        r = BodieZRoutine.objects.create(
            user=request.user, title=src.title[:80], description=src.description, exercises=kept,
            bucket="inbox", goal=src.goal, source="member")
        out = _routine_dict(r)
        out["left_out"] = len(rows) - len(kept)
        return Response(out, status=status.HTTP_201_CREATED)


# The trial's "Build a week" flow computes the split client-side — the same
# pure `pickForDay` lookup the real app's SplitBuilder already runs, no AI,
# no server round trip, so a stranger can preview all 1-6 days for free
# before an account exists to save anything to. What they built has nowhere
# to live until they register, so `RegisterSerializer.create` calls this with
# whatever the client sent in `trial_split` — untrusted input from someone
# who was never authenticated, so it is cleaned here rather than trusted,
# following the same shape `BodieZRoutinesView.post` already validates a
# single routine with. Best-effort and silent on anything malformed: a bad
# trial split must never be the reason a registration fails, same rule
# `claim_trial_take` already holds itself to for a stale token.
MAX_TRIAL_SPLIT_DAYS = 6
MAX_TRIAL_SPLIT_EXERCISES_PER_DAY = 12


def clean_trial_split(raw):
    """Untrusted client JSON -> a validated list of day dicts, or []."""
    if not isinstance(raw, list) or not raw:
        return []
    days = raw[:MAX_TRIAL_SPLIT_DAYS]

    all_ids = set()
    for day in days:
        if not isinstance(day, dict):
            continue
        for e in (day.get("exercises") or [])[:MAX_TRIAL_SPLIT_EXERCISES_PER_DAY]:
            if isinstance(e, dict) and e.get("exercise_id"):
                all_ids.add(e["exercise_id"])
    valid_ids = set(BodieZExercise.objects.library().filter(id__in=all_ids).values_list("id", flat=True))

    cleaned = []
    for day in days:
        if not isinstance(day, dict):
            continue
        title = str(day.get("title") or "").strip()[:120]
        if not title:
            continue
        exercises = []
        for i, e in enumerate((day.get("exercises") or [])[:MAX_TRIAL_SPLIT_EXERCISES_PER_DAY]):
            if not isinstance(e, dict) or e.get("exercise_id") not in valid_ids:
                continue
            try:
                sets = max(1, min(10, int(e.get("sets") or 3)))
                reps = max(1, min(100, int(e.get("reps") or 10)))
            except (TypeError, ValueError):
                sets, reps = 3, 10
            weight_kg = e.get("weight_kg")
            try:
                weight_kg = float(weight_kg) if weight_kg not in (None, "") else None
            except (TypeError, ValueError):
                weight_kg = None
            exercises.append({"exercise_id": e["exercise_id"], "order": i,
                               "sets": sets, "reps": reps, "weight_kg": weight_kg})
        if exercises:
            cleaned.append({"title": title, "exercises": exercises})
    return cleaned


def create_trial_split_routines(user, days):
    """One real BodieZRoutine per day, in Inbox — `days` already cleaned by
    `clean_trial_split`. Mirrors `BodieZRoutinesView.post` one call at a time
    rather than a bulk-insert, because the per-routine defaults (bucket,
    ordering) live there and a second copy of that logic is how the two
    quietly disagree within a year."""
    for day in days:
        BodieZRoutine.objects.create(user=user, title=day["title"],
                                      exercises=day["exercises"], bucket="inbox", source="trial")


class BodieZRoutineDetailView(APIView):
    """PATCH/DELETE /api/economy/bodiez/routines/{id}/"""
    permission_classes = [IsAuthenticated]

    def _get(self, request, routine_id):
        try:
            return BodieZRoutine.objects.get(id=routine_id, user=request.user)
        except BodieZRoutine.DoesNotExist:
            return None

    def patch(self, request, routine_id):
        routine = self._get(request, routine_id)
        if not routine:
            return Response({"detail": "Routine not found."}, status=status.HTTP_404_NOT_FOUND)
        title = request.data.get("title")
        if title is not None:
            title = str(title).strip()[:80]
            if not title:
                return Response({"detail": "Routine needs a title."}, status=status.HTTP_400_BAD_REQUEST)
            routine.title = title
        exercises = request.data.get("exercises")
        if exercises is not None:
            if not isinstance(exercises, list):
                return Response({"detail": "exercises must be a list."}, status=status.HTTP_400_BAD_REQUEST)
            ids = [e.get("exercise_id") for e in exercises if isinstance(e, dict) and e.get("exercise_id")]
            valid_ids = set(BodieZExercise.objects.visible(request.user).filter(id__in=ids).values_list("id", flat=True))
            bad = [i for i in ids if i not in valid_ids]
            if bad:
                return Response({"detail": f"Unknown exercise id(s): {bad}"}, status=status.HTTP_400_BAD_REQUEST)
            routine.exercises = exercises
        if "bucket" in request.data:
            bucket = request.data.get("bucket")
            if bucket not in _BUCKET_KEYS:
                return Response({"detail": f"bucket must be one of {sorted(_BUCKET_KEYS)}."},
                                 status=status.HTTP_400_BAD_REQUEST)
            routine.bucket = bucket
        if "day_tag" in request.data:
            day_tag = request.data.get("day_tag") or ""
            if day_tag not in _DAY_TAG_KEYS and day_tag != "":
                return Response({"detail": f"day_tag must be one of {sorted(_DAY_TAG_KEYS)}, or blank."},
                                 status=status.HTTP_400_BAD_REQUEST)
            routine.day_tag = day_tag
            if day_tag:
                routine.custom_day = None
        if "custom_day_id" in request.data:
            custom_day = _own_custom_day(request.user, request.data.get("custom_day_id"))
            if custom_day == "bad":
                return Response({"detail": "That day isn't one of yours."}, status=status.HTTP_400_BAD_REQUEST)
            routine.custom_day = custom_day or None
            if custom_day:
                routine.day_tag = ""
        if "goal" in request.data:
            goal = request.data.get("goal") or ""
            if goal and goal not in GOALS:
                return Response({"detail": f"goal must be one of {sorted(GOALS)}, or blank."},
                                status=status.HTTP_400_BAD_REQUEST)
            routine.goal = goal
        if "description" in request.data:
            routine.description = str(request.data.get("description") or "").strip()[:200]
        if "scheduled_for" in request.data:
            raw = request.data.get("scheduled_for")
            if not raw:
                routine.scheduled_for = None
            else:
                try:
                    routine.scheduled_for = date.fromisoformat(str(raw)[:10])
                except ValueError:
                    return Response({"detail": "scheduled_for must be YYYY-MM-DD."},
                                     status=status.HTTP_400_BAD_REQUEST)
        routine.save()
        return Response(_routine_dict(routine))

    def delete(self, request, routine_id):
        routine = self._get(request, routine_id)
        if not routine:
            return Response({"detail": "Routine not found."}, status=status.HTTP_404_NOT_FOUND)
        routine.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BodieZBoardView(APIView):
    """GET /api/economy/bodiez/board/ — every routine, grouped by bucket.

    One request for the whole scheduler, the same shape
    `lilith_taskz.LilithBoardView` answers for tasks: a screen with five tabs
    built from five round trips is a screen that flickers on every open.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = BodieZRoutine.objects.filter(user=request.user)
        buckets = {k: [] for k, _ in BODIEZ_BUCKETS}
        for r in rows:
            buckets[r.bucket].append(_routine_dict(r))
        return Response({
            "buckets": buckets,
            # Labels come from the server for the same reason Lilith's do —
            # a client that split BODIEZ_BUCKETS itself would be the second
            # place the emoji and wording live, and the two drift within a
            # year the way every retyped tier number in this app has.
            "bucket_labels": [{"key": k, "label": v} for k, v in BODIEZ_BUCKETS],
            # Same reasoning as bucket_labels — a client that split
            # BODIEZ_DAY_TAGS itself would be the second place the order and
            # wording live.
            "day_tag_labels": [{"key": k, "label": v} for k, v in BODIEZ_DAY_TAGS],
            "custom_days": [_custom_day_dict(d) for d in BodieZCustomDay.objects.filter(user=request.user)],
        })


class BodieZSessionsView(APIView):
    """GET/POST /api/economy/bodiez/sessions/ — list past sessions, or start
    a new one (POST with no body starts an ad-hoc session; {routine_id}
    starts one against a saved routine)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = BodieZSession.objects.filter(user=request.user).select_related("routine").prefetch_related("sets__exercise")[:50]
        return Response({"sessions": [_session_dict(s) for s in rows]})

    def post(self, request):
        routine_id = request.data.get("routine_id")
        routine = None
        if routine_id:
            try:
                routine = BodieZRoutine.objects.get(id=routine_id, user=request.user)
            except BodieZRoutine.DoesNotExist:
                return Response({"detail": "Routine not found."}, status=status.HTTP_404_NOT_FOUND)
        # One open session at a time — starting a second one while the first
        # is still running is almost always a lost tab, not two workouts.
        if BodieZSession.objects.filter(user=request.user, ended_at__isnull=True).exists():
            return Response({"detail": "You already have a session in progress."},
                             status=status.HTTP_409_CONFLICT)
        sess = BodieZSession.objects.create(user=request.user, routine=routine)
        return Response(_session_dict(sess), status=status.HTTP_201_CREATED)


def session_summary(sess):
    """What a finished session added up to, and what it beat.

    Every number is a count or a sum of logged sets. A record is only a record
    against the member's own EARLIER finished sessions: an exercise done for
    the first time is listed under `firsts`, never called a record, because
    beating nothing is not beating anything.
    """
    sets = list(sess.sets.select_related("exercise"))
    vol = lambda ss: sum(float(x.weight_kg) * x.reps for x in ss if x.weight_kg is not None)
    by_ex = defaultdict(list)
    for x in sets:
        by_ex[_lane(x)].append(x)

    prior = BodieZSet.objects.filter(
        session__user=sess.user, session__ended_at__isnull=False,
        session__started_at__lt=sess.started_at).exclude(session=sess)
    prior_by_ex = defaultdict(list)
    for x in prior.filter(exercise_id__in={k[0] for k in by_ex}):
        prior_by_ex[_lane(x)].append(x)

    exercises, records, firsts = [], [], []
    for (ex_id, side), ss in by_ex.items():
        name = _lane_name(ss[0].exercise.name, side)
        weights = [float(x.weight_kg) for x in ss if x.weight_kg is not None]
        exercises.append({"exercise_id": ex_id, "one_sided": side, "name": name, "sets": len(ss),
                          "reps": sum(x.reps for x in ss), "volume_kg": round(vol(ss), 2),
                          "top_weight_kg": max(weights) if weights else None})
        old = prior_by_ex.get((ex_id, side), [])
        if not old:
            firsts.append(name)
            continue
        old_w = [float(x.weight_kg) for x in old if x.weight_kg is not None]
        if weights and old_w and max(weights) > max(old_w):
            records.append({"kind": "heaviest", "exercise": name,
                            "value_kg": max(weights), "previous_kg": max(old_w)})
        # Most reps at one exact weight (or bodyweight) — more reps at a lighter
        # load than you've used before is not a record, so it is not compared.
        for w in {x.weight_kg for x in ss}:
            now_best = max(x.reps for x in ss if x.weight_kg == w)
            then = [x.reps for x in old if x.weight_kg == w]
            if then and now_best > max(then):
                records.append({"kind": "reps", "exercise": name, "reps": now_best,
                                "previous_reps": max(then),
                                "weight_kg": float(w) if w is not None else None})

    total = vol(sets)
    past = defaultdict(float)
    for x in prior.exclude(weight_kg__isnull=True):
        past[x.session_id] += float(x.weight_kg) * x.reps
    if total and past and total > max(past.values()):
        records.append({"kind": "session_volume", "value_kg": round(total, 2),
                        "previous_kg": round(max(past.values()), 2)})

    end = sess.ended_at or timezone.now()
    coaches = list(StudentRelationship.objects.filter(student=sess.user)
                   .values_list("coach__username", flat=True))
    return {
        "session_id": sess.id,
        "routine_title": sess.routine.title if sess.routine_id and sess.routine else None,
        "started_at": sess.started_at.isoformat(),
        "ended_at": sess.ended_at.isoformat() if sess.ended_at else None,
        "backfilled": sess.backfilled,
        # A workout typed in afterwards has no measured length; None, never 0.
        "duration_seconds": None if sess.backfilled else int((end - sess.started_at).total_seconds()),
        "sets": len(sets), "reps": sum(x.reps for x in sets),
        "volume_kg": round(total, 2),
        "exercises": sorted(exercises, key=lambda e: e["name"]),
        "records": records, "firsts": sorted(firsts),
        "coaches": coaches,
    }


class BodieZSessionSummaryView(APIView):
    """GET /api/economy/bodiez/sessions/{id}/summary/ — totals and records."""
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        try:
            sess = BodieZSession.objects.get(id=session_id, user=request.user)
        except BodieZSession.DoesNotExist:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(session_summary(sess))


# Which Sentence ConnectZ kinds a workout can become. Not the whole list:
# resume/cover_letter/bio are NO_INVENTION documents about a person's whole
# history, and essay/contract/royalties/the lyric fixers answer a different
# question entirely. A workout is one session — a poem, a lyric, a caption or
# a post are the kinds that are actually about ONE thing that just happened.
WORKOUT_WRITE_KINDS = ("poem", "lyrics", "caption", "post")


def workout_topic(summary, label=""):
    """The brief for "write about this workout" — assembled HERE, from
    `session_summary`'s own numbers, never from anything a client sends. Same
    shape as `takescorez.promo_topic`: a finished session is a settled record
    (logged sets, nothing typed into this request), so writing from anything
    else would risk a poem about a PR that was never actually hit.
    """
    facts = []
    if summary.get("routine_title"):
        facts.append(f"Routine: {summary['routine_title']}")
    if summary.get("duration_seconds"):
        facts.append(f"Duration: {summary['duration_seconds'] // 60} minutes")
    exs = summary.get("exercises") or []
    if exs:
        facts.append("Exercises and what was done: " + "; ".join(
            f"{e['name']} — {e['sets']} sets, {e['reps']} reps"
            + (f" at up to {e['top_weight_kg']}kg" if e.get("top_weight_kg") else "")
            for e in exs[:8]))
    if summary.get("volume_kg"):
        facts.append(f"Total volume moved: {summary['volume_kg']}kg")
    for r in summary.get("records") or []:
        if r["kind"] == "heaviest":
            facts.append(f"Personal record: heaviest {r['exercise']} ever at {r['value_kg']}kg "
                        f"(previous best {r['previous_kg']}kg)")
        elif r["kind"] == "reps":
            facts.append(f"Personal record: most reps on {r['exercise']} at "
                        f"{r.get('weight_kg') or 'bodyweight'} — {r['reps']} (previous best {r['previous_reps']})")
        elif r["kind"] == "session_volume":
            facts.append(f"Personal record: most total weight moved in one session, "
                        f"{r['value_kg']}kg (previous best {r['previous_kg']}kg)")
    for name in summary.get("firsts") or []:
        facts.append(f"First time logging {name}")
    if not facts:
        facts.append("A logged workout, with no sets recorded yet.")
    rules = ["Write about THIS workout, in the first person, from the facts above only.",
             "Do not invent an exercise, a weight, a rep count or a record that is not listed.",
             "This is about training — a gym session, not a music performance."]
    return "\n".join(["Facts:", *[f"- {f}" for f in facts], "", "Rules:", *[f"- {x}" for x in rules]])


class BodieZSessionWriteView(APIView):
    """/api/economy/bodiez/sessions/<id>/write/ — write about a finished workout.

    GET says the price and the kinds on offer, before anything is spent. POST
    writes it through Sentence ConnectZ's own writer — same price, same daily
    allowance, same "a failed run is not charged" as every other door into it
    — from a brief built out of the session's own logged sets, never from
    anything the request sends. An in-progress session has no door here: its
    summary is not settled yet, so there is nothing true to write from.
    """
    permission_classes = [IsAuthenticated]

    def _session(self, request, session_id):
        return BodieZSession.objects.filter(
            id=session_id, user=request.user, ended_at__isnull=False).first()

    def get(self, request, session_id):
        sess = self._session(request, session_id)
        if not sess:
            return Response({"detail": "Session not found, or still in progress."},
                            status=status.HTTP_404_NOT_FOUND)
        from .crosspost import coach_price
        price = coach_price(request.user)
        from .sentencez import KINDS
        kinds = [{"key": k, "label": KINDS[k]["label"], "emoji": KINDS[k]["emoji"]}
                for k in WORKOUT_WRITE_KINDS]
        return Response({"cost": {"resource": "promptz", "amount": price["amount"],
                                  "free_today": price["free_today"]}, "kinds": kinds})

    def post(self, request, session_id):
        sess = self._session(request, session_id)
        if not sess:
            return Response({"detail": "Session not found, or still in progress."},
                            status=status.HTTP_404_NOT_FOUND)
        kind = str((request.data or {}).get("kind") or "poem")
        if kind not in WORKOUT_WRITE_KINDS:
            kind = "poem"
        from .sentencez import clean_hashtags, write_piece
        summary = session_summary(sess)
        topic = workout_topic(summary)
        title = summary.get("routine_title") or "ad-hoc"
        return write_piece(request.user, kind, topic,
                           hashtags=clean_hashtags((request.data or {}).get("hashtags")),
                           spend_note=f"Sentence ConnectZ — about a BodieZ workout ({title})",
                           extra_inputs={"bodiez_session": sess.pk})


MAX_PAST_SETS = 100
MAX_PAST_DAYS = 365 * 5


def clean_set_rows(user, raw):
    """Untrusted set rows -> ([(id|None, exercise, reps, weight, side)], None)
    or ([], "the sentence saying which set and why").

    The ONE validator for a list of sets typed in rather than logged live —
    a past workout and an edit of a logged one both come through here, so the
    two can never disagree about what a set may be. All or nothing: the first
    bad row refuses the lot, and the message names it.
    """
    ids = {r.get("exercise_id") for r in raw if isinstance(r, dict)}
    try:
        exercises = {e.id: e for e in BodieZExercise.objects.visible(user).filter(id__in=ids)}
    except (ValueError, TypeError):
        exercises = {}
    clean = []
    for i, r in enumerate(raw, 1):
        if not isinstance(r, dict) or r.get("exercise_id") not in exercises:
            return [], f"Set {i}: unknown exercise."
        try:
            reps = int(r.get("reps"))
        except (TypeError, ValueError):
            return [], f"Set {i}: reps must be a number."
        if not 1 <= reps <= MAX_REPS_PER_SET:
            return [], f"Set {i}: reps must be 1 to {MAX_REPS_PER_SET}."
        weight = r.get("weight_kg")
        if weight in (None, ""):
            weight = None
        else:
            try:
                weight = Decimal(str(weight))
            except Exception:
                return [], f"Set {i}: weight must be a number."
            if weight < 0 or weight >= 10000:
                return [], f"Set {i}: weight is out of range."
        side = _clean_side(r.get("one_sided"))
        if side is None:
            return [], f"Set {i}: one_sided must be blank, arm or leg."
        set_id = r.get("id")
        set_id = set_id if isinstance(set_id, int) and not isinstance(set_id, bool) else None
        clean.append((set_id, exercises[r["exercise_id"]], reps, weight, side))
    return clean, None


class BodieZPastSessionView(APIView):
    """POST /api/economy/bodiez/sessions/past/ — log a workout you already did.

    {date: "YYYY-MM-DD", routine_id?, notes?, sets: [{exercise_id, reps, weight_kg?}, ...]}

    It lands as a FINISHED session on that date, so it feeds records, the body
    map, goals and the coach exactly as a live one does — and is flagged
    `backfilled`, because the things a live session has measured by the server
    (rest between sets, how long it took) are not known and are not invented.
    Sets are validated by the same rules as the live logger, and nothing is
    saved unless every one passes.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            day = date.fromisoformat(str(request.data.get("date"))[:10])
        except ValueError:
            return Response({"detail": "date must be YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)
        today = timezone.localdate()
        if day > today:
            return Response({"detail": "That date is in the future — log it once you've done it."},
                            status=status.HTTP_400_BAD_REQUEST)
        if (today - day).days > MAX_PAST_DAYS:
            return Response({"detail": "That's more than five years back."}, status=status.HTTP_400_BAD_REQUEST)

        # Optional: the routine this was, so the workout carries its name and
        # the member's own history reads "Push day" rather than "Ad-hoc".
        routine = None
        if request.data.get("routine_id"):
            routine = BodieZRoutine.objects.filter(id=request.data.get("routine_id"), user=request.user).first() \
                if str(request.data.get("routine_id")).isdigit() else None
            if routine is None:
                return Response({"detail": "Routine not found."}, status=status.HTTP_404_NOT_FOUND)

        raw = request.data.get("sets")
        if not isinstance(raw, list) or not raw:
            return Response({"detail": "Add at least one set."}, status=status.HTTP_400_BAD_REQUEST)
        if len(raw) > MAX_PAST_SETS:
            return Response({"detail": f"At most {MAX_PAST_SETS} sets in one workout."},
                            status=status.HTTP_400_BAD_REQUEST)

        clean, problem = clean_set_rows(request.user, raw)
        if problem:
            return Response({"detail": problem}, status=status.HTTP_400_BAD_REQUEST)

        # Today: now. Any other day: noon, so the date survives a timezone.
        when = (timezone.now() if day == today else
                timezone.make_aware(datetime.combine(day, datetime.min.time().replace(hour=12))))
        sess = BodieZSession.objects.create(user=request.user, ended_at=when, backfilled=True, routine=routine,
                                            notes=str(request.data.get("notes") or "")[:2000])
        # started_at is auto_now_add; set the real date after create.
        BodieZSession.objects.filter(id=sess.id).update(started_at=when)
        sess.refresh_from_db()
        counts = defaultdict(int)
        for pos, (_id, ex, reps, weight, side) in enumerate(clean, 1):
            counts[ex.id] += 1
            BodieZSet.objects.create(session=sess, exercise=ex, set_number=counts[ex.id], position=pos,
                                     reps=reps, weight_kg=weight, rest_seconds=None, one_sided=side)
        out = _session_dict(sess)
        out["summary"] = session_summary(sess)
        return Response(out, status=status.HTTP_201_CREATED)


class BodieZSessionDetailView(APIView):
    """PATCH /api/economy/bodiez/sessions/{id}/ — finish a session, or edit a
    finished one's notes and (for one typed in afterwards) its date.
    DELETE removes a workout and its sets."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, session_id):
        deleted, _ = BodieZSession.objects.filter(id=session_id, user=request.user).delete()
        if not deleted:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def patch(self, request, session_id):
        try:
            sess = BodieZSession.objects.get(id=session_id, user=request.user)
        except BodieZSession.DoesNotExist:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        if request.data.get("date"):
            # Only a workout typed in afterwards has a date the member chose.
            # A live one's start and end were measured by the server, and
            # moving them would make its duration and rest times lie.
            if not sess.backfilled:
                return Response({"detail": "A workout logged live keeps the time it happened."},
                                status=status.HTTP_400_BAD_REQUEST)
            try:
                day = date.fromisoformat(str(request.data.get("date"))[:10])
            except ValueError:
                return Response({"detail": "date must be YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)
            today = timezone.localdate()
            if day > today:
                return Response({"detail": "That date is in the future."}, status=status.HTTP_400_BAD_REQUEST)
            if (today - day).days > MAX_PAST_DAYS:
                return Response({"detail": "That's more than five years back."}, status=status.HTTP_400_BAD_REQUEST)
            if day != timezone.localtime(sess.started_at).date():
                when = timezone.make_aware(datetime.combine(day, datetime.min.time().replace(hour=12)))
                BodieZSession.objects.filter(id=sess.id).update(started_at=when, ended_at=when)
                sess.refresh_from_db()
        if request.data.get("finish"):
            if sess.ended_at:
                return Response({"detail": "Session already finished."}, status=status.HTTP_400_BAD_REQUEST)
            sess.ended_at = timezone.now()
        notes = request.data.get("notes")
        if notes is not None:
            sess.notes = notes
        sess.save()
        out = _session_dict(sess)
        if sess.ended_at:
            out["summary"] = session_summary(sess)
        return Response(out)


def routine_from_session(sess):
    """A logged workout -> routine rows: one per lift, in the order it was
    first done, with the number of sets done and the TOP set's weight and
    reps as the target. The top set, not an average: the routine is what you
    did, and an average of a warm-up and a working set is a set nobody did."""
    by_ex = {}
    for x in sess.sets.order_by("id"):
        by_ex.setdefault(x.exercise_id, []).append(x)
    rows = []
    for i, (ex_id, ss) in enumerate(by_ex.items()):
        top = max(ss, key=lambda x: (x.weight_kg if x.weight_kg is not None else Decimal(-1), x.reps))
        rows.append({"exercise_id": ex_id, "order": i, "sets": len(ss), "reps": top.reps,
                     "weight_kg": float(top.weight_kg) if top.weight_kg is not None else None})
    return rows


class BodieZSessionRoutineView(APIView):
    """POST /api/economy/bodiez/sessions/{id}/routine/ — save a logged
    workout as a new routine. The workout is untouched; the routine is a new
    row in Inbox that the designer edits like any other."""
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        sess = BodieZSession.objects.filter(id=session_id, user=request.user).select_related("routine").first()
        if sess is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        rows = routine_from_session(sess)
        if not rows:
            return Response({"detail": "That workout has no sets to build a routine from."},
                            status=status.HTTP_400_BAD_REQUEST)
        day = timezone.localtime(sess.started_at).date().isoformat()
        base = sess.routine.title if sess.routine_id and sess.routine else "Workout"
        title = str(request.data.get("title") or f"{base} — {day}").strip()[:80]
        r = BodieZRoutine.objects.create(
            user=request.user, title=title, exercises=rows, bucket="inbox", source="session",
            goal=sess.routine.goal if sess.routine_id and sess.routine else "",
            description=f"Built from your workout on {day}."[:200])
        return Response(_routine_dict(r), status=status.HTTP_201_CREATED)


class BodieZSetOrderView(APIView):
    """POST /api/economy/bodiez/sessions/{id}/order/ {ids: [...]} — put the sets in this
    order. Live or finished: dragging a set is a display order, not a rewrite, so it
    changes nothing that was measured (rest, time, weight). `ids` must be exactly this
    session's sets, each once, or nothing moves."""
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        sess = BodieZSession.objects.filter(id=session_id, user=request.user).first()
        if not sess:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        ids = request.data.get("ids")
        rows = {x.id: x for x in sess.sets.all()}
        if (not isinstance(ids, list) or len(ids) != len(rows)
                or any(not isinstance(i, int) or isinstance(i, bool) for i in ids)
                or set(ids) != set(rows)):
            return Response({"detail": "Send every set of this workout, once each."},
                            status=status.HTTP_400_BAD_REQUEST)
        counts = defaultdict(int)
        with transaction.atomic():
            for pos, i in enumerate(ids, 1):
                row = rows[i]
                counts[row.exercise_id] += 1
                row.position, row.set_number = pos, counts[row.exercise_id]
                row.save(update_fields=["position", "set_number"])
        return Response(_session_dict(sess))


class BodieZSetsView(APIView):
    """POST /api/economy/bodiez/sessions/{id}/sets/ — log one set.
    PUT replaces every set of a FINISHED session — the edit of a workout
    already logged."""
    permission_classes = [IsAuthenticated]

    def put(self, request, session_id):
        try:
            sess = BodieZSession.objects.get(id=session_id, user=request.user)
        except BodieZSession.DoesNotExist:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        # A live session is edited by logging; rewriting it underneath the
        # logger would break the rest timer's "since the last set".
        if not sess.ended_at:
            return Response({"detail": "Finish this session before editing its sets."},
                            status=status.HTTP_400_BAD_REQUEST)
        raw = request.data.get("sets")
        if not isinstance(raw, list) or not raw:
            return Response({"detail": "A workout needs at least one set — delete the workout instead."},
                            status=status.HTTP_400_BAD_REQUEST)
        if len(raw) > MAX_PAST_SETS:
            return Response({"detail": f"At most {MAX_PAST_SETS} sets in one workout."},
                            status=status.HTTP_400_BAD_REQUEST)
        clean, problem = clean_set_rows(request.user, raw)
        if problem:
            return Response({"detail": problem}, status=status.HTTP_400_BAD_REQUEST)

        existing = {x.id: x for x in sess.sets.all()}
        counts = defaultdict(int)
        with transaction.atomic():
            kept = set()
            for pos, (set_id, ex, reps, weight, side) in enumerate(clean, 1):
                counts[ex.id] += 1
                row = existing.get(set_id)
                if row is None or set_id in kept:
                    BodieZSet.objects.create(session=sess, exercise=ex, set_number=counts[ex.id], position=pos,
                                             reps=reps, weight_kg=weight, rest_seconds=None, one_sided=side,
                                             converted_from_lb=True)
                    continue
                kept.add(set_id)
                # A kept set keeps its measured rest — that was real — unless
                # it is now a different lift, when the rest belonged to
                # something else. converted_from_lb: whatever weight is here
                # now was typed in the member's current unit, so the pounds
                # fix must never convert it again.
                if row.exercise_id != ex.id:
                    row.rest_seconds = None
                row.exercise, row.set_number, row.reps, row.position = ex, counts[ex.id], reps, pos
                row.weight_kg, row.one_sided, row.converted_from_lb = weight, side, True
                row.save(update_fields=["exercise", "set_number", "reps", "weight_kg", "one_sided",
                                        "rest_seconds", "converted_from_lb", "position"])
            BodieZSet.objects.filter(id__in=list(existing.keys() - kept)).delete()
        out = _session_dict(sess)
        out["summary"] = session_summary(sess)
        return Response(out)

    def post(self, request, session_id):
        try:
            sess = BodieZSession.objects.get(id=session_id, user=request.user)
        except BodieZSession.DoesNotExist:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        if sess.ended_at:
            return Response({"detail": "This session is already finished."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            exercise = BodieZExercise.objects.visible(request.user).get(id=request.data.get("exercise_id"))
        except (BodieZExercise.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "Unknown exercise."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            reps = int(request.data.get("reps"))
        except (TypeError, ValueError):
            return Response({"detail": "reps must be a number."}, status=status.HTTP_400_BAD_REQUEST)
        if reps <= 0:
            return Response({"detail": "reps must be positive."}, status=status.HTTP_400_BAD_REQUEST)
        if reps > MAX_REPS_PER_SET:
            return Response({"detail": f"reps can be at most {MAX_REPS_PER_SET} per set."},
                            status=status.HTTP_400_BAD_REQUEST)

        weight_kg = request.data.get("weight_kg")
        if weight_kg is not None:
            try:
                weight_kg = Decimal(str(weight_kg))
            except Exception:
                return Response({"detail": "weight_kg must be a number."}, status=status.HTTP_400_BAD_REQUEST)
            if weight_kg < 0:
                return Response({"detail": "weight_kg cannot be negative."}, status=status.HTTP_400_BAD_REQUEST)

        side = _clean_side(request.data.get("one_sided"))
        if side is None:
            return Response({"detail": "one_sided must be blank, arm or leg."}, status=status.HTTP_400_BAD_REQUEST)

        set_number = sess.sets.filter(exercise=exercise).count() + 1
        prev = sess.sets.order_by("-created_at").first()
        rest = int((timezone.now() - prev.created_at).total_seconds()) if prev else None
        # Last in the member's order: once any set was dragged, a new one with position 0
        # would sort to the top.
        last_pos = sess.sets.aggregate(m=Max("position"))["m"] or 0
        s = BodieZSet.objects.create(session=sess, exercise=exercise, set_number=set_number,
                                      position=last_pos + 1 if last_pos else 0,
                                      reps=reps, weight_kg=weight_kg, rest_seconds=rest, one_sided=side)
        return Response(_set_dict(s), status=status.HTTP_201_CREATED)


class BodieZProgressView(APIView):
    """GET /api/economy/bodiez/progress/ — counts and volume, never a
    fabricated rating. Total volume is reps x weight, summed across every
    logged set with a weight; bodyweight sets (weight_kg null) count toward
    session/set totals but not volume, because there is nothing honest to
    multiply reps by."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sessions = BodieZSession.objects.filter(user=request.user, ended_at__isnull=False)
        session_count = sessions.count()
        sets = BodieZSet.objects.filter(session__user=request.user, session__ended_at__isnull=False)
        set_count = sets.count()
        volume = Decimal("0")
        for s in sets.exclude(weight_kg__isnull=True):
            volume += s.weight_kg * s.reps
        return Response({
            "sessions_completed": session_count,
            "sets_logged": set_count,
            "total_volume_kg": float(volume),
        })


# --- Thorough rating: how THOROUGHLY a lift, routine or muscle has been trained --
#
# One 1-10 scale for all three, read off the member's own FINISHED sessions in
# the last THOROUGH_DAYS (28). Corey's call, replacing an earlier progress-only
# 10/6/3 that said whether a lift went up and nothing about how completely it
# was being trained. Three parts, each a plain comparison the member can check:
#
#   consistency  distinct days it was trained         vs THOROUGH_TARGET_DAYS   40%
#   volume       working sets a week, averaged        vs the target for it      35%
#   progress     latest session vs own earlier best   up 1 / held .67 / down .33  25%
#
# score = round(1 + 9 * weighted share), so one lone set is a 1-2 and "twice a
# week, enough sets, still improving" is a 10. Progress is left out and the
# other two re-weighted until a lift has two comparable sessions (it cannot be
# judged on one), so a new lift is not marked down for having no history.
#
# SUBSTANCE, said out loud: turning up and sets are effort, and this number now
# includes them. That is why the score is named "thorough" and the caveat says
# it is how completely something is trained, not how strong you are, and why
# the third part is still there: a muscle hit every day that goes nowhere cannot
# reach 10. `None` (never 0) when nothing was logged in the window.
THOROUGH_DAYS = 28
THOROUGH_TARGET_DAYS = 8          # twice a week, over the window
THOROUGH_LIFT_WEEKLY_SETS = 6     # one lift; a muscle uses the bodymap's own target
RATING_UP = 1.02
RATING_DOWN = 0.90
TREND_SHARE = {"up": 1.0, "held": 0.67, "down": 0.33}
RATING_CAVEAT = (
    "Thorough rating: how thoroughly this has been trained, 1 to 10, from your "
    "finished sessions in the last 28 days: how many days you trained it (40%), "
    "how many working sets a week (35%), and whether it is going up against "
    "your own earlier best (25%, once a lift has two sessions). It is not how "
    "strong you are next to anyone else, and one session cannot make a 10."
)


def thoroughness(days, weekly_sets, target_weekly_sets, trend=None):
    """The 1-10 score from its three parts. Pure; `trend` is up/held/down/None."""
    parts = [(min(1.0, days / THOROUGH_TARGET_DAYS), 0.40),
             (min(1.0, weekly_sets / target_weekly_sets), 0.35)]
    if trend in TREND_SHARE:
        parts.append((TREND_SHARE[trend], 0.25))
    share = sum(v * w for v, w in parts) / sum(w for _, w in parts)
    return max(1, min(10, round(1 + 9 * share)))


def _session_metric(sets):
    """(kind, value) for one exercise in one session, or None."""
    weighted = [s for s in sets if s.weight_kg is not None and s.weight_kg > 0]
    if weighted:
        return "est_1rm_kg", max(float(s.weight_kg) * (1 + s.reps / 30) for s in weighted)
    reps = [s.reps for s in sets if s.reps]
    return ("reps", float(max(reps))) if reps else None


def _trend_of(by_session):
    """up/held/down for one lift's sessions (ordered by session start), or None."""
    ordered = sorted(by_session.values(), key=lambda ss: ss[0].session.started_at)
    metrics = [m for m in (_session_metric(ss) for ss in ordered) if m]
    if len(metrics) < 2:
        return None, None, None
    kind, latest = metrics[-1]
    # Like with like: a session logged with weight and one without are not the
    # same measurement.
    earlier = [v for k, v in metrics[:-1] if k == kind]
    if not earlier or max(earlier) <= 0:
        return None, None, None
    before = max(earlier)
    ratio = latest / before
    trend = "up" if ratio >= RATING_UP else "down" if ratio < RATING_DOWN else "held"
    return trend, kind, (round(latest, 1), round(before, 1))


def _mean_trend(trends):
    """One trend word for several lifts' trends (or None if none had one)."""
    pts = [TREND_SHARE[t] for t in trends if t]
    if not pts:
        return None
    avg = sum(pts) / len(pts)
    return "up" if avg >= 0.84 else "held" if avg >= 0.5 else "down"


def lift_thoroughness(sets, now=None):
    """{exercise_id: {...}} for every lift logged in the window, from finished
    `BodieZSet` rows (exercise and session loaded). Sides of a one-arm/one-leg
    lift are rated as one lift for the routine, and listed apart in the muscle."""
    now = now or timezone.now()
    cutoff = now - timedelta(days=THOROUGH_DAYS)
    sets = list(sets)
    lanes = defaultdict(lambda: defaultdict(list))        # (exercise, side) -> session -> sets
    for st in sets:
        lanes[(st.exercise, st.one_sided)][st.session_id].append(st)
    out = {}
    for (exercise, side), by_session in lanes.items():
        recent = [x for ss in by_session.values() for x in ss if x.session.started_at >= cutoff]
        if not recent:
            continue
        days = len({timezone.localtime(x.session.started_at).date() for x in recent})
        weekly = len(recent) / (THOROUGH_DAYS / 7)
        trend, kind, nums = _trend_of(by_session)
        row = {"exercise_id": exercise.id, "one_sided": side,
               "exercise_name": _lane_name(exercise.name, side),
               "muscle_group": exercise.muscle_group,
               "rating": thoroughness(days, weekly, THOROUGH_LIFT_WEEKLY_SETS, trend),
               "days_trained": days, "sets_per_week": round(weekly, 1), "trend": trend}
        if nums:
            row.update({"metric": kind, "latest": nums[0], "earlier_best": nums[1]})
        out[(exercise.id, side)] = row
    return out


def muscle_coach_ratings(sets, now=None, target_weekly_sets=10):
    """{muscle_group: {"rating": int|None, "why": str, "exercises": [...]}}
    for an iterable of finished `BodieZSet` rows (exercise and session
    already loaded). `exercises` lists every lift of that muscle logged in the
    window, each with its own 1-10 `rating`."""
    now = now or timezone.now()
    cutoff = now - timedelta(days=THOROUGH_DAYS)
    sets = list(sets)
    lifts = lift_thoroughness(sets, now)
    recent_by_muscle = defaultdict(list)
    for st in sets:
        if st.session.started_at >= cutoff:
            recent_by_muscle[st.exercise.muscle_group].append(st)
    out = {}
    for muscle, recent in recent_by_muscle.items():
        rows = sorted((r for r in lifts.values() if r["muscle_group"] == muscle),
                      key=lambda r: r["exercise_name"])
        days = len({timezone.localtime(x.session.started_at).date() for x in recent})
        weekly = len(recent) / (THOROUGH_DAYS / 7)
        trend = _mean_trend(r["trend"] for r in rows)
        out[muscle] = {
            "rating": thoroughness(days, weekly, target_weekly_sets, trend),
            "exercises": rows,
            "why": (f"Thorough on {days} day{'s' if days != 1 else ''}, with {weekly:.1f} sets a week "
                    f"over the last {THOROUGH_DAYS} days"
                    + (f"; its lifts are {trend} against your own earlier best." if trend else ".")),
        }
    return out


def routine_coach_ratings(user, routines, now=None):
    """{routine_id: {"coach_rating", "coach_why", "coach_exercises"}}.

    A routine's rating is the mean of its lifts' thoroughness, and a lift in the
    routine that was NOT logged in the window counts as a 1 — so a routine you
    only half do is rated as half done, which is the point of rating a routine.
    None (never 0) when none of its lifts were logged in the window."""
    sets = (BodieZSet.objects.filter(session__user=user, session__ended_at__isnull=False)
            .select_related("exercise", "session"))
    per_lift = defaultdict(list)
    for r in lift_thoroughness(sets, now).values():
        per_lift[r["exercise_id"]].append(r["rating"])
    rating = {i: round(sum(v) / len(v)) for i, v in per_lift.items()}
    out = {}
    for r in routines:
        ids = []
        for e in (r.exercises or []):
            i = e.get("exercise_id") if isinstance(e, dict) else None
            if isinstance(i, int) and i not in ids:
                ids.append(i)
        done = [i for i in ids if i in rating]
        if not done:
            out[r.id] = {"coach_rating": None, "coach_exercises": [],
                         "coach_why": f"Not thorough yet — nothing from this routine logged in the last {THOROUGH_DAYS} days."}
            continue
        scores = [rating.get(i, 1) for i in ids]
        out[r.id] = {
            "coach_rating": max(1, min(10, round(sum(scores) / len(scores)))),
            "coach_exercises": [{"exercise_id": i, "rating": rating.get(i)} for i in ids],
            "coach_why": (f"Thorough on {len(done)} of {len(ids)} lift{'s' if len(ids) != 1 else ''} logged in the last "
                          f"{THOROUGH_DAYS} days; the rest count as 1."),
        }
    return out


class BodieZBodyMapView(APIView):
    """GET /api/economy/bodiez/bodymap/ — which muscles were trained
    recently, which are going stale, which are getting hit every session.

    Every number here comes off a logged, FINISHED session (`ended_at` not
    null) — the same rule `BodieZProgressView` already follows, and for the
    same reason: an in-progress session hasn't happened yet, and a routine's
    PLAN is not a fact about what was trained. "Leg day" on a saved routine
    doesn't move this screen until a set against a leg exercise is actually
    logged.

    Status is one of five words, each a plain comparison against real dates
    and counts — never a fabricated 0-100 "balance score", because a member
    could not check that number against anything and a number nobody can
    check is the substance rule's failure case:

    - `untrained` — nothing ever logged for this muscle group.
    - `undertrained` — last trained more than `STALE_DAYS` ago.
    - `overworked` — trained on `OVERWORKED_SESSION_DAYS`+ separate days in
      the trailing window — not sets, DAYS, so five sets in one session
      doesn't read the same as five separate sessions.
    - `recent` — trained within `RECENT_DAYS`.
    - `balanced` — trained inside the window, but neither of the above.

    `volume_score` (0-10) is the one number on this screen that looks like a
    score, and it earns the exception the docstring above just warned
    against by staying CHECKABLE: it's `sets_last_7d` divided by
    `TARGET_WEEKLY_SETS`, capped at 10 — a ratio a member can verify with the
    two numbers sitting right beside it, never a black box. `TARGET_WEEKLY_SETS`
    is the floor of the evidence-based weekly-volume range for muscle growth
    (Schoenfeld's own review, already cited in GOALS["muscle_gain"] above),
    so hitting the recommended MINIMUM reads as a full 10 rather than
    requiring the top of the range — the same "developing artist" calibration
    lesson `vocalcoach.py`'s `ScaleIsAnchoredTests` already learned: an anchor
    set at the ceiling tells everyone below it they're failing.
    """
    permission_classes = [IsAuthenticated]

    RECENT_DAYS = 3
    STALE_DAYS = 10
    WINDOW_DAYS = 7
    OVERWORKED_SESSION_DAYS = 4
    TARGET_WEEKLY_SETS = 10
    VOLUME_CITATION = ("Schoenfeld, B. J., Ogborn, D., & Krieger, J. W. (2017). "
                        "Dose-response relationship between weekly resistance "
                        "training volume and increases in muscle mass: A "
                        "systematic review and meta-analysis. Journal of Sports "
                        "Sciences, 35(11), 1073-1082.")

    def get(self, request):
        now = timezone.now()
        window_start = now - timedelta(days=self.WINDOW_DAYS)
        sets = (BodieZSet.objects
                .filter(session__user=request.user, session__ended_at__isnull=False)
                .select_related("exercise", "session"))

        by_muscle = defaultdict(list)
        for s in sets:
            by_muscle[s.exercise.muscle_group].append(s)
        ratings = muscle_coach_ratings(sets, now, self.TARGET_WEEKLY_SETS)
        unrated = {"rating": None, "exercises": [],
                   "why": f"Not thorough yet — nothing logged for this muscle in the last {THOROUGH_DAYS} days."}

        rows = []
        for muscle, label in BodieZExercise.MUSCLE_CHOICES:
            group_sets = by_muscle.get(muscle, [])
            if not group_sets:
                rows.append({"muscle_group": muscle, "label": label,
                             "last_trained": None, "sets_last_7d": 0,
                             "days_trained_last_7d": 0, "status": "untrained",
                             "volume_score": 0,
                             "coach_rating": None, "coach_why": unrated["why"],
                             "coach_exercises": []})
                continue

            last_trained = max(s.session.started_at for s in group_sets)
            recent = [s for s in group_sets if s.session.started_at >= window_start]
            days_trained = len({s.session.started_at.date() for s in recent})
            days_since = (now - last_trained).days

            if days_since > self.STALE_DAYS:
                status_ = "undertrained"
            elif days_trained >= self.OVERWORKED_SESSION_DAYS:
                status_ = "overworked"
            elif days_since <= self.RECENT_DAYS:
                status_ = "recent"
            else:
                status_ = "balanced"

            rows.append({
                "muscle_group": muscle, "label": label,
                "last_trained": last_trained.isoformat(),
                "sets_last_7d": len(recent),
                "days_trained_last_7d": days_trained,
                "status": status_,
                "volume_score": min(10, round(10 * len(recent) / self.TARGET_WEEKLY_SETS)),
                "coach_rating": ratings.get(muscle, unrated)["rating"],
                "coach_why": ratings.get(muscle, unrated)["why"],
                "coach_exercises": ratings.get(muscle, unrated)["exercises"],
            })

        return Response({
            "muscles": rows,
            "window_days": self.WINDOW_DAYS,
            "recent_days": self.RECENT_DAYS,
            "stale_after_days": self.STALE_DAYS,
            "target_weekly_sets": self.TARGET_WEEKLY_SETS,
            "volume_citation": self.VOLUME_CITATION,
            "rating_caveat": RATING_CAVEAT,
        })


# What each recommendation MEANS — served alongside every row for the same
# reason `instruments.py` serves a label with every score: a member reading
# "increase_weight" with nothing to explain it has a keyword, not advice.
REC_LABELS = {
    "increase_weight": "Add weight next time 📈",
    "hold_steady": "Hold steady 🤝",
    "deload_taken": "Deload logged 📉",
    "increase_difficulty": "Increase difficulty 💪",
    "reintroduce": "Reintroduce or swap it 🔄",
    "not_enough_data": "Not enough data yet 🌱",
}


class BodieZCoachView(APIView):
    """GET /api/economy/bodiez/coach/ — per-exercise recommendations, built
    from comparing the member's own last two logged sessions for each
    exercise. Arithmetic, not a model — see the module docstring for why.

    Every row carries `why` in the member's own numbers, because a
    recommendation with no visible reasoning is a black box wearing a
    coach's name, which is the exact thing the substance rule exists to
    keep off this screen.
    """
    permission_classes = [IsAuthenticated]

    STALE_DAYS = 21
    MIN_SESSIONS_FOR_A_CALL = 2

    def get(self, request):
        sessions = (BodieZSession.objects
                    .filter(user=request.user, ended_at__isnull=False)
                    .order_by("started_at")
                    .prefetch_related("sets__exercise"))

        # exercise_id -> [(session, [sets in that session]), ...], oldest first
        by_exercise = defaultdict(list)
        for sess in sessions:
            per_ex = defaultdict(list)
            for s in sess.sets.all():
                per_ex[_lane(s)].append(s)
            for lane, ex_sets in per_ex.items():
                by_exercise[lane].append((sess, ex_sets))

        now = timezone.now()
        rows = []
        for (ex_id, side), history in by_exercise.items():
            last_sess, last_sets = history[-1]
            exercise = last_sets[0].exercise
            ex_name = _lane_name(exercise.name, side)
            days_since = (now - last_sess.started_at).days
            total_sessions = len(history)

            if days_since > self.STALE_DAYS and total_sessions >= 3:
                rows.append({
                    "exercise_id": ex_id, "one_sided": side, "exercise_name": ex_name,
                    "recommendation": "reintroduce",
                    "why": f"Last logged {days_since} days ago after {total_sessions} sessions — "
                           "bring it back, or swap it out on purpose.",
                    "last_trained": last_sess.started_at.isoformat(),
                })
                continue

            if total_sessions < self.MIN_SESSIONS_FOR_A_CALL:
                rows.append({
                    "exercise_id": ex_id, "one_sided": side, "exercise_name": ex_name,
                    "recommendation": "not_enough_data",
                    "why": "One logged session isn't a trend yet.",
                    "last_trained": last_sess.started_at.isoformat(),
                })
                continue

            prev_sess, prev_sets = history[-2]
            last_weighted = [s for s in last_sets if s.weight_kg is not None]
            prev_weighted = [s for s in prev_sets if s.weight_kg is not None]

            if last_weighted and prev_weighted:
                last_top = max(last_weighted, key=lambda s: s.weight_kg)
                prev_top = max(prev_weighted, key=lambda s: s.weight_kg)
                if last_top.weight_kg > prev_top.weight_kg:
                    rec = "hold_steady"
                    why = (f"You already moved up to {last_top.weight_kg}kg last time — "
                           "let it settle before adding more.")
                elif last_top.weight_kg == prev_top.weight_kg:
                    if last_top.reps >= prev_top.reps:
                        rec = "increase_weight"
                        why = (f"Same {last_top.weight_kg}kg, same-or-more reps "
                               f"({last_top.reps} vs {prev_top.reps}) — time to add weight.")
                    else:
                        rec = "hold_steady"
                        why = (f"Reps dropped at {last_top.weight_kg}kg "
                               f"({last_top.reps} vs {prev_top.reps}) — repeat before adding weight.")
                else:
                    rec = "deload_taken"
                    why = (f"Weight dropped from {prev_top.weight_kg}kg to {last_top.weight_kg}kg — "
                           "logged as a deload, not a red flag by itself.")
            else:
                last_reps = sum(s.reps for s in last_sets)
                prev_reps = sum(s.reps for s in prev_sets)
                if last_reps > prev_reps:
                    rec = "increase_difficulty"
                    why = (f"Total reps went up ({prev_reps} → {last_reps}) with no weight tracked — "
                           "a harder variation or added resistance is the next step.")
                elif last_reps < prev_reps:
                    rec = "hold_steady"
                    why = f"Reps dropped ({prev_reps} → {last_reps}) — repeat at this level."
                else:
                    rec = "hold_steady"
                    why = "Same total reps as last time — repeat before changing anything."

            rows.append({
                "exercise_id": ex_id, "one_sided": side, "exercise_name": ex_name,
                "recommendation": rec, "why": why,
                "last_trained": last_sess.started_at.isoformat(),
            })

        rows.sort(key=lambda r: r["exercise_name"])
        return Response({
            "exercises": rows,
            "labels": REC_LABELS,
            "stale_after_days": self.STALE_DAYS,
            "goals": GOALS,
            "splits": SPLITS,
        })


_GOAL_KIND_KEYS = {k for k, _ in BODIEZ_GOAL_KINDS}
FREQUENCY_WINDOW_DAYS = 7


def _best_set(user, exercise, min_reps=None):
    """The heaviest logged, weighted set ever against this exercise — the
    same "read the real rows" the Coach uses for its own comparisons."""
    qs = BodieZSet.objects.filter(session__user=user, session__ended_at__isnull=False,
                                  exercise=exercise, weight_kg__isnull=False)
    if min_reps:
        qs = qs.filter(reps__gte=min_reps)
    return qs.order_by("-weight_kg").first()


def goal_progress(goal, user):
    """(current_value, target_value, pct 0-100 or None, achieved: bool).

    `pct` is None only when there's nothing to divide by yet (a strength goal
    with no matching set logged) — never a fabricated 0, because 0% reads as
    "you've made no progress" and "we have no data" is a different fact.
    """
    if goal.kind == "strength":
        best = _best_set(user, goal.exercise, goal.target_reps)
        target = float(goal.target_value)
        if not best:
            return None, target, None, False
        current = float(best.weight_kg)
        pct = min(100.0, round(current / target * 100, 1)) if target else None
        return current, target, pct, current >= target

    if goal.kind == "frequency":
        since = timezone.now() - timedelta(days=FREQUENCY_WINDOW_DAYS)
        days = (BodieZSession.objects
                .filter(user=user, ended_at__isnull=False, started_at__gte=since)
                .values_list("started_at__date", flat=True))
        current = len(set(days))
        target = float(goal.target_value)
        pct = min(100.0, round(current / target * 100, 1)) if target else None
        return current, target, pct, current >= target

    if goal.kind == "count":
        current = BodieZSession.objects.filter(user=user, ended_at__isnull=False).count()
        target = float(goal.target_value)
        pct = min(100.0, round(current / target * 100, 1)) if target else None
        return current, target, pct, current >= target

    if goal.kind == "bodyweight":
        latest = BodieZWeightLog.objects.filter(user=user).first()
        if not latest or goal.starting_value is None:
            return None, float(goal.target_value), None, False
        current = float(latest.weight_kg)
        target = float(goal.target_value)
        start = float(goal.starting_value)
        span = target - start
        if span == 0:
            pct = 100.0 if current == target else 0.0
        else:
            pct = max(0.0, min(100.0, round((current - start) / span * 100, 1)))
        # Losing weight and gaining weight cross the target from opposite
        # sides, so "achieved" has to check the direction the goal set out
        # in, not just >=.
        achieved = current <= target if span < 0 else current >= target
        return current, target, pct, achieved

    return None, float(goal.target_value), None, False


def _goal_dict(goal, user):
    current, target, pct, achieved = goal_progress(goal, user)
    return {
        "id": goal.id, "kind": goal.kind, "title": goal.title,
        "exercise_id": goal.exercise_id,
        "exercise_name": goal.exercise.name if goal.exercise_id else None,
        "target_value": target, "target_reps": goal.target_reps,
        "starting_value": float(goal.starting_value) if goal.starting_value is not None else None,
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "current_value": current, "pct": pct, "achieved": achieved,
        "created_at": goal.created_at.isoformat(),
    }


class BodieZGoalsView(APIView):
    """GET/POST /api/economy/bodiez/goals/ — list mine with live progress
    attached, or set a new one.

    POST body: kind (required, one of BODIEZ_GOAL_KINDS), title (required),
    target_value (required), exercise_id (required for `strength`),
    target_reps (optional, `strength` only), target_date (optional).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        goals = BodieZGoal.objects.filter(user=request.user)
        return Response({
            "goals": [_goal_dict(g, request.user) for g in goals],
            "kinds": [{"key": k, "label": v} for k, v in BODIEZ_GOAL_KINDS],
        })

    def post(self, request):
        d = request.data
        kind = d.get("kind")
        if kind not in _GOAL_KIND_KEYS:
            return Response({"detail": f"kind must be one of {sorted(_GOAL_KIND_KEYS)}."},
                             status=status.HTTP_400_BAD_REQUEST)
        title = (d.get("title") or "").strip()
        if not title:
            return Response({"detail": "Goal needs a title."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            target_value = Decimal(str(d.get("target_value")))
        except Exception:
            return Response({"detail": "target_value must be a number."}, status=status.HTTP_400_BAD_REQUEST)
        if target_value <= 0:
            return Response({"detail": "target_value must be positive."}, status=status.HTTP_400_BAD_REQUEST)

        exercise = None
        if kind == "strength":
            try:
                exercise = BodieZExercise.objects.visible(request.user).get(id=d.get("exercise_id"))
            except (BodieZExercise.DoesNotExist, ValueError, TypeError):
                return Response({"detail": "A strength goal needs a real exercise_id."},
                                 status=status.HTTP_400_BAD_REQUEST)

        target_reps = None
        if d.get("target_reps") not in (None, ""):
            try:
                target_reps = max(1, int(d["target_reps"]))
            except (TypeError, ValueError):
                return Response({"detail": "target_reps must be a whole number."},
                                 status=status.HTTP_400_BAD_REQUEST)

        target_date = None
        if d.get("target_date"):
            try:
                target_date = date.fromisoformat(str(d["target_date"])[:10])
            except ValueError:
                return Response({"detail": "target_date must be YYYY-MM-DD."},
                                 status=status.HTTP_400_BAD_REQUEST)

        starting_value = None
        if kind == "bodyweight":
            # Snapshotted now, because a starting point that could drift
            # after the fact would let the goal rewrite its own difficulty.
            latest = BodieZWeightLog.objects.filter(user=request.user).first()
            starting_value = latest.weight_kg if latest else target_value

        goal = BodieZGoal.objects.create(
            user=request.user, kind=kind, title=title[:80], exercise=exercise,
            target_value=target_value, target_reps=target_reps,
            starting_value=starting_value, target_date=target_date,
        )
        return Response(_goal_dict(goal, request.user), status=status.HTTP_201_CREATED)


class BodieZGoalDetailView(APIView):
    """PATCH/DELETE /api/economy/bodiez/goals/{id}/ — only title and
    target_date are editable. The target itself is not, on purpose: changing
    what "achieved" means after the fact is how a goal stops meaning
    anything — delete it and start a new one instead."""
    permission_classes = [IsAuthenticated]

    def _get(self, request, goal_id):
        return BodieZGoal.objects.filter(id=goal_id, user=request.user).first()

    def patch(self, request, goal_id):
        goal = self._get(request, goal_id)
        if not goal:
            return Response({"detail": "Goal not found."}, status=status.HTTP_404_NOT_FOUND)
        d = request.data
        fields = []
        if "title" in d:
            title = str(d["title"]).strip()
            if not title:
                return Response({"detail": "Goal needs a title."}, status=status.HTTP_400_BAD_REQUEST)
            goal.title = title[:80]
            fields.append("title")
        if "target_date" in d:
            raw = d.get("target_date")
            if not raw:
                goal.target_date = None
            else:
                try:
                    goal.target_date = date.fromisoformat(str(raw)[:10])
                except ValueError:
                    return Response({"detail": "target_date must be YYYY-MM-DD."},
                                     status=status.HTTP_400_BAD_REQUEST)
            fields.append("target_date")
        if fields:
            goal.save(update_fields=fields)
        return Response(_goal_dict(goal, request.user))

    def delete(self, request, goal_id):
        goal = self._get(request, goal_id)
        if not goal:
            return Response({"detail": "Goal not found."}, status=status.HTTP_404_NOT_FOUND)
        goal.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BodieZWeightLogView(APIView):
    """GET/POST /api/economy/bodiez/weightlog/ — the only reader of this is a
    `bodyweight` goal's progress; this is a check-in, not a Nutrition
    feature."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        logs = BodieZWeightLog.objects.filter(user=request.user)[:60]
        return Response({"logs": [
            {"id": l.id, "weight_kg": float(l.weight_kg), "logged_at": l.logged_at.isoformat()}
            for l in logs
        ]})

    def post(self, request):
        try:
            weight_kg = Decimal(str(request.data.get("weight_kg")))
        except Exception:
            return Response({"detail": "weight_kg must be a number."}, status=status.HTTP_400_BAD_REQUEST)
        if weight_kg <= 0:
            return Response({"detail": "weight_kg must be positive."}, status=status.HTTP_400_BAD_REQUEST)
        log = BodieZWeightLog.objects.create(user=request.user, weight_kg=weight_kg)
        return Response({"id": log.id, "weight_kg": float(log.weight_kg),
                         "logged_at": log.logged_at.isoformat()}, status=status.HTTP_201_CREATED)


def _recovery_dict(log):
    return {"id": log.id, "soreness": log.soreness, "sleep_quality": log.sleep_quality,
            "fatigue": log.fatigue, "notes": log.notes, "logged_at": log.logged_at.isoformat()}


# The number this endpoint refuses to invent: a single "readiness score"
# blending self-report and training load would be exactly the composite
# `directz_ai_rating` was — a number that FEELS like a measurement while
# actually being an average of things that don't average cleanly. What it
# returns instead is a real count (days trained in the window, the same
# BodyMap already computes) sitting next to the member's own numbers,
# unmixed, so whoever reads it does the one piece of judgment a formula
# can't: deciding what soreness + four training days this week actually
# means for THEM today.
REST_WINDOW_DAYS = 7
REST_SUGGESTED_TRAINING_DAYS = 5  # BodyMap's own "overworked" threshold + 1
REST_SUGGESTED_SORENESS = 4       # of 5 — a member's own word for it


class BodieZRecoveryView(APIView):
    """GET the recent check-ins plus a rest signal; POST today's check-in.

    `rest_suggested` is a bool, never a score, and it is true for one of two
    REAL reasons the response names separately — trained
    `REST_SUGGESTED_TRAINING_DAYS`+ days this window, or the member's own
    most recent soreness/fatigue reading hit `REST_SUGGESTED_SORENESS`+.
    Either reason alone is enough; neither is blended into the other.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        since = now - timedelta(days=REST_WINDOW_DAYS)
        days_trained = len(set(
            BodieZSession.objects
            .filter(user=request.user, ended_at__isnull=False, started_at__gte=since)
            .values_list("started_at__date", flat=True)
        ))
        latest = BodieZRecoveryLog.objects.filter(user=request.user).first()
        self_reported_high = bool(
            latest and (latest.soreness >= REST_SUGGESTED_SORENESS
                        or latest.fatigue >= REST_SUGGESTED_SORENESS)
        )
        overtrained = days_trained >= REST_SUGGESTED_TRAINING_DAYS
        logs = BodieZRecoveryLog.objects.filter(user=request.user)[:14]
        return Response({
            "logs": [_recovery_dict(l) for l in logs],
            "days_trained_last_7d": days_trained,
            "rest_suggested": overtrained or self_reported_high,
            "rest_suggested_because": (
                ["trained_often"] * overtrained + ["self_reported"] * self_reported_high
            ),
            "window_days": REST_WINDOW_DAYS,
        })

    def post(self, request):
        d = request.data
        try:
            soreness = int(d.get("soreness"))
            sleep_quality = int(d.get("sleep_quality"))
            fatigue = int(d.get("fatigue"))
        except (TypeError, ValueError):
            return Response({"detail": "soreness, sleep_quality and fatigue must be numbers 1-5."},
                             status=status.HTTP_400_BAD_REQUEST)
        if not all(1 <= v <= 5 for v in (soreness, sleep_quality, fatigue)):
            return Response({"detail": "soreness, sleep_quality and fatigue must each be 1-5."},
                             status=status.HTTP_400_BAD_REQUEST)
        log = BodieZRecoveryLog.objects.create(
            user=request.user, soreness=soreness, sleep_quality=sleep_quality,
            fatigue=fatigue, notes=str(d.get("notes") or "")[:280],
        )
        return Response(_recovery_dict(log), status=status.HTTP_201_CREATED)


# --- StepZ --------------------------------------------------------------
#
# The screen was written against a coach that scored cadence, form,
# stability and endurance "from steps". A step COUNT carries none of that —
# a number of steps says nothing about how they were taken — so scoring those
# from it would be the substance rule's failure case: a rating that moves on
# form completeness, not on the thing it names. The coach endpoint therefore
# answers only with what a count can honestly give (totals, an average) and
# leaves `scores`/`medians`/`overall_score` empty, which the screen already
# renders as "nothing to show". Prefer no number to a fake one.
DAILY_STEP_GOAL = 10000        # a stated default, not a tier limit
MAX_STEPS_PER_ENTRY = 100000   # one entry past this is a typo, not a walk


def _today_bounds():
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


class BodieZStepsView(APIView):
    """GET/POST /api/economy/bodiez/steps/ — today's entries and total; add one."""
    permission_classes = [IsAuthenticated]

    def _payload(self, user):
        start, end = _today_bounds()
        rows = list(BodieZStepLog.objects.filter(user=user, logged_at__gte=start, logged_at__lt=end))
        return {"steps": [{"id": r.id, "count": r.count, "logged_at": r.logged_at.isoformat()} for r in rows],
                "today_total": sum(r.count for r in rows), "daily_goal": DAILY_STEP_GOAL}

    def get(self, request):
        return Response(self._payload(request.user))

    def post(self, request):
        try:
            count = int(request.data.get("count"))
        except (TypeError, ValueError):
            return Response({"detail": "Steps must be a whole number."}, status=status.HTTP_400_BAD_REQUEST)
        if not 1 <= count <= MAX_STEPS_PER_ENTRY:
            return Response({"detail": f"Enter between 1 and {MAX_STEPS_PER_ENTRY:,} steps."},
                            status=status.HTTP_400_BAD_REQUEST)
        BodieZStepLog.objects.create(user=request.user, count=count)
        return Response(self._payload(request.user), status=status.HTTP_201_CREATED)


class BodieZStepCoachView(APIView):
    """GET /api/economy/bodiez/stepz/coach/ — what a step count can honestly
    show. No quality scores: see the note above."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        start, _ = _today_bounds()
        since = start - timedelta(days=6)
        rows = BodieZStepLog.objects.filter(user=request.user, logged_at__gte=since)
        total = sum(r.count for r in rows)
        days = {timezone.localtime(r.logged_at).date() for r in rows}
        return Response({
            "scores": {}, "medians": {}, "overall_score": None, "step_counts": {},
            "total_steps": total, "days_logged": len(days),
            "avg_per_logged_day": round(total / len(days)) if days else None,
            "caveat": ("These are your step totals for the last 7 days. A step count shows how much you "
                       "moved, not how well — cadence, form and stability can't be read from a number, "
                       "so none are scored here."),
        })
