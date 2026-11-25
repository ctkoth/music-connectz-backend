"""HealthZ — a member's own sleep log and the conditions they say they have.

Two things, and a line drawn around both:

* **Entered, never inferred.** Sleep is hours the member typed. A condition is a name the
  member typed. Nothing here is estimated from activity, takes, posts or messages — "we
  detected you sleep badly" would be `directz_ai_rating` wearing a stethoscope.
* **Not a diagnosis, and it says so.** HealthZ records what the member tells it. It does not
  diagnose, suggest a diagnosis, rate anyone's health or recommend treatment, and the screen
  says that before anything is typed (`NOTE`).

Private to the owner, always: every query filters on `request.user`, no other module reads
these tables (`test_healthz` fails if one does), and both rows cascade with the account.
Arithmetic only: the seven-day average is a mean of the nights logged, and is None — never 0 —
when none were.
"""
import datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import HealthCondition, SleepLog

SLEEP_KEPT = 90          # nights returned
MAX_CONDITIONS = 100

NOTE = ("This is your own record, private to you. HealthZ doesn't diagnose, suggest a diagnosis, "
        "score your health or recommend treatment — it keeps what you tell it. For anything medical, "
        "talk to a clinician.")


def _sleep_dict(s):
    return {"id": s.id, "night": s.night.isoformat(), "hours": s.hours, "quality": s.quality, "note": s.note}


def _cond_dict(c):
    return {"id": c.id, "name": c.name, "since_year": c.since_year, "note": c.note}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def board(user):
    rows = list(SleepLog.objects.filter(user=user)[:SLEEP_KEPT])
    week_ago = timezone.localdate() - datetime.timedelta(days=7)
    week = [r.hours for r in rows if r.night > week_ago]
    return {
        "note": NOTE,
        "sleep": [_sleep_dict(r) for r in rows],
        "avg_hours_7d": round(sum(week) / len(week), 1) if week else None,
        "nights_7d": len(week),
        "conditions": [_cond_dict(c) for c in HealthCondition.objects.filter(user=user)],
        "private": True,
    }


class HealthZView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(board(request.user))


class SleepView(APIView):
    """POST {night, hours, quality?, note?} — one row per night; logging a night again edits it."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        d = request.data
        try:
            night = datetime.date.fromisoformat(str(d.get("night") or timezone.localdate().isoformat()))
        except ValueError:
            return Response({"detail": "night must be a date (YYYY-MM-DD)."}, status=status.HTTP_400_BAD_REQUEST)
        if night > timezone.localdate() + datetime.timedelta(days=1):
            return Response({"detail": "That night hasn't happened yet."}, status=status.HTTP_400_BAD_REQUEST)
        hours = _num(d.get("hours"))
        if hours is None or not (0 < hours <= 24):
            return Response({"detail": "hours must be more than 0 and at most 24."}, status=status.HTTP_400_BAD_REQUEST)
        quality = d.get("quality")
        if quality not in (None, ""):
            try:
                quality = int(quality)
            except (TypeError, ValueError):
                quality = 0
            if not 1 <= quality <= 5:
                return Response({"detail": "quality is 1 to 5, or leave it blank."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            quality = None
        SleepLog.objects.update_or_create(
            user=request.user, night=night,
            defaults={"hours": round(hours, 2), "quality": quality, "note": str(d.get("note") or "")[:300]})
        return Response(board(request.user), status=status.HTTP_201_CREATED)


class SleepDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        SleepLog.objects.filter(pk=pk, user=request.user).delete()
        return Response(board(request.user))


class ConditionView(APIView):
    """POST {name, since_year?, note?}."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        d = request.data
        name = str(d.get("name") or "").strip()[:120]
        if not name:
            return Response({"detail": "Say what it is, in your own words."}, status=status.HTTP_400_BAD_REQUEST)
        if HealthCondition.objects.filter(user=request.user).count() >= MAX_CONDITIONS:
            return Response({"detail": f"That's {MAX_CONDITIONS} — remove one to add another."},
                            status=status.HTTP_400_BAD_REQUEST)
        since = d.get("since_year")
        if since in (None, ""):
            since = None
        else:
            try:
                since = int(since)
            except (TypeError, ValueError):
                since = 0
            if not 1900 <= since <= timezone.localdate().year:
                return Response({"detail": "since_year must be a real year, or leave it blank."},
                                status=status.HTTP_400_BAD_REQUEST)
        HealthCondition.objects.create(user=request.user, name=name, since_year=since,
                                       note=str(d.get("note") or "")[:500])
        return Response(board(request.user), status=status.HTTP_201_CREATED)


class ConditionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        HealthCondition.objects.filter(pk=pk, user=request.user).delete()
        return Response(board(request.user))
