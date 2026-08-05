"""ObservationZ — HabitZ 🫠, CodeZ 🧩, PathZ 🛤️, MistakeZ 😢.

Four tabs over one table. Notice something happen, tally it, and say which
repeats are worth a member's attention.

Significance is arithmetic, not a model call: how often, and how recently.
"AI-detected" would sound better and mean less — a number nobody can explain is
the same failure as a skill claiming 26 years for 14 played.
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (OBSERVATION_KINDS, SIGNIFICANT_AT, Observation,
                     ObservationConsent, observing)

KIND_META = {
    "habit": {"emoji": "🫠", "label": "HabitZ", "blurb": "Things you repeat — noted because they clearly matter to you."},
    "code": {"emoji": "🧩", "label": "CodeZ", "blurb": "Acronyms, typos and slang you type that mean something else."},
    "path": {"emoji": "🛤️", "label": "PathZ", "blurb": "Routes you take, across every device you use."},
    "mistake": {"emoji": "😢", "label": "MistakeZ", "blurb": "Errors the AI made — kept so it stops making them."},
}
KINDS = [k for k, _ in OBSERVATION_KINDS]


def _significance(obs, now):
    """0-10. Frequency carries it; going cold pulls it back down.

    Explainable on purpose — a member can be told "12 times, last seen
    yesterday" and check the number themselves.
    """
    if obs.count < SIGNIFICANT_AT:
        return 0
    freq = min(7, obs.count // 3)
    days = max(0, (now - obs.last_seen).days)
    recency = 3 if days <= 1 else 2 if days <= 7 else 1 if days <= 30 else 0
    return min(10, freq + recency)


def _row(obs, now):
    sig = _significance(obs, now)
    return {
        "id": obs.id, "kind": obs.kind, "key": obs.key,
        "label": obs.label or obs.key, "count": obs.count,
        "first_seen": obs.first_seen, "last_seen": obs.last_seen,
        # Where this can be opened to edit or analyse. The crux: a thing
        # noticed in one app is actionable in the app it came from.
        "app_key": obs.app_key, "target": obs.target,
        "open_in": obs.app_key or None,
        "significance": sig,
        "significant": sig > 0,
        "dismissed": obs.dismissed,
    }


class ObservationZView(APIView):
    """GET  ?kind=habit&order=desc|asc  → tallies, most-repeated first.
    POST {kind, key, dismissed}         → stop surfacing one.
    DELETE ?kind=habit                  → forget everything of that kind.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        kind = (request.query_params.get("kind") or "").lower()
        qs = request.user.observations.all()
        if kind in KINDS:
            qs = qs.filter(kind=kind)
        if request.query_params.get("include_dismissed") not in ("1", "true"):
            qs = qs.filter(dismissed=False)
        if (request.query_params.get("order") or "desc").lower() == "asc":
            qs = qs.order_by("count", "last_seen")

        now = timezone.now()
        rows = [_row(o, now) for o in qs[:300]]
        return Response({
            "observations": rows,
            "significant": sum(1 for r in rows if r["significant"]),
            "threshold": SIGNIFICANT_AT,
            "kinds": [
                {"key": k, **KIND_META[k], "watching": observing(request.user, k),
                 "count": request.user.observations.filter(kind=k, dismissed=False).count()}
                for k in KINDS
            ],
        })

    def post(self, request):
        d = request.data or {}
        obs = request.user.observations.filter(
            kind=str(d.get("kind", "")).lower(), key=str(d.get("key", ""))).first()
        if not obs:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        obs.dismissed = bool(d.get("dismissed", True))
        obs.save(update_fields=["dismissed"])
        return Response(_row(obs, timezone.now()))

    def delete(self, request):
        """Forget. Not 'hide' — the rows go."""
        kind = (request.query_params.get("kind") or "").lower()
        qs = request.user.observations.all()
        if kind in KINDS:
            qs = qs.filter(kind=kind)
        n = qs.count()
        qs.delete()
        return Response({"forgotten": n, "kind": kind or "all"})


class ObservationConsentView(APIView):
    """GET → what's being watched. POST {kind, enabled} → change it.

    Off unless asked for. Turning a kind OFF forgets what it collected, because
    leaving it behind means the member revoked consent and we kept the data.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"kinds": [
            {"key": k, **KIND_META[k], "watching": observing(request.user, k)} for k in KINDS
        ]})

    def post(self, request):
        d = request.data or {}
        kind = str(d.get("kind", "")).lower()
        if kind not in KINDS:
            return Response({"detail": f"kind must be one of {KINDS}"},
                            status=status.HTTP_400_BAD_REQUEST)
        enabled = bool(d.get("enabled"))
        ObservationConsent.objects.update_or_create(
            user=request.user, kind=kind, defaults={"enabled": enabled})
        forgotten = 0
        if not enabled:
            forgotten = request.user.observations.filter(kind=kind).count()
            request.user.observations.filter(kind=kind).delete()
        return Response({"kind": kind, "watching": enabled, "forgotten": forgotten})
