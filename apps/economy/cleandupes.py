"""Clean ConnectZ's duplicate finder: open on every plan, a few times a day.

The finder runs in the Windows app on the member's own files and nothing about them is sent here. What the server holds is
only the number: **a tier says how OFTEN, never whether** — Free 3, Premium 6, StatZ 12 scans in a rolling 24 hours
(`catalog.TIER_LIMITS["clean_dupe_runs"]`, Corey's numbers). It costs no ⚡, 🍥 or 🏷️, and the screen reads `state()` BEFORE
the button is pressed, because a limit is a price.

* **A scan counts when it has finished.** The screen asks `GET` first (to say "2 of 3 left today" and to refuse before any
  work), scans, then `POST`s to record it. A cancelled or failed scan is never posted, so it costs nothing.
* **The record is the gate.** `POST` refuses past the number, writing nothing, so a client that skipped the check still
  cannot run more — it can only run one it will not be shown results for, and the screen says why.
* **Rolling, not a calendar day** (a UTC midnight is early evening in New York), counted as rows, so nothing drifts.
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import limits_for
from .models import CleanDupeRun, membership_for

WINDOW_HOURS = 24
KEY = "clean_dupe_runs"


def cap_for(user):
    """This member's number: an int, or None for unlimited."""
    return limits_for(membership_for(user).tier).get(KEY)


def used_since(user, now=None):
    now = now or timezone.now()
    return CleanDupeRun.objects.filter(user=user, at__gte=now - timedelta(hours=WINDOW_HOURS)).count()


def _next(user):
    tier = membership_for(user).tier
    if tier == "free":
        return limits_for("premium").get(KEY)
    if tier == "premium":
        return limits_for("statz").get(KEY)
    return False


def state(user):
    cap, used = cap_for(user), used_since(user)
    nxt = _next(user)
    return {
        "limit": cap, "used": used, "unlimited": cap is None,
        "left": None if cap is None else max(0, cap - used),
        "can": cap is None or used < cap,
        "next_limit": nxt,                 # False on the top plan; None = unlimited
        # Approaching the number (one left or none): the screen offers the upgrade THEN, not before — a plan pitch on a
        # member who has plenty left is noise. Where it lands is the control, not the tab (`goToSpot`).
        "near": cap is not None and used >= cap - 1,
        "upgrade": ({"tab": "membershipz", "target": "membershipz-plans"} if nxt is not False else None),
        "window_hours": WINDOW_HOURS,
        "cost": "Free — no ⚡, 🍥 or 🏷️. A scan that finishes uses one of today's.",
        "note": "Cancelled or failed scans aren't counted. Nothing about your files is sent anywhere.",
    }


class CleanDupesView(APIView):
    """GET the number, before the press. POST records one finished scan (refused past the number, nothing written)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(state(request.user))

    def post(self, request):
        st = state(request.user)
        if not st["can"]:
            nxt = st["next_limit"]
            more = "" if nxt is False else f" The next plan up allows {'any number' if nxt is None else nxt} a day."
            return Response({"detail": f"You've run {st['used']} of {st['limit']} duplicate scans in the last "
                                       f"{WINDOW_HOURS} hours — your plan's number.{more} Nothing was charged.",
                             "dupes": st}, status=status.HTTP_403_FORBIDDEN)
        CleanDupeRun.objects.create(user=request.user)
        return Response({"dupes": state(request.user)}, status=status.HTTP_201_CREATED)
