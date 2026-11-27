"""PaneZ: opening a split page counts against the plan's times a day (`split_opens`: Free 3, Premium 6, StatZ
12 — Corey's numbers), over a rolling 24 hours like BodieZ's float. A tier says how OFTEN, never whether: every
plan can split. Swapping the app in a split already open is not a new open (the client only asks for a first open).
It costs no ⚡ 🍥 🏷️; a refused open says when the next one frees up."""
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import higher_tiers_keep, limits_for
from .models import PaneOpen, membership_for

WINDOW = timedelta(hours=24)
# The tier above each tier that holds a split count. StatZ is the top one, so it has no next.
NEXT_TIER = {"free": "premium", "premium": "statz"}


def state(user):
    tier = membership_for(user).tier
    limit = limits_for(tier).get("split_opens")
    since = timezone.now() - WINDOW
    recent = list(PaneOpen.objects.filter(user=user, created_at__gte=since).order_by("created_at").values_list("created_at", flat=True))
    left = None if limit is None else max(0, limit - len(recent))
    frees = None
    if limit is not None and left == 0 and recent:
        frees = max(0, int((recent[0] + WINDOW - timezone.now()).total_seconds()))
    # False on the top plan: there is no next one to name. None is reserved for "unlimited", as everywhere else.
    return {"limit": limit, "used": len(recent), "left": left, "seconds_until_next": frees,
            "next_limit": limits_for(NEXT_TIER[tier]).get("split_opens") if tier in NEXT_TIER else False}


def _wait(sec):
    h, m = divmod(max(1, sec) // 60, 60)
    return f"{h} h {m} min" if h else f"{max(1, m)} min"


class PaneZView(APIView):
    """GET: how many split pages are left today. POST {app}: open one, or 429 with when the next frees up."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(state(request.user))

    def post(self, request):
        st = state(request.user)
        if st["left"] == 0:
            words = higher_tiers_keep(lambda t: limits_for(t).get("split_opens"),
                                      membership_for(request.user).tier, verb="opens", unit=" a day")
            return Response({**st, "detail": f"You've opened your {st['limit']} split pages for today — the next frees up in "
                                              f"{_wait(st['seconds_until_next'] or 0)}."
                                              + (f" {words}." if words else "")},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)
        PaneOpen.objects.create(user=request.user, app_key=str((request.data or {}).get("app") or "")[:32])
        return Response(state(request.user))
