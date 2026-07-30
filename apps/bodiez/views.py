"""BodieZ API.

    GET  /api/bodiez/catalog/                equipment, muscles, patterns, goals
    GET  /api/bodiez/exercises/              filtered library (?equipment=&muscles=)
    GET  POST   /api/bodiez/routines/        yours (+ ?shared=1 for StatZ)
    GET  PATCH DELETE /api/bodiez/routines/<id>/
    POST /api/bodiez/routines/<id>/exercises/    add an exercise with targets
    POST /api/bodiez/routines/ai/            Corey writes one (costs a prompt)
    GET  POST   /api/bodiez/sessions/        history / start one
    POST /api/bodiez/sessions/<id>/sets/     log a set
    POST /api/bodiez/sessions/<id>/finish/
    GET  /api/bodiez/progress/               charts, PRs, volume, streak
    GET  /api/bodiez/bodymap/                trained / undertrained / overworked
    GET  /api/bodiez/coach/                  overload verdicts + readiness
    GET  POST   /api/bodiez/items/           the Lilith buckets
    PATCH DELETE /api/bodiez/items/<id>/
    GET  POST   /api/bodiez/metrics/         body check-ins
    GET  POST   /api/bodiez/goals/
    GET  POST   /api/bodiez/locations/       PREMIUM: rooms + equipment
    DELETE      /api/bodiez/locations/<id>/

Tiers, as specified:
  * **Free** — the whole training loop. Log workouts, build your own routines,
    the full exercise library. Nothing about tracking your own training is
    paywalled, because a tracker you can't use isn't a tracker.
  * **Premium** — GymLocations with their equipment and muscle-coverage metrics.
  * **StatZ** — browsing other members' shared routines, and the AI Coach run
    without spending a prompt.

The AI Coach itself is open to **every** tier: a free member spends one of their
daily prompts on it. Locking it away entirely means a free member never finds out
it's good, which is the opposite of what a paywall is for.
"""
from datetime import date, timedelta

from django.db.models import Count, Max, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.economy.catalog import ai_cost
from apps.economy.models import (TIER_DEBUG, TIER_PREMIUM, TIER_STATZ,
                                 can_afford_ai, charge_ai_usage,
                                 daily_prompt_state, membership_for)

from . import catalog as cat
from . import coach
from .models import (BUCKET_LABELS, BUCKETS, BodieZItem, BodyMetric, Exercise,
                     FitnessGoal, GymLocation, Routine, RoutineExercise,
                     WorkoutSession, WorkoutSet)

PREMIUM_TIERS = {TIER_PREMIUM, TIER_STATZ, TIER_DEBUG}
STATZ_TIERS = {TIER_STATZ, TIER_DEBUG}


def tier_of(user):
    return membership_for(user).tier


def _gate(user, tiers, feature):
    """(ok, response). One place, so the paywall message is always the same shape."""
    if tier_of(user) in tiers:
        return True, None
    needed = "StatZ" if tiers is STATZ_TIERS else "Premium"
    return False, Response(
        {"detail": f"{feature} is a {needed} feature.", "required_tier": needed.lower(),
         "your_tier": tier_of(user)},
        status=status.HTTP_402_PAYMENT_REQUIRED,
    )


def _csv(request, key):
    raw = request.query_params.get(key, "")
    return [v.strip() for v in raw.split(",") if v.strip()]


def _exercise_dict(e):
    return {
        "id": e.id, "key": e.key, "name": e.name, "muscle": e.muscle,
        "secondary": e.secondary, "equipment": e.equipment, "pattern": e.pattern,
        "requires": e.requires,
        "difficulty": e.difficulty, "instructions": e.instructions,
        "media_url": e.media_url, "custom": not e.is_catalog,
    }


def _routine_exercise_dict(re_):
    return {
        "id": re_.id, "order": re_.order,
        "exercise": _exercise_dict(re_.exercise),
        "sets": re_.sets, "reps": re_.reps, "rest_seconds": re_.rest_seconds,
        "target_weight": float(re_.target_weight) if re_.target_weight is not None else None,
        "target_volume": re_.target_volume,
        "tempo": re_.tempo, "superset_group": re_.superset_group,
        "notes": re_.notes, "is_warmup": re_.is_warmup,
    }


