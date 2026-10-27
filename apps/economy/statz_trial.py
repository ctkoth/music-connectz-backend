"""The StatZ sample: a first full hour, then fifteen minutes every 24 hours.

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

# The FIRST sample a member ever has is a full hour — long enough to use StatZ and form an
# opinion — and every later one is TRIAL_MINUTES. An hour is the best first impression; a daily
# fifteen is the habit (ViewZ is worth checking again after you promote a post, and a single
# hour can burn before there is anything to see), so it is both rather than either.
FIRST_TRIAL_MINUTES = 60
TRIAL_MINUTES = 15
# It was one hour, once, ever — which was the whole of what a member could learn about StatZ.
# Fifteen minutes a day is enough to use the thing (read a post's tracks, run a pairing) and
# short enough that the lock, and the way past it, is part of the daily habit rather than a
# one-time cliff. Measured from the START of the last sample, not the calendar day: a member
# in New York must not get a fresh window at 7pm because the server's clock is UTC.
TRIAL_COOLDOWN_HOURS = 24
# When the screen tells a member how long is left, besides the banner that is always there.
WARN_AT_SECONDS = [300, 60]
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
    # ViewZ: who viewed a post by name and every visit as a track on a clock, with what
    # each viewer did. It is a READ of what already happened, so it switches off cleanly.
    {"key": "viewz_tracks", "label": "Who viewed your posts, as DAW tracks", "tab": "viewz", "target": "viewz-tracks"},
]

# THE AUDIT: every place StatZ is the difference, and whether the daily sample covers it.
#
# A feature belongs in the sample only if it can honestly switch off again when the
# hour is up (a read, a picker, a control). A STANDING grant wearing a timer — a saved
# voice, a visibility setting, a limit — is not, and the audit says why for each one
# rather than leaving the next reader to guess. `test_statz_drivers` walks the source:
# a module that asks `has_statz` / `feature_tier` and is not named here fails, and the
# sampled rows must be exactly FEATURES, so the list the screen shows and the list the
# server gates cannot drift.
#
# `modules` is where the gate lives. Limits (characters, uploads, links, prompts) are
# not features: they are read from the tier and never from the sample.
DRIVERS = [
    {"key": "mood_search", "sampled": True, "modules": ["instrumentalz"]},
    {"key": "page_widgets", "sampled": True, "modules": ["widgetz"]},
    {"key": "advanced_horoscope", "sampled": True, "modules": ["metricz"]},
    {"key": "coach_pairing", "sampled": True, "modules": ["superset"]},
    {"key": "rest_alerts", "sampled": True, "modules": []},
    {"key": "viewz_tracks", "sampled": True, "modules": ["viewz"]},
    {"key": "instrumental_mix", "sampled": False, "modules": ["instrumentalz"],
     "why_not": "A kept set of levels is a saved preference on a stored piece — a sample that left one behind would be a permanent grant wearing a timer."},
    {"key": "mix_presets", "sampled": False, "modules": ["mix_presets"],
     "why_not": "Keeping a preset's mix and a saved library of AI presets are saved preferences — a sample that left them behind would be a permanent grant wearing a timer."},
    {"key": "budget_bank", "sampled": False, "modules": ["budgetz"],
     "why_not": "A linked bank is a standing connection that keeps importing — a sample that left one behind would be a permanent grant wearing a timer."},
    {"key": "coach_voices", "sampled": False, "modules": ["coachvoice"],
     "why_not": "Saving a coach voice is a standing preference — a sample that left one behind would be a permanent grant wearing a timer."},
    {"key": "custom_voices", "sampled": False, "modules": ["voicez"],
     "why_not": "A cloned voice is a stored asset that costs real compute to make; it does not switch off."},
    {"key": "shop_markets", "sampled": False, "modules": ["lookmaxz"],
     "why_not": "Your own marketplace list is a saved preference — a sample that left one behind would be a permanent grant wearing a timer."},
    {"key": "code_sandbox", "sampled": False, "modules": ["modal_sandbox"],
     "why_not": "Every run spends real compute, so a free sample of it every day is a cost with no sale attached."},
    {"key": "lesson_visibility", "sampled": False, "modules": ["lessonz"],
     "why_not": "Setting a lesson StatZ-only changes what OTHER members can see; it must not flip back under them when an hour ends."},
    {"key": "limits", "sampled": False, "modules": ["catalog"],
     "why_not": "Characters, uploads, storage, links and prompts are limits read from the tier, never from a sample."},
]
FEATURE_MODULES = {m for d in DRIVERS for m in d["modules"]}
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


def _window_minutes(t):
    """How long the member's LAST window was (the first one is an hour), or None if never."""
    return round((t.ends_at - t.started_at).total_seconds() / 60) if t else None


