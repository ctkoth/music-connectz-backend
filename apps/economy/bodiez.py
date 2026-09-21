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
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (BODIEZ_BUCKETS, BODIEZ_GOAL_KINDS, BodieZExercise, BodieZGoal,
                     BodieZRecoveryLog, BodieZRoutine, BodieZSession, BodieZSet,
                     BodieZWeightLog)

_BUCKET_KEYS = {k for k, _ in BODIEZ_BUCKETS}


def _exercise_dict(ex):
    return {"id": ex.id, "name": ex.name, "muscle_group": ex.muscle_group,
            "equipment": ex.equipment, "demo_url": ex.demo_url}


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
# Three goals, not the many an exercise-science textbook would name, because
# three is what a member choosing a routine actually decides between —
# strength itself is deliberately excluded here since BodieZGoal already has
# a "strength" kind driven by logged 1RM progress; a fourth goal here would
# be the second place that word means something on this screen.
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
}


def _routine_dict(r):
    return {"id": r.id, "title": r.title, "exercises": r.exercises,
            "bucket": r.bucket,
            "scheduled_for": r.scheduled_for.isoformat() if r.scheduled_for else None,
            "updated_at": r.updated_at.isoformat()}


def _set_dict(s):
    return {"id": s.id, "exercise_id": s.exercise_id, "exercise_name": s.exercise.name,
            "set_number": s.set_number, "reps": s.reps,
            "weight_kg": float(s.weight_kg) if s.weight_kg is not None else None}


def _session_dict(sess, sets=None):
    sets = sets if sets is not None else list(sess.sets.select_related("exercise"))
    return {
        "id": sess.id,
        "routine_id": sess.routine_id,
        "routine_title": sess.routine.title if sess.routine_id and sess.routine else None,
        "started_at": sess.started_at.isoformat(),
        "ended_at": sess.ended_at.isoformat() if sess.ended_at else None,
        "notes": sess.notes,
        "sets": [_set_dict(s) for s in sets],
    }


class BodieZExercisesView(APIView):
    """GET /api/economy/bodiez/exercises/ — the movement library, everyone's,
    read-only. Nothing here is per-user, so there is no write endpoint."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = BodieZExercise.objects.all()
        muscle = request.query_params.get("muscle_group")
        if muscle:
            rows = rows.filter(muscle_group=muscle)
        return Response({"exercises": [_exercise_dict(e) for e in rows]})


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
        last_set = (BodieZSet.objects
                    .filter(session__user=request.user, session__ended_at__isnull=False,
                            exercise_id=exercise_id)
                    .order_by("-session__started_at", "-set_number")
                    .select_related("session")
                    .first())
        if not last_set:
            return Response({"last_session": None})
        sets = (BodieZSet.objects
                .filter(session=last_set.session_id, exercise_id=exercise_id)
                .order_by("set_number"))
        return Response({
            "last_session": {
                "started_at": last_set.session.started_at.isoformat(),
                "sets": [_set_dict(s) for s in sets],
            },
        })


class BodieZRoutinesView(APIView):
    """GET/POST /api/economy/bodiez/routines/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = BodieZRoutine.objects.filter(user=request.user)
        return Response({"routines": [_routine_dict(r) for r in rows]})

    def post(self, request):
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"detail": "Routine needs a title."}, status=status.HTTP_400_BAD_REQUEST)
        exercises = request.data.get("exercises")
        if not isinstance(exercises, list):
            exercises = []
        # Validate every exercise id up front rather than storing a routine
        # that silently 404s a card the moment somebody starts a session
        # from it.
        ids = [e.get("exercise_id") for e in exercises if isinstance(e, dict) and e.get("exercise_id")]
        valid_ids = set(BodieZExercise.objects.filter(id__in=ids).values_list("id", flat=True))
        bad = [i for i in ids if i not in valid_ids]
        if bad:
            return Response({"detail": f"Unknown exercise id(s): {bad}"}, status=status.HTTP_400_BAD_REQUEST)
        bucket = request.data.get("bucket")
        bucket = bucket if bucket in _BUCKET_KEYS else "inbox"
        routine = BodieZRoutine.objects.create(user=request.user, title=title, exercises=exercises,
                                                bucket=bucket)
        return Response(_routine_dict(routine), status=status.HTTP_201_CREATED)


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
            title = title.strip()
            if not title:
                return Response({"detail": "Routine needs a title."}, status=status.HTTP_400_BAD_REQUEST)
            routine.title = title
        exercises = request.data.get("exercises")
        if exercises is not None:
            if not isinstance(exercises, list):
                return Response({"detail": "exercises must be a list."}, status=status.HTTP_400_BAD_REQUEST)
            ids = [e.get("exercise_id") for e in exercises if isinstance(e, dict) and e.get("exercise_id")]
            valid_ids = set(BodieZExercise.objects.filter(id__in=ids).values_list("id", flat=True))
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