def _routine_dict(r, full=False):
    out = {
        "id": r.id, "name": r.name, "description": r.description, "goal": r.goal,
        "split": r.split, "difficulty": r.difficulty,
        "days_per_week": r.days_per_week, "bucket": r.bucket,
        "bucket_label": BUCKET_LABELS.get(r.bucket, r.bucket),
        "scheduled_for": r.scheduled_for, "is_public": r.is_public,
        "equipment": r.equipment, "owner": r.owner.username,
        "exercise_count": r.exercises.count(),
        "estimated_minutes": r.estimated_minutes,
        "updated_at": r.updated_at,
    }
    if full:
        out["exercises"] = [_routine_exercise_dict(x) for x in
                            r.exercises.select_related("exercise")]
        out["muscles"] = r.muscles
    return out


def _set_dict(s):
    return {
        "id": s.id, "exercise_id": s.exercise_id, "exercise": s.exercise.name,
        "set_number": s.set_number,
        "weight": float(s.weight) if s.weight is not None else None,
        "reps": s.reps, "duration_seconds": s.duration_seconds,
        "distance_m": s.distance_m,
        "rpe": float(s.rpe) if s.rpe is not None else None, "rir": s.rir,
        "rest_seconds": s.rest_seconds, "is_warmup": s.is_warmup,
        "completed": s.completed, "note": s.note,
        "volume": s.volume, "estimated_1rm": s.estimated_1rm,
    }


def _session_dict(s, full=False):
    out = {
        "id": s.id, "routine_id": s.routine_id,
        "name": s.name or (s.routine.name if s.routine else "Freestyle"),
        "started_at": s.started_at, "ended_at": s.ended_at, "status": s.status,
        "duration_minutes": s.duration_minutes, "total_volume": s.total_volume,
        "perceived_effort": s.perceived_effort, "notes": s.notes,
        "set_count": s.sets.count(),
        "location": s.location.name if s.location else None,
    }
    if full:
        out["sets"] = [_set_dict(x) for x in s.sets.select_related("exercise")]
    return out


class CatalogView(APIView):
    """GET the whole reference vocabulary. Public — it's a picker, not member data."""

    permission_classes = [AllowAny]

    def get(self, _request):
        return Response({
            "equipment": cat.equipment_payload(),
            "muscle_groups": cat.muscle_payload(),
            "movement_patterns": cat.simple_payload(cat.MOVEMENT_PATTERNS),
            "difficulties": cat.simple_payload(cat.DIFFICULTIES),
            "goals": cat.simple_payload(cat.GOALS),
            "splits": cat.SPLITS,
            "buckets": [{"key": b, "label": BUCKET_LABELS[b]} for b in BUCKETS],
            "exercise_count": len(cat.EXERCISES),
            "tiers": {
                "free": ["log workouts", "own routines", "exercise library",
                         "progress", "bodymap", "coach verdicts",
                         "AI Coach (costs a daily prompt)"],
                "premium": ["gym locations + equipment coverage"],
                "statz": ["AI Coach without spending a prompt",
                          "other members' routines"],
            },
        })


class ExercisesView(APIView):
    """GET the library. `?equipment=barbell,flat-bench&muscles=chest` filters it
    the way the routine builder does — every piece an exercise needs must be
    available, not just one of them."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        equipment = _csv(request, "equipment")
        muscles = _csv(request, "muscles")
        qs = Exercise.objects.filter(active=True).filter(
            Q(owner__isnull=True) | Q(owner=request.user))
        if muscles:
            qs = qs.filter(Q(muscle__in=muscles) | Q(secondary__overlap=muscles)) \
                if _supports_overlap() else qs.filter(muscle__in=muscles)
        have = set(equipment) | ({"bodyweight"} if equipment else set())
        rows = [e for e in qs
                if not equipment or cat.can_perform(e.requires or [[q] for q in e.equipment], have)]
        if muscles and not _supports_overlap():
            rows = [e for e in rows
                    if e.muscle in muscles or set(e.secondary or []).intersection(muscles)]
        return Response({
            "exercises": [_exercise_dict(e) for e in rows[:400]],
            "count": len(rows),
            "filtered_by": {"equipment": equipment, "muscles": muscles},
        })

    def post(self, request):
        """Add a movement the catalog doesn't have. Every gym has one."""
        d = request.data or {}
        name = str(d.get("name", "")).strip()
        muscle = str(d.get("muscle", "")).strip()
        if not name:
            return Response({"detail": "name required"}, status=status.HTTP_400_BAD_REQUEST)
        if muscle not in cat.MUSCLE_KEYS:
            return Response({"detail": f"muscle must be one of {cat.MUSCLE_KEYS}"},
                            status=status.HTTP_400_BAD_REQUEST)
        e = Exercise.objects.create(
            key=name.lower().replace(" ", "-")[:60], name=name[:120], owner=request.user,
            muscle=muscle,
            secondary=[m for m in (d.get("secondary") or []) if m in cat.MUSCLE_KEYS],
            equipment=[q for q in (d.get("equipment") or []) if q in cat.EQUIPMENT_KEYS],
            requires=[[q] for q in (d.get("equipment") or []) if q in cat.EQUIPMENT_KEYS],
            pattern=d.get("pattern") if d.get("pattern") in cat.PATTERN_KEYS else "isolation",
            difficulty=(d.get("difficulty") if d.get("difficulty") in cat.DIFFICULTY_KEYS
                        else "beginner"),
            instructions=str(d.get("instructions", ""))[:2000],
        )
        return Response({"exercise": _exercise_dict(e)}, status=status.HTTP_201_CREATED)


