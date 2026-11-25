"""HealthZ — a member's own sleep log and the conditions they say they have.

Two things, and a line drawn around both:

* **Entered, never inferred.** Sleep is hours the member typed. A condition is a name the
  member typed. Nothing here is estimated from activity, takes, posts or messages — "we
  detected you sleep badly" would be `directz_ai_rating` wearing a stethoscope.
* **Not a diagnosis, and it says so.** HealthZ records what the member tells it. It does not
  diagnose, suggest a diagnosis, rate anyone's health or recommend treatment, and the screen
  says that before anything is typed (`NOTE`).

Private to the owner by default: every query filters on `request.user`, no other module reads
these tables (`test_healthz` fails if one does), and both rows cascade with the account.

The one exception is a choice, made condition by condition: `shared` lets an ADULT who searches
Social ConnectZ for that condition find the member. `shared_map` is the only reader, it fails
closed (a minor owner, a minor searcher or a blocked pair reads as nothing), and the search
only ever reports the conditions the searcher asked about.
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


SHARE_MINOR_REASON = ("Letting other members find you by a condition is for members 18 and over. "
                      "Nothing was shared; the condition stays private to you.")


def _may_share(user):
    from .models import profile_for, profile_is_minor
    return not profile_is_minor(profile_for(user))


def shared_map(profiles, viewer):
    """{user_id: [condition names]} the `viewer` is entitled to search on.

    Fails closed, in both directions: a minor viewer reads nothing, a minor owner is never
    included, and only conditions the owner marked `shared` count. Blocks are the caller's
    (the member search has already dropped them). One query for the whole page."""
    from .models import adult_only_reason, profile_is_minor
    if viewer is None or not getattr(viewer, "is_authenticated", False) or adult_only_reason(viewer):
        return {}
    ids = [p.user_id for p in profiles if not profile_is_minor(p)]
    out = {}
    for uid, name in HealthCondition.objects.filter(user_id__in=ids, shared=True).values_list("user_id", "name"):
        out.setdefault(uid, []).append(name)
    return out


def _sleep_dict(s):
    return {"id": s.id, "night": s.night.isoformat(), "hours": s.hours, "quality": s.quality, "note": s.note}


def _cond_dict(c):
    return {"id": c.id, "name": c.name, "since_year": c.since_year, "note": c.note, "shared": c.shared}


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
        shared = bool(d.get("shared"))
        if shared and not _may_share(request.user):
            return Response({"detail": SHARE_MINOR_REASON, "adult_only": True}, status=status.HTTP_403_FORBIDDEN)
        HealthCondition.objects.create(user=request.user, name=name, since_year=since,
                                       note=str(d.get("note") or "")[:500], shared=shared)
        return Response(board(request.user), status=status.HTTP_201_CREATED)


class ConditionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        HealthCondition.objects.filter(pk=pk, user=request.user).delete()
        return Response(board(request.user))

    def patch(self, request, pk):
        """{shared: bool} — the only thing that can change after it is written."""
        c = HealthCondition.objects.filter(pk=pk, user=request.user).first()
        if not c:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        shared = bool(request.data.get("shared"))
        if shared and not _may_share(request.user):
            return Response({"detail": SHARE_MINOR_REASON, "adult_only": True}, status=status.HTTP_403_FORBIDDEN)
        c.shared = shared
        c.save(update_fields=["shared"])
        return Response(board(request.user))
