"""BreathZ — breath training, free, for every coach that scores Breath.

The Breath score on a take (RapZ, SingZ) is the thing members most often fail on
and the thing nothing in the app helped with: the coach said "your breath runs
out" and the only door was a drill list with no breathing in it. This is that
door, and it is deliberately free — a member who can fix a weakness for nothing
should be told so, and it is the cheapest place the platform can be useful.

What it is NOT, said on the screen as well: a timer cannot measure a breath. A
session here pays XP and a streak (effort — XP may reward turning up) and it NEVER
moves a rating. The measurement is still the coach's Breath score on your takes,
which this screen reads back beside the practice so the two can be compared.

Server-owned like everything else: the patterns, what each is for and why, the
minimum a session must last to count, and the daily number that pay XP. The client
paces the breath and claims a session; the server decides whether it counted.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

APP_KEY = "breathz"
# XP is for turning up, so it is for turning up a few times a day, not a hundred.
COUNTED_PER_DAY = 5
# The wind and brass coaches: for them breath is the instrument, so every pattern is for them.
WINDS = ["flutez", "saxz", "clarinetz", "trumpetz"]

# Each step is (phase, beats). A "beat" is one second unless the pattern is
# `bpm_based`, where it is one beat at the member's own tempo — rap breathes on the
# bar, so its breath is measured in the same unit as the verse.
PATTERNS = [
    {"key": "box", "label": "Box breathing", "xp": 20, "rounds": 6, "min_seconds": 80,
     "steps": [("in", 4), ("hold", 4), ("out", 4), ("hold", 4)],
     "what": "Breathe in for 4, hold 4, out 4, hold 4.",
     "why": "Evens out a racing breath before a take, so the first line is not the breathless one.",
     "for": ["singz", "rapz", "guitarz", "bassz", "keyz", "drumz", "violinz", *WINDS]},
    {"key": "long_exhale", "label": "Long exhale", "xp": 25, "rounds": 8, "min_seconds": 90,
     "steps": [("in", 4), ("out", 8)],
     "what": "In for 4, out slowly for 8.",
     "why": "The exhale is the part you perform on. Stretching it is how phrases stop ending in a gasp.",
     "for": ["singz", "rapz", "violinz", *WINDS]},
    {"key": "support_hiss", "label": "Support hiss", "xp": 25, "rounds": 6, "min_seconds": 100,
     "steps": [("in", 4), ("out", 16)],
     "what": "In for 4, then let the air out on a steady 'sss' for 16.",
     "why": "A hiss that stays level is support you can hear. When it wobbles or dies early, that is where a long line will too.",
     "for": ["singz", "rapz"]},
    {"key": "bar_breath", "label": "Bar breathing", "xp": 30, "rounds": 8, "min_seconds": 90,
     "bpm_based": True, "bpm_default": 90,
     "steps": [("in", 1), ("out", 7)],
     "what": "One beat to breathe in, seven to let it go — two bars at your tempo.",
     "why": "Rap runs out of air on the bar. This practises taking the breath in the gap and having it last to the next one.",
     "for": ["rapz"]},
    {"key": "lip_trill", "label": "Lip trill", "xp": 20, "rounds": 6, "min_seconds": 80,
     "steps": [("in", 4), ("out", 12)],
     "what": "In for 4, then buzz your lips on a steady breath for 12.",
     "why": "Smooths airflow without strain and warms the voice at the same time.",
     "for": ["singz", "rapz"]},
    {"key": "downshift", "label": "4-7-8 downshift", "xp": 15, "rounds": 4, "min_seconds": 70,
     "steps": [("in", 4), ("hold", 7), ("out", 8)],
     "what": "In for 4, hold 7, out 8.",
     "why": "For after a hard session or before sleep — it brings the heart rate down, which is when practice settles.",
     "for": ["singz", "rapz", "guitarz", "bassz", "keyz", "drumz", "violinz", *WINDS]},
]
BY_KEY = {p["key"]: p for p in PATTERNS}

CAVEAT = ("A timer can't measure your breath. These sessions earn XP and a streak for turning up and never "
          "change a rating — the measure is the Breath score on your takes, shown here beside your practice.")


def _breath_scores(user):
    """The member's own Breath scores from the coach, newest first — the only measurement."""
    from .models import TakeScore
    rows = TakeScore.objects.filter(user=user, app_key__in=("singz", "rapz")).order_by("-created_at")[:30]
    vals = [t.scores["breath"] for t in rows if isinstance((t.scores or {}).get("breath"), int)]
    if len(vals) < 3:
        return {"average": None, "takes": len(vals),
                "why": f"{len(vals)} of 3 takes with a Breath score. One take's breath is a bad day, not a trend."}
    recent, earlier = vals[: len(vals) // 2 or 1], vals[len(vals) // 2 or 1:]
    out = {"average": round(sum(vals) / len(vals), 1), "takes": len(vals), "why": ""}
    if earlier:
        out.update({"recent": round(sum(recent) / len(recent), 1), "earlier": round(sum(earlier) / len(earlier), 1)})
    return out


def _pattern_dict(p):
    return {"key": p["key"], "label": p["label"], "what": p["what"], "why": p["why"], "xp": p["xp"],
            "rounds": p["rounds"], "min_seconds": p["min_seconds"],
            "bpm_based": bool(p.get("bpm_based")), "bpm_default": p.get("bpm_default"),
            "steps": [{"phase": ph, "beats": b} for ph, b in p["steps"]], "for": p["for"]}


def _today_count(profile):
    from apps.skillz.models import TrainingEvent
    since = timezone.now() - timedelta(hours=24)
    return TrainingEvent.objects.filter(profile=profile, created_at__gte=since, xp_awarded__gt=0).count()


class BreathZView(APIView):
    """GET: the patterns, what is left today, XP and streak, and the Breath score
    from the coach. POST {pattern, seconds, bpm?}: log a finished session."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.skillz.models import TrainingProfile
        profile = TrainingProfile.objects.filter(user=request.user, app_key=APP_KEY).first()
        return Response({
            "patterns": [_pattern_dict(p) for p in PATTERNS],
            "caveat": CAVEAT,
            "free": True,
            "counted_per_day": COUNTED_PER_DAY,
            "counted_today": _today_count(profile) if profile else 0,
            "xp": profile.xp if profile else 0,
            "level": profile.level if profile else 1,
            "streak": profile.current_streak if profile else 0,
            "longest_streak": profile.longest_streak if profile else 0,
            "breath": _breath_scores(request.user),
        })

    @transaction.atomic
    def post(self, request):
        from apps.skillz.models import TrainingEvent, TrainingProfile
        d = request.data or {}
        p = BY_KEY.get(str(d.get("pattern", "")))
        if not p:
            return Response({"detail": "Pick a pattern."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            seconds = int(d.get("seconds"))
        except (TypeError, ValueError):
            seconds = 0
        if seconds < p["min_seconds"]:
            return Response({"detail": f"That one counts from {p['min_seconds']} seconds — finish the rounds "
                                       "and it's logged. Nothing was lost.",
                             "counted": False}, status=status.HTTP_200_OK)
        profile = (TrainingProfile.objects.select_for_update()
                   .get_or_create(user=request.user, app_key=APP_KEY)[0])
        counted = _today_count(profile) < COUNTED_PER_DAY
        xp = p["xp"] if counted else 0
        if counted:
            profile.add_xp(xp)
            profile.drills_completed += 1
            profile.touch_streak()
            profile.save()
        TrainingEvent.objects.create(profile=profile, drill_key=p["key"], score=0, xp_awarded=xp)
        return Response({"counted": counted, "xp_awarded": xp, "xp": profile.xp, "streak": profile.current_streak,
                         "note": ("" if counted else f"That's {COUNTED_PER_DAY} counted today — more is fine, "
                                                      "it just doesn't earn XP.")})
