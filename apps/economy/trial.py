"""Trial Boss Take — one scored take, no account.

The strongest thing Music ConnectZ can hand a stranger is a number about
THEMSELVES. Reading about a vocal coach persuades nobody; being told your take
is a 6 and exactly which two things cost you the other four is a different
conversation. So the door is a take, not a tour.

Two rules hold it together:

1. **It is graded by the same rubric a member's take is** (`score_take`). A
   trial that grades easier is a lie the first real take exposes.
2. **It is capped, hard.** An unauthenticated endpoint that spends real money
   is a bill anybody with curl can run up. One per address per day, plus a
   global daily ceiling that refuses rather than overspends.

Nothing here moves a member resource — a visitor has no wallet, so there is no
⚡/🍥/🏷️ to state. The cost is ours; the gain is theirs, and the response says
so before asking them to sign up.
"""
import secrets

from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .gemini import _key
from .instruments import DIFFICULTIES, profile_for_app
from .models import (
    TRIAL_CLAIM_DAYS,
    TRIAL_MAX_MB,
    TRIAL_PER_IP_HOURS,
    TrialTake,
    trial_daily_cap,
)
from .vocalcoach import score_take


def client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return (fwd.split(",")[0].strip() or "")[:64]
    return (request.META.get("REMOTE_ADDR") or "")[:64]


def trial_state(ip):
    """(taken_today_globally, this_address_already_had_one)."""
    from datetime import timedelta
    now = timezone.now()
    today = TrialTake.objects.filter(created_at__gte=now - timedelta(hours=24)).count()
    mine = bool(ip) and TrialTake.objects.filter(
        ip=ip, created_at__gte=now - timedelta(hours=TRIAL_PER_IP_HOURS)
    ).exists()
    return today, mine


class TrialCoachView(APIView):
    """GET what the trial offers and whether it's available; POST one take.

    `app_key` is bound per-route, exactly as SingZCoachView's is, so SingZ and
    RapZ both get a door without either owning it.
    """

    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]
    app_key = "singz"

    def get(self, request):
        profile = profile_for_app(self.app_key)
        today, mine = trial_state(client_ip(request))
        cap = trial_daily_cap()
        return Response({
            "app_key": self.app_key,
            "label": profile["label"],
            "configured": bool(_key()),
            # Free to them, and it costs them nothing they own — say so plainly
            # rather than letting them wonder what they're about to spend.
            "free": True,
            "available": bool(_key()) and not mine and today < cap,
            "already_used": mine,
            "per_address": f"one free take every {TRIAL_PER_IP_HOURS} hours",
            "max_mb": TRIAL_MAX_MB,
            "claim_days": TRIAL_CLAIM_DAYS,
            "scores": profile["scores"],
            "range_label": profile["range_label"],
            "ranges": [{"key": k, "label": l} for k, l in profile["ranges"]],
            "difficulties": DIFFICULTIES,
            "caveat": profile["caveat"],
        })

    def post(self, request):
        ip = client_ip(request)
        today, mine = trial_state(ip)
        if mine:
            return Response(
                {"detail": "You've had your free take for today. Make an account and the coach is yours whenever you want it.",
                 "already_used": True},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if today >= trial_daily_cap():
            return Response(
                {"detail": "Free takes are all spoken for today — they're limited so we can keep giving them away. Try tomorrow, or make an account.",
                 "retry_tomorrow": True},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        f = request.FILES.get("take")
        if not f:
            return Response({"detail": "Record or attach a take first."},
                            status=status.HTTP_400_BAD_REQUEST)
        content_type = (getattr(f, "content_type", "") or "").lower()
        if not (content_type.startswith("audio/") or content_type.startswith("video/")):
            return Response({"detail": "That isn't audio or video. Record a take, or attach an "
                                       "audio or video file."},
                            status=status.HTTP_400_BAD_REQUEST)
        if f.size > TRIAL_MAX_MB * 1024 * 1024:
            return Response({"detail": f"That take is too big for a free run — keep it under {TRIAL_MAX_MB}MB."},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        data = request.data
        payload, err = score_take(
            self.app_key, f, content_type,
            genre=data.get("genre"), target=data.get("range"),
            difficulty=data.get("difficulty"),
        )
        if err:
            # A take the coach couldn't read doesn't burn the visitor's one
            # free run — nothing is written, so they can try again.
            body, code = err
            return Response(body, status=code)

        take = TrialTake.objects.create(
            token=secrets.token_urlsafe(24), app_key=self.app_key, ip=ip, result=payload,
        )
        return Response({
            **payload,
            "trial": True,
            "cost_cents": 0,
            "claim_token": take.token,
            # Not a dead end: the take they just made opens inside the app once
            # they join, rather than vanishing with the tab.
            "open_in": f"{self.app_key}:coach",
            "claim_hint": f"Sign up within {TRIAL_CLAIM_DAYS} days and this take is saved to your account.",
        }, status=status.HTTP_201_CREATED)


class TrialTakeDetailView(APIView):
    """GET /api/trial/<token>/ — read a trial take back.

    Lets the client survive a reload before signup, and lets a freshly claimed
    take render inside the app afterwards.
    """

    permission_classes = [AllowAny]

    def get(self, request, token):
        take = TrialTake.objects.filter(token=str(token)[:64]).first()
        if not take:
            return Response({"detail": "That trial take has expired or never existed."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response({
            **(take.result or {}),
            "app_key": take.app_key,
            "trial": True,
            "claimed": bool(take.claimed_by_id),
            "open_in": f"{take.app_key}:coach",
            "created_at": take.created_at.isoformat(),
        })