def _next_minutes(t):
    """How long the window they would get NEXT is: the hour once, then fifteen."""
    return FIRST_TRIAL_MINUTES if t is None else TRIAL_MINUTES


def _next_at(t):
    return t.started_at + timedelta(hours=TRIAL_COOLDOWN_HOURS) if t else None


def state(user):
    tier = membership_for(user).tier
    t = _trial(user)
    now = timezone.now()
    active = bool(t and t.ends_at > now)
    is_statz = tier in (TIER_STATZ, TIER_DEBUG)
    nxt = _next_at(t)
    # Available: never had one, or the last one started at least a day ago and has ended.
    available = (not is_statz) and (t is None or (not active and now >= nxt))
    return {
        "is_statz": is_statz,
        "available": available,
        "active": active,
        # Used = today's sample is spent and the next one is not due yet.
        "used": t is not None and not active and not available and not is_statz,
        "ends_at": t.ends_at.isoformat() if t else None,
        "seconds_left": max(0, int((t.ends_at - now).total_seconds())) if active else 0,
        # When the next free sample opens — said as a time, so "back tomorrow" is a fact.
        "next_at": nxt.isoformat() if (t and not available and not is_statz) else None,
        "seconds_until_next": max(0, int((nxt - now).total_seconds())) if (t and not available and not is_statz) else 0,
        # `minutes` is the window on offer now (60 the first time, then 15); `last_minutes` is
        # the one just used, so "your free hour is used" never says fifteen.
        "minutes": _next_minutes(t),
        "last_minutes": _window_minutes(t),
        "first": t is None and not is_statz,
        "daily_minutes": TRIAL_MINUTES,
        "daily": True,
        "features": FEATURES,
        # What StatZ holds that the daily sample does NOT, and why — so the screen can say
        # "keeping it" and mean the whole of it, not only the sample's list.
        "also_in_statz": [{"key": d["key"], "why_not": d["why_not"]} for d in DRIVERS if not d["sampled"]],
        "upgrade": UPGRADE,
        "warn_at_seconds": WARN_AT_SECONDS,
    }


class StatzTrialView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(state(request.user))

    def post(self, request):
        s = state(request.user)
        if s["is_statz"]:
            return Response({"detail": "You already have StatZ.", **s}, status=status.HTTP_400_BAD_REQUEST)
        if s["active"]:
            return Response(s)                      # pressing it again is not a second window
        if not s["available"]:
            return Response({"detail": "Today's free StatZ minutes are used — the next ones open at the time shown, "
                                       "or upgrading keeps it for good.", **s}, status=status.HTTP_409_CONFLICT)
        now = timezone.now()
        ends = now + timedelta(minutes=_next_minutes(_trial(request.user)))
        try:
            row = _trial(request.user)
            if row is None:
                StatzTrial.objects.create(user=request.user, ends_at=ends)
            else:
                # Re-arm the one row. `started_at` is auto_now_add, so it is written explicitly;
                # a conditional update means two presses at once cannot open two windows.
                StatzTrial.objects.filter(pk=row.pk, started_at=row.started_at).update(started_at=now, ends_at=ends)
        except IntegrityError:
            pass
        return Response(state(request.user), status=status.HTTP_201_CREATED)