def _supports_overlap():
    """JSONField `__overlap` is a Postgres ArrayField feature, not a JSON one —
    so secondary-muscle filtering is done in Python. Kept as a named function so
    the reason is written down rather than rediscovered."""
    return False


class RoutinesView(APIView):
    """GET yours (`?bucket=today`), or `?shared=1` for other members' — StatZ."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.query_params.get("shared") in ("1", "true"):
            ok, resp = _gate(request.user, STATZ_TIERS, "Browsing other members' routines")
            if not ok:
                return resp
            qs = (Routine.objects.filter(is_public=True)
                  .exclude(owner=request.user).select_related("owner")[:100])
            return Response({"routines": [_routine_dict(r) for r in qs], "shared": True})

        qs = Routine.objects.filter(owner=request.user).select_related("owner")
        bucket = request.query_params.get("bucket")
        if bucket in BUCKETS:
            qs = qs.filter(bucket=bucket)
        else:
            qs = qs.exclude(bucket="trash")
        return Response({"routines": [_routine_dict(r) for r in qs[:200]]})

    def post(self, request):
        d = request.data or {}
        name = str(d.get("name", "")).strip()
        if not name:
            return Response({"detail": "name required"}, status=status.HTTP_400_BAD_REQUEST)
        r = Routine.objects.create(
            owner=request.user, name=name[:120],
            description=str(d.get("description", ""))[:500],
            goal=d.get("goal") if d.get("goal") in cat.GOAL_KEYS else "general",
            split=d.get("split") if d.get("split") in cat.SPLITS else "custom",
            difficulty=(d.get("difficulty") if d.get("difficulty") in cat.DIFFICULTY_KEYS
                        else "beginner"),
            days_per_week=max(1, min(int(d.get("days_per_week") or 3), 7)),
            bucket=d.get("bucket") if d.get("bucket") in BUCKETS else "anytime",
            equipment=[q for q in (d.get("equipment") or []) if q in cat.EQUIPMENT_KEYS],
            is_public=bool(d.get("is_public")),
        )
        return Response({"routine": _routine_dict(r, full=True)}, status=status.HTTP_201_CREATED)


class RoutineDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, pk):
        """Yours, or somebody's public one (StatZ only — checked by the caller)."""
        return Routine.objects.filter(pk=pk).select_related("owner").first()

    def get(self, request, pk):
        r = self._get(request, pk)
        if not r:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        if r.owner_id != request.user.id:
            if not r.is_public:
                return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
            ok, resp = _gate(request.user, STATZ_TIERS, "Viewing another member's routine")
            if not ok:
                return resp
        return Response({"routine": _routine_dict(r, full=True)})

    def patch(self, request, pk):
        r = Routine.objects.filter(pk=pk, owner=request.user).first()
        if not r:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        d = request.data or {}
        fields = []
        for field, valid in (("goal", cat.GOAL_KEYS), ("split", cat.SPLITS),
                             ("difficulty", cat.DIFFICULTY_KEYS), ("bucket", BUCKETS)):
            if d.get(field) in valid:
                setattr(r, field, d[field])
                fields.append(field)
        if isinstance(d.get("name"), str) and d["name"].strip():
            r.name = d["name"].strip()[:120]
            fields.append("name")
        if "is_public" in d:
            r.is_public = bool(d["is_public"])
            fields.append("is_public")
        if "scheduled_for" in d:
            try:
                r.scheduled_for = date.fromisoformat(str(d["scheduled_for"])) if d["scheduled_for"] else None
                fields.append("scheduled_for")
            except ValueError:
                return Response({"detail": "scheduled_for must be YYYY-MM-DD"},
                                status=status.HTTP_400_BAD_REQUEST)
        if fields:
            r.save(update_fields=fields + ["updated_at"])
        return Response({"routine": _routine_dict(r, full=True)})

    def delete(self, request, pk):
        r = Routine.objects.filter(pk=pk, owner=request.user).first()
        if not r:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        # Trash first, delete only from trash — that's what a Trash bucket is for.
        if r.bucket != "trash":
            r.bucket = "trash"
            r.save(update_fields=["bucket", "updated_at"])
            return Response({"trashed": pk})
        r.delete()
        return Response({"deleted": pk})


