"""Auto-trim: a lift left part-done when the member moves on reads done (3/5 -> 3/3) — counted by tier.

The trimming itself is the client's (`src/autoTrim.js` in the frontend: when, and what it never touches). This module is
the number that goes with it, the same shape as `bodiez_float`:

* **A tier says how OFTEN, never whether.** Free 3, Premium 6, StatZ 12 lifts trimmed a rolling 24 hours
  (`catalog.TIER_LIMITS["bodiez_autotrim"]`, Corey's numbers). Trimming a lift by hand (tapping its sets) is free and
  uncounted at every tier; what a tier buys is how often BodieZ does it FOR them. Past the number nothing is trimmed and
  the lift reads 3/5 as it always did.
* **A lift counts once per session.** A row per (session, lift): a lift trimmed, come back to and trimmed again is one
  use, and two requests at once write one row (`unique_together`).
* **Stated before it happens.** `state()` serves used / left / the next plan's number so the switch can say "2 of 3 left
  today" BEFORE a set is logged. It costs no ⚡, 🍥 or 🏷️, and a refused trim writes nothing.
* **Only a live session of your own**, and today only: the routine is never touched and the end-of-session report still
  counts the routine's plan.
"""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import limits_for
from .models import BodieZAutoTrim, BodieZSession, membership_for

WINDOW_HOURS = 24
TIERS = ("free", "premium", "statz")
KEY = "bodiez_autotrim"
MAX_PER_REQUEST = 20        # a plan has no more lifts than this worth trimming at once


def cap_for(user):
    """This member's number: an int, or None for unlimited."""
    return limits_for(membership_for(user).tier).get(KEY)


def used_since(user, now=None):
    now = now or timezone.now()
    return BodieZAutoTrim.objects.filter(user=user, created_at__gte=now - timedelta(hours=WINDOW_HOURS)).count()


def _next_number(user):
    """What the NEXT plan up allows (None = unlimited), or False on the top plan."""
    tier = membership_for(user).tier
    if tier == "free":
        return limits_for("premium").get(KEY)
    if tier == "premium":
        return limits_for("statz").get(KEY)
    return False


def state(user):
    cap = cap_for(user)
    used = used_since(user)
    return {
        "limit": cap,                      # None = unlimited
        "used": used,
        "left": None if cap is None else max(0, cap - used),
        "unlimited": cap is None,
        "window_hours": WINDOW_HOURS,
        "next_limit": _next_number(user),  # False on the top plan; None = unlimited
        "ladder": {t: limits_for(t).get(KEY) for t in TIERS},
        "cost": "Free — no ⚡, 🍥 or 🏷️. Each lift trimmed for you uses one of today's.",
        "note": ("Tapping a lift's sets to change them yourself is free and never counted. A lift counts once a "
                 "session however often it is trimmed, and your routine is never changed."),
    }


def _ids(raw):
    out = []
    for x in raw if isinstance(raw, list) else []:
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if n > 0 and n not in out:
            out.append(n)
    return out[:MAX_PER_REQUEST]


def grant(user, session, exercise_ids):
    """(granted, refused) — lifts already trimmed in this session are free; new ones take today's count in order."""
    have = set(BodieZAutoTrim.objects.filter(session=session, exercise_id__in=exercise_ids)
               .values_list("exercise_id", flat=True))
    granted = [i for i in exercise_ids if i in have]
    fresh = [i for i in exercise_ids if i not in have]
    cap = cap_for(user)
    left = None if cap is None else max(0, cap - used_since(user))
    refused = []
    for i in fresh:
        if left is not None and left <= 0:
            refused.append(i)
            continue
        try:
            with transaction.atomic():
                BodieZAutoTrim.objects.create(user=user, session=session, exercise_id=i)
        except IntegrityError:
            pass                            # another request recorded it first: same lift, one use
        else:
            if left is not None:
                left -= 1
        granted.append(i)
    return granted, refused


class BodieZAutoTrimStateView(APIView):
    """GET /api/economy/bodiez/autotrim/ — the number, before any set is logged."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(state(request.user))


class BodieZSessionAutoTrimView(APIView):
    """POST /api/economy/bodiez/sessions/<id>/autotrim/ {exercise_ids} — which of these lifts may be trimmed now."""
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        sess = BodieZSession.objects.filter(id=session_id, user=request.user).first()
        if sess is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        if sess.ended_at or sess.backfilled:
            return Response({"detail": "Only a session you are logging right now is trimmed."},
                            status=status.HTTP_409_CONFLICT)
        ids = _ids((request.data or {}).get("exercise_ids"))
        granted, refused = grant(request.user, sess, ids)
        st = state(request.user)
        out = {"granted": granted, "refused": refused, "autotrim": st}
        if refused:
            nxt = st["next_limit"]
            more = ("" if nxt is False else
                    f" The next plan up trims {'any number' if nxt is None else nxt} a day.")
            out["detail"] = (f"Auto-trim has done {st['used']} of {st['limit']} lifts in the last {WINDOW_HOURS} hours — "
                             f"your plan's number, so {len(refused)} {'lift was' if len(refused) == 1 else 'lifts were'} "
                             f"left as planned. Tap its sets to trim it yourself, free.{more} Nothing was charged.")
        return Response(out)
