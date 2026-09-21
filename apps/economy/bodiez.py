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

Deliberately still NOT built here: BodyMap, Nutrition, Community, an AI Coach
recommendation engine, Goals, Recovery, and XP/streak rewards. The last one is
worth explaining rather than just omitting — XP here would need its own
wallet column (nothing in this codebase has a general per-user XP total;
LilithPayout.xp is Lilith-specific) and a decision about whether a logged set
is "effort" in the sense the substance rule allows XP for. That is a real
design question, not a gap to fill silently, so it stays a follow-up.
"""
from datetime import date
from decimal import Decimal

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import BODIEZ_BUCKETS, BodieZExercise, BodieZRoutine, BodieZSession, BodieZSet

_BUCKET_KEYS = {k for k, _ in BODIEZ_BUCKETS}


def _exercise_dict(ex):
    return {"id": ex.id, "name": ex.name, "muscle_group": ex.muscle_group,
            "equipment": ex.equipment}


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