class RoutineExercisesView(APIView):
    """POST an exercise into a routine with its targets."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        r = Routine.objects.filter(pk=pk, owner=request.user).first()
        if not r:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        d = request.data or {}
        ex = Exercise.objects.filter(pk=d.get("exercise_id")).filter(
            Q(owner__isnull=True) | Q(owner=request.user)).first()
        if not ex:
            return Response({"detail": "exercise_id not found"},
                            status=status.HTTP_400_BAD_REQUEST)
        weight = d.get("target_weight")
        try:
            weight = float(weight) if weight not in (None, "") else None
        except (TypeError, ValueError):
            return Response({"detail": "target_weight must be a number"},
                            status=status.HTTP_400_BAD_REQUEST)
        re_ = RoutineExercise.objects.create(
            routine=r, exercise=ex,
            order=int(d.get("order") or r.exercises.count()),
            sets=max(1, min(int(d.get("sets") or 3), 20)),
            reps=max(1, min(int(d.get("reps") or 10), 100)),
            rest_seconds=max(0, min(int(d.get("rest_seconds") or 90), 600)),
            target_weight=weight,
            tempo=str(d.get("tempo", ""))[:16],
            superset_group=str(d.get("superset_group", ""))[:8],
            notes=str(d.get("notes", ""))[:300],
            is_warmup=bool(d.get("is_warmup")),
        )
        r.save(update_fields=["updated_at"])
        return Response({"routine_exercise": _routine_exercise_dict(re_)},
                        status=status.HTTP_201_CREATED)

    def delete(self, request, pk):
        r = Routine.objects.filter(pk=pk, owner=request.user).first()
        row = (RoutineExercise.objects.filter(routine=r,
                                              pk=request.query_params.get("id")).first()
               if r else None)
        if not row:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        row.delete()
        return Response({"deleted": True})


class AIRoutineView(APIView):
    """POST — Corey writes a routine from the catalog you can actually use.

    **Not gated by tier.** A free member spends one of their daily prompts (or
    prepaid PromptZ, or a cent) and gets the same coach — because "the AI told me
    what to train" is the reason to open this app, and locking it away entirely
    means a free member never finds out it's good.

    StatZ runs it without spending a prompt. That's the perk: unlimited, not
    exclusive.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        free_run = tier_of(request.user) in STATZ_TIERS
        cost = 0 if free_run else ai_cost("corey-gpt")
        if cost and not can_afford_ai(request.user, cost, count_daily=True):
            allowance, used, remaining = daily_prompt_state(request.user)
            return Response(
                {"detail": "You're out of daily prompts and balance for this.",
                 "cost_cents": cost, "daily_allowance": allowance,
                 "prompts_remaining": remaining},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )
        d = request.data or {}
        equipment = [q for q in (d.get("equipment") or []) if q in cat.EQUIPMENT_KEYS]
        focus = [m for m in (d.get("muscles") or []) if m in cat.MUSCLE_KEYS]
        plan, err = coach.ai_plan(
            request.user,
            goal=d.get("goal") if d.get("goal") in cat.GOAL_KEYS else "general",
            equipment=equipment,
            days_per_week=max(1, min(int(d.get("days_per_week") or 3), 7)),
            split=d.get("split") if d.get("split") in cat.SPLITS else "custom",
            focus=focus or None,
        )
        if err:
            # Charge nothing when there's no plan — a failed coach run is not a
            # prompt the member spent.
            return Response({"detail": err}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        charged = 0
        if cost:
            # count_daily spends today's free allowance first, then PromptZ, then
            # cash — the same ladder as every other AI run on the platform.
            remaining = charge_ai_usage(request.user, cost, note="BodieZ AI Coach",
                                        count_daily=True)
            charged = cost if remaining is not None else 0

        r = Routine.objects.create(
            owner=request.user, name=str(plan.get("name") or "Coach routine")[:120],
            description="Written by the BodieZ AI Coach.",
            goal=plan.get("goal") if plan.get("goal") in cat.GOAL_KEYS else "general",
            split=plan.get("split") if plan.get("split") in cat.SPLITS else "custom",
            days_per_week=max(1, min(int(plan.get("days_per_week") or 3), 7)),
            bucket="anytime", equipment=equipment,
        )
        by_key = {e.key: e for e in Exercise.objects.filter(
            key__in=[x["key"] for x in plan["exercises"]], owner__isnull=True)}
        for i, item in enumerate(plan["exercises"]):
            ex = by_key.get(item["key"])
            if not ex:
                continue
            RoutineExercise.objects.create(
                routine=r, exercise=ex, order=i,
                sets=max(1, min(int(item.get("sets") or 3), 20)),
                reps=max(1, min(int(item.get("reps") or 10), 100)),
                rest_seconds=max(0, min(int(item.get("rest_seconds") or 90), 600)),
                superset_group=str(item.get("superset_group") or "")[:8],
                notes=str(item.get("notes") or "")[:300],
            )
        allowance, used, remaining = daily_prompt_state(request.user)
        return Response({"routine": _routine_dict(r, full=True),
                         "cost_cents": charged,
                         "daily_prompts": {"allowance": allowance, "used": used,
                                           "remaining": remaining}},
                        status=status.HTTP_201_CREATED)


class SessionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = WorkoutSession.objects.filter(user=request.user).select_related("routine")
        if request.query_params.get("status") in WorkoutSession.STATUSES:
            qs = qs.filter(status=request.query_params["status"])
        return Response({"sessions": [_session_dict(s) for s in qs[:100]]})

    def post(self, request):
        d = request.data or {}
        routine = Routine.objects.filter(pk=d.get("routine_id"), owner=request.user).first()
        location = GymLocation.objects.filter(pk=d.get("location_id"),
                                              owner=request.user).first()
        # One live session at a time. Two open sessions means sets landing in the
        # wrong one, and a log you can't trust is worse than no log.
        existing = WorkoutSession.objects.filter(
            user=request.user, status=WorkoutSession.STATUS_ACTIVE).first()
        if existing:
            return Response({"detail": "You already have a session running.",
                             "session": _session_dict(existing, full=True)},
                            status=status.HTTP_409_CONFLICT)
        s = WorkoutSession.objects.create(
            user=request.user, routine=routine, location=location,
            name=str(d.get("name", ""))[:120])
        return Response({"session": _session_dict(s, full=True)},
                        status=status.HTTP_201_CREATED)


class SessionSetsView(APIView):
    """POST a set. The one screen that has to be fast, so it takes one object."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        s = WorkoutSession.objects.filter(pk=pk, user=request.user).first()
        if not s:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        if s.status != WorkoutSession.STATUS_ACTIVE:
            return Response({"detail": f"that session is {s.status}"},
                            status=status.HTTP_400_BAD_REQUEST)
        d = request.data or {}
        ex = Exercise.objects.filter(pk=d.get("exercise_id")).filter(
            Q(owner__isnull=True) | Q(owner=request.user)).first()
        if not ex:
            return Response({"detail": "exercise_id not found"},
                            status=status.HTTP_400_BAD_REQUEST)

        def num(key, cast=float):
            value = d.get(key)
            try:
                return cast(value) if value not in (None, "") else None
            except (TypeError, ValueError):
                return None

        nth = d.get("set_number")
        if not nth:
            nth = s.sets.filter(exercise=ex).count() + 1
        row = WorkoutSet.objects.create(
            session=s, exercise=ex, set_number=int(nth),
            weight=num("weight"), reps=num("reps", int),
            duration_seconds=num("duration_seconds", int),
            distance_m=num("distance_m", int),
            rpe=num("rpe"), rir=num("rir", int),
            rest_seconds=num("rest_seconds", int),
            is_warmup=bool(d.get("is_warmup")),
            completed=bool(d.get("completed", True)),
            note=str(d.get("note", ""))[:200],
        )
        return Response({"set": _set_dict(row), "session_volume": s.total_volume},
                        status=status.HTTP_201_CREATED)


class SessionFinishView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        s = WorkoutSession.objects.filter(pk=pk, user=request.user).first()
        if not s:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        if s.status != WorkoutSession.STATUS_ACTIVE:
            return Response({"detail": f"already {s.status}"},
                            status=status.HTTP_400_BAD_REQUEST)
        d = request.data or {}
        s.status = (WorkoutSession.STATUS_ABANDONED if d.get("abandon")
                    else WorkoutSession.STATUS_DONE)
        s.ended_at = timezone.now()
        effort = d.get("perceived_effort")
        if effort not in (None, ""):
            try:
                s.perceived_effort = max(1, min(int(effort), 10))
            except (TypeError, ValueError):
                pass
        s.notes = str(d.get("notes", ""))[:500]
        s.save(update_fields=["status", "ended_at", "perceived_effort", "notes"])

        # A finished session belongs in the Logbook. That's the bucket's job.
        if s.status == WorkoutSession.STATUS_DONE:
            BodieZItem.objects.create(
                user=request.user, bucket="logbook", kind="note",
                title=f"{s.name or (s.routine.name if s.routine else 'Freestyle')}"
                      f" · {s.total_volume:g} volume",
                note=s.notes[:1000], routine=s.routine, done=True)
        return Response({"session": _session_dict(s, full=True)})


class ProgressView(APIView):
    """GET the numbers a member actually wants: PRs, volume, streak, consistency."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            days = max(7, min(int(request.query_params.get("days", 90)), 365))
        except (TypeError, ValueError):
            days = 90
        since = timezone.now() - timedelta(days=days)
        sessions = list(WorkoutSession.objects.filter(
            user=request.user, status="done", started_at__gte=since))

        by_week = {}
        for s in sessions:
            week = s.started_at.strftime("%Y-W%V")
            bucket = by_week.setdefault(week, {"week": week, "sessions": 0, "volume": 0.0})
            bucket["sessions"] += 1
            bucket["volume"] += s.total_volume

        prs = (WorkoutSet.objects
               .filter(session__user=request.user, completed=True, is_warmup=False,
                       weight__isnull=False)
               .values("exercise__name")
               .annotate(best=Max("weight"), sets=Count("id"))
               .order_by("-best")[:20])

        # Streak: consecutive days ending today or yesterday. Yesterday counts,
        # because a streak that dies at midnight punishes people for training at
        # 9pm and not opening the app after.
        trained = sorted({s.started_at.date() for s in sessions}, reverse=True)
        streak, cursor = 0, timezone.now().date()
        if trained and (cursor - trained[0]).days <= 1:
            cursor = trained[0]
            for day in trained:
                if day == cursor:
                    streak += 1
                    cursor -= timedelta(days=1)
                elif day < cursor:
                    break

        latest = BodyMetric.objects.filter(user=request.user).first()
        first = BodyMetric.objects.filter(user=request.user).order_by("date").first()
        return Response({
            "window_days": days,
            "sessions": len(sessions),
            "total_volume": round(sum(s.total_volume for s in sessions), 1),
            "total_minutes": sum(s.duration_minutes or 0 for s in sessions),
            "streak_days": streak,
            "by_week": sorted(by_week.values(), key=lambda w: w["week"]),
            "personal_records": [
                {"exercise": p["exercise__name"], "best_weight": float(p["best"]),
                 "sets_logged": p["sets"]} for p in prs
            ],
            "bodyweight": {
                "latest": float(latest.weight) if latest and latest.weight else None,
                "first": float(first.weight) if first and first.weight else None,
                "change": (round(float(latest.weight) - float(first.weight), 1)
                           if latest and first and latest.weight and first.weight else None),
            },
        })


class BodyMapView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            days = max(1, min(int(request.query_params.get("days", 7)), 90))
        except (TypeError, ValueError):
            days = 7
        return Response(coach.body_map(request.user, days=days))


class CoachView(APIView):
    """GET readiness plus an overload verdict for every exercise in a routine."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        out = {"readiness": coach.readiness(request.user), "verdicts": []}
        routine = Routine.objects.filter(pk=request.query_params.get("routine_id"),
                                         owner=request.user).first()
        if routine:
            out["routine"] = routine.name
            for re_ in routine.exercises.select_related("exercise"):
                verdict = coach.overload_verdict(request.user, re_)
                verdict["exercise"] = re_.exercise.name
                verdict["exercise_id"] = re_.exercise_id
                out["verdicts"].append(verdict)
        out["bodymap_summary"] = coach.body_map(request.user)["summary"]
        return Response(out)


class ItemsView(APIView):
    """The Lilith layer. GET `?bucket=inbox`; POST captures a thought."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = BodieZItem.objects.filter(user=request.user)
        bucket = request.query_params.get("bucket")
        if bucket in BUCKETS:
            qs = qs.filter(bucket=bucket)
        else:
            qs = qs.exclude(bucket="trash")
        rows = list(qs[:300])
        counts = dict(BodieZItem.objects.filter(user=request.user)
                      .values_list("bucket").annotate(n=Count("id")))
        return Response({
            "items": [{"id": i.id, "bucket": i.bucket,
                       "bucket_label": BUCKET_LABELS.get(i.bucket, i.bucket),
                       "kind": i.kind, "title": i.title, "note": i.note,
                       "due_at": i.due_at, "routine_id": i.routine_id,
                       "done": i.done, "updated_at": i.updated_at} for i in rows],
            "buckets": [{"key": b, "label": BUCKET_LABELS[b], "count": counts.get(b, 0)}
                        for b in BUCKETS],
        })

    def post(self, request):
        d = request.data or {}
        title = str(d.get("title", "")).strip()
        if not title:
            return Response({"detail": "title required"}, status=status.HTTP_400_BAD_REQUEST)
        due = None
        if d.get("due_at"):
            try:
                due = date.fromisoformat(str(d["due_at"]))
            except ValueError:
                return Response({"detail": "due_at must be YYYY-MM-DD"},
                                status=status.HTTP_400_BAD_REQUEST)
        i = BodieZItem.objects.create(
            user=request.user,
            bucket=d.get("bucket") if d.get("bucket") in BUCKETS else "inbox",
            kind=d.get("kind") if d.get("kind") in BodieZItem.KINDS else "idea",
            title=title[:200], note=str(d.get("note", ""))[:1000], due_at=due,
            routine=Routine.objects.filter(pk=d.get("routine_id"),
                                           owner=request.user).first(),
        )
        return Response({"item": {"id": i.id, "bucket": i.bucket, "title": i.title}},
                        status=status.HTTP_201_CREATED)


class ItemDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        i = BodieZItem.objects.filter(pk=pk, user=request.user).first()
        if not i:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        d = request.data or {}
        fields = []
        if d.get("bucket") in BUCKETS:
            i.bucket = d["bucket"]
            fields.append("bucket")
        if isinstance(d.get("title"), str) and d["title"].strip():
            i.title = d["title"].strip()[:200]
            fields.append("title")
        if "note" in d:
            i.note = str(d["note"])[:1000]
            fields.append("note")
        if "done" in d:
            i.done = bool(d["done"])
            fields.append("done")
        if fields:
            i.save(update_fields=fields + ["updated_at"])
        return Response({"item": {"id": i.id, "bucket": i.bucket, "title": i.title,
                                  "done": i.done}})

    def delete(self, request, pk):
        i = BodieZItem.objects.filter(pk=pk, user=request.user).first()
        if not i:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        if i.bucket != "trash":
            i.bucket = "trash"
            i.save(update_fields=["bucket", "updated_at"])
            return Response({"trashed": pk})
        i.delete()
        return Response({"deleted": pk})


class MetricsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = BodyMetric.objects.filter(user=request.user)[:365]
        return Response({"metrics": [
            {"date": m.date, **{f: (float(getattr(m, f)) if getattr(m, f) is not None else None)
                                for f in ("weight", "body_fat", "neck", "shoulders", "chest",
                                          "waist", "hips", "arms", "thighs", "calves")},
             "note": m.note}
            for m in rows]})

    def post(self, request):
        d = request.data or {}
        try:
            when = date.fromisoformat(str(d.get("date"))) if d.get("date") else date.today()
        except ValueError:
            return Response({"detail": "date must be YYYY-MM-DD"},
                            status=status.HTTP_400_BAD_REQUEST)

        def num(key):
            value = d.get(key)
            try:
                return float(value) if value not in (None, "") else None
            except (TypeError, ValueError):
                return None

        m, created = BodyMetric.objects.update_or_create(
            user=request.user, date=when,
            defaults={f: num(f) for f in ("weight", "body_fat", "neck", "shoulders", "chest",
                                          "waist", "hips", "arms", "thighs", "calves")}
            | {"note": str(d.get("note", ""))[:300]},
        )
        return Response({"date": m.date, "created": created},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class GoalsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = FitnessGoal.objects.filter(user=request.user)[:100]
        return Response({"goals": [
            {"id": g.id, "goal_type": g.goal_type, "title": g.title,
             "target_value": float(g.target_value) if g.target_value is not None else None,
             "current_value": float(g.current_value) if g.current_value is not None else None,
             "unit": g.unit, "deadline": g.deadline, "status": g.status,
             "progress_pct": g.progress_pct} for g in rows]})

    def post(self, request):
        d = request.data or {}
        title = str(d.get("title", "")).strip()
        if not title:
            return Response({"detail": "title required"}, status=status.HTTP_400_BAD_REQUEST)
        deadline = None
        if d.get("deadline"):
            try:
                deadline = date.fromisoformat(str(d["deadline"]))
            except ValueError:
                return Response({"detail": "deadline must be YYYY-MM-DD"},
                                status=status.HTTP_400_BAD_REQUEST)

        def num(key):
            try:
                return float(d[key]) if d.get(key) not in (None, "") else None
            except (TypeError, ValueError):
                return None

        g = FitnessGoal.objects.create(
            user=request.user, title=title[:140],
            goal_type=(d.get("goal_type") if d.get("goal_type") in FitnessGoal.TYPES
                       else FitnessGoal.TYPE_HABIT),
            target_value=num("target_value"), current_value=num("current_value"),
            unit=str(d.get("unit", ""))[:16], deadline=deadline,
        )
        return Response({"goal": {"id": g.id, "title": g.title,
                                  "progress_pct": g.progress_pct}},
                        status=status.HTTP_201_CREATED)


class LocationsView(APIView):
    """PREMIUM. A room, its equipment, and what it can't train."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        ok, resp = _gate(request.user, PREMIUM_TIERS, "Gym locations")
        if not ok:
            return resp
        rows = GymLocation.objects.filter(owner=request.user)[:50]
        return Response({"locations": [
            {"id": g.id, "name": g.name, "address": g.address, "equipment": g.equipment,
             "is_default": g.is_default, "muscle_coverage": g.muscle_coverage,
             "gaps": g.gaps} for g in rows]})

    def post(self, request):
        ok, resp = _gate(request.user, PREMIUM_TIERS, "Gym locations")
        if not ok:
            return resp
        d = request.data or {}
        name = str(d.get("name", "")).strip()
        if not name:
            return Response({"detail": "name required"}, status=status.HTTP_400_BAD_REQUEST)
        if GymLocation.objects.filter(owner=request.user, name=name[:120]).exists():
            return Response({"detail": f"you already have a location called {name!r}"},
                            status=status.HTTP_409_CONFLICT)
        g = GymLocation.objects.create(
            owner=request.user, name=name[:120],
            address=str(d.get("address", ""))[:250],
            equipment=[q for q in (d.get("equipment") or []) if q in cat.EQUIPMENT_KEYS],
            is_default=bool(d.get("is_default")),
        )
        if g.is_default:
            GymLocation.objects.filter(owner=request.user).exclude(pk=g.pk).update(
                is_default=False)
        return Response({"location": {"id": g.id, "name": g.name,
                                      "equipment": g.equipment,
                                      "muscle_coverage": g.muscle_coverage,
                                      "gaps": g.gaps}},
                        status=status.HTTP_201_CREATED)


class LocationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        ok, resp = _gate(request.user, PREMIUM_TIERS, "Gym locations")
        if not ok:
            return resp
        g = GymLocation.objects.filter(pk=pk, owner=request.user).first()
        if not g:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        g.delete()
        return Response({"deleted": pk})