class BodieZSessionDetailView(APIView):
    """PATCH /api/economy/bodiez/sessions/{id}/ — finish a session (notes,
    ended_at)."""
    permission_classes = [IsAuthenticated]

    def patch(self, request, session_id):
        try:
            sess = BodieZSession.objects.get(id=session_id, user=request.user)
        except BodieZSession.DoesNotExist:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        if request.data.get("finish"):
            if sess.ended_at:
                return Response({"detail": "Session already finished."}, status=status.HTTP_400_BAD_REQUEST)
            from django.utils import timezone
            sess.ended_at = timezone.now()
        notes = request.data.get("notes")
        if notes is not None:
            sess.notes = notes
        sess.save()
        return Response(_session_dict(sess))


class BodieZSetsView(APIView):
    """POST /api/economy/bodiez/sessions/{id}/sets/ — log one set."""
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        try:
            sess = BodieZSession.objects.get(id=session_id, user=request.user)
        except BodieZSession.DoesNotExist:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        if sess.ended_at:
            return Response({"detail": "This session is already finished."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            exercise = BodieZExercise.objects.get(id=request.data.get("exercise_id"))
        except (BodieZExercise.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "Unknown exercise."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            reps = int(request.data.get("reps"))
        except (TypeError, ValueError):
            return Response({"detail": "reps must be a number."}, status=status.HTTP_400_BAD_REQUEST)
        if reps <= 0:
            return Response({"detail": "reps must be positive."}, status=status.HTTP_400_BAD_REQUEST)

        weight_kg = request.data.get("weight_kg")
        if weight_kg is not None:
            try:
                weight_kg = Decimal(str(weight_kg))
            except Exception:
                return Response({"detail": "weight_kg must be a number."}, status=status.HTTP_400_BAD_REQUEST)
            if weight_kg < 0:
                return Response({"detail": "weight_kg cannot be negative."}, status=status.HTTP_400_BAD_REQUEST)

        set_number = sess.sets.filter(exercise=exercise).count() + 1
        s = BodieZSet.objects.create(session=sess, exercise=exercise, set_number=set_number,
                                      reps=reps, weight_kg=weight_kg)
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
    """
    permission_classes = [IsAuthenticated]

    RECENT_DAYS = 3
    STALE_DAYS = 10
    WINDOW_DAYS = 7
    OVERWORKED_SESSION_DAYS = 4

    def get(self, request):
        now = timezone.now()
        window_start = now - timedelta(days=self.WINDOW_DAYS)
        sets = (BodieZSet.objects
                .filter(session__user=request.user, session__ended_at__isnull=False)
                .select_related("exercise", "session"))

        by_muscle = defaultdict(list)
        for s in sets:
            by_muscle[s.exercise.muscle_group].append(s)

        rows = []
        for muscle, label in BodieZExercise.MUSCLE_CHOICES:
            group_sets = by_muscle.get(muscle, [])
            if not group_sets:
                rows.append({"muscle_group": muscle, "label": label,
                             "last_trained": None, "sets_last_7d": 0,
                             "days_trained_last_7d": 0, "status": "untrained"})
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
            })

        return Response({
            "muscles": rows,
            "window_days": self.WINDOW_DAYS,
            "recent_days": self.RECENT_DAYS,
            "stale_after_days": self.STALE_DAYS,
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
                per_ex[s.exercise_id].append(s)
            for ex_id, ex_sets in per_ex.items():
                by_exercise[ex_id].append((sess, ex_sets))

        now = timezone.now()
        rows = []
        for ex_id, history in by_exercise.items():
            last_sess, last_sets = history[-1]
            exercise = last_sets[0].exercise
            days_since = (now - last_sess.started_at).days
            total_sessions = len(history)

            if days_since > self.STALE_DAYS and total_sessions >= 3:
                rows.append({
                    "exercise_id": ex_id, "exercise_name": exercise.name,
                    "recommendation": "reintroduce",
                    "why": f"Last logged {days_since} days ago after {total_sessions} sessions — "
                           "bring it back, or swap it out on purpose.",
                    "last_trained": last_sess.started_at.isoformat(),
                })
                continue

            if total_sessions < self.MIN_SESSIONS_FOR_A_CALL:
                rows.append({
                    "exercise_id": ex_id, "exercise_name": exercise.name,
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
                "exercise_id": ex_id, "exercise_name": exercise.name,
                "recommendation": rec, "why": why,
                "last_trained": last_sess.started_at.isoformat(),
            })

        rows.sort(key=lambda r: r["exercise_name"])
        return Response({
            "exercises": rows,
            "labels": REC_LABELS,
            "stale_after_days": self.STALE_DAYS,
            "goals": GOALS,
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
                exercise = BodieZExercise.objects.get(id=d.get("exercise_id"))
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
