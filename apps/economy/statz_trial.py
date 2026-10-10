"""The StatZ sample: one hour of StatZ-only features, once per member.

FunnelZ's rules hold here because this is an offer: the deadline is real (the
server's `ends_at`, never a client timer that resets on reload), it ends when
it says it ends, and it is offered only to somebody it is true for — a member
who isn't StatZ and has never had one. One per account is also why the
one-person-one-account rule matters to it: a second account would be a second
sample.

It unlocks only what can honestly switch off again when the hour is up:
searching keys by mood and framing whole pages as widgets. Saving a StatZ
coach voice is NOT in it — that is a standing preference, and a sample that
left one behind would be a permanent grant wearing a timer.
"""
from datetime import timedelta

from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import TIER_DEBUG, TIER_STATZ
from .models import StatzTrial, membership_for

TRIAL_MINUTES = 60
FEATURES = [
    {"key": "mood_search", "label": "Search keys by mood", "tab": "instrumentalconnectz", "target": "instrumental-mood"},
    {"key": "page_widgets", "label": "Open any scanned site as a widget", "tab": "profilez", "target": "widgets"},
    {"key": "advanced_horoscope", "label": "The advanced daily horoscope", "tab": "zodiacz", "target": "zodiacz-advanced"},
    # BodieZ. The Coach CHOOSING a superset partner, and a rest alert that reaches a
    # locked phone. Both can honestly switch off when the hour is up: a routine the
    # Coach already paired stays paired (it is the member's), and linking two lifts
    # by hand was never gated.
    {"key": "coach_pairing", "label": "Coach supersets: compound + isolation, push + pull", "tab": "bodiez", "target": "bodiez-pairing"},
    {"key": "rest_alerts", "label": "Rest alerts and a screen that stays awake", "tab": "bodiez", "target": "bodiez-rest-alerts"},
]
UPGRADE = {"tab": "membershipz", "target": "membershipz-plans", "label": "Upgrade to StatZ"}


def _trial(user):
    return StatzTrial.objects.filter(user=user).first()


def trial_active(user):
    t = _trial(user)
    return bool(t and t.ends_at > timezone.now())


def has_statz(user):
    """StatZ-only features: the real tier, or a sample that hasn't ended."""
    return membership_for(user).tier in (TIER_STATZ, TIER_DEBUG) or trial_active(user)


def feature_tier(user):
    """The tier to judge a StatZ-only FEATURE by — StatZ while a sample runs.
    Never use this for prices, allowances or limits; only for the features
    the sample lists."""
    return TIER_STATZ if trial_active(user) else membership_for(user).tier


def state(user):
    tier = membership_for(user).tier
    t = _trial(user)
    now = timezone.now()
    active = bool(t and t.ends_at > now)
    return {
        "is_statz": tier in (TIER_STATZ, TIER_DEBUG),
        "available": tier not in (TIER_STATZ, TIER_DEBUG) and t is None,
        "active": active,
        "used": t is not None and not active,
        "ends_at": t.ends_at.isoformat() if t else None,
        "seconds_left": max(0, int((t.ends_at - now).total_seconds())) if active else 0,
        "minutes": TRIAL_MINUTES,
        "features": FEATURES,
        "upgrade": UPGRADE,
    }


class StatzTrialView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(state(request.user))

    def post(self, request):
        s = state(request.user)
        if s["is_statz"]:
            return Response({"detail": "You already have StatZ.", **s}, status=status.HTTP_400_BAD_REQUEST)
        if not s["available"]:
            return Response({"detail": "Your StatZ sample has been used — upgrading keeps it for good.", **s},
                            status=status.HTTP_409_CONFLICT)
        try:
            StatzTrial.objects.create(user=request.user, ends_at=timezone.now() + timedelta(minutes=TRIAL_MINUTES))
        except IntegrityError:
            pass
        return Response(state(request.user), status=status.HTTP_201_CREATED)
