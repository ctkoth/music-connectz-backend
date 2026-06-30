"""Parametrized training views. Each app mounts these via training_urlpatterns(app_key).

Youth-safe: training is creative practice, open to all authenticated tiers.
"""
import datetime

from django.db.models import Sum
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.agegate import YouthSafe

from .models import Attempt, Drill, SkillProgress, SkillTrack
from .serializers import AttemptSerializer, DrillSerializer, TrackSerializer
from .utils import level_for_xp
from . import badges as badge_engine
from .models import UserAchievement
from apps.common.tiergate import can_suggest, can_auto_suggest, can_automate, tier_of

PERMS = [YouthSafe]


class _AppScoped(APIView):
    permission_classes = PERMS
    app_key = None  # set via .as_view(app_key="mixez")

    def progress_map(self, user):
        return {p.track_id: p for p in SkillProgress.objects.filter(
            user=user, track__app_key=self.app_key)}


class TracksView(_AppScoped):
    def get(self, request):
        tracks = SkillTrack.objects.filter(app_key=self.app_key)
        ser = TrackSerializer(tracks, many=True,
                              context={"progress_map": self.progress_map(request.user)})
        return Response({"app": self.app_key, "tracks": ser.data})


class DrillsView(_AppScoped):
    def get(self, request):
        qs = Drill.objects.filter(track__app_key=self.app_key)
        track = request.query_params.get("track")
        if track:
            qs = qs.filter(track__key=track)
        return Response({"app": self.app_key, "drills": DrillSerializer(qs, many=True).data})


class DailyView(_AppScoped):
    """A daily warmup — a small rotating set of drills, stable per (user, date)."""
    def get(self, request):
        drills = list(Drill.objects.filter(track__app_key=self.app_key))
        if not drills:
            return Response({"app": self.app_key, "date": str(datetime.date.today()), "drills": []})
        seed = (request.user.id or 0) + datetime.date.today().toordinal()
        picks = [drills[(seed * (i + 7)) % len(drills)] for i in range(min(3, len(drills)))]
        return Response({"app": self.app_key, "date": str(datetime.date.today()),
                         "drills": DrillSerializer(picks, many=True).data})


class ProgressView(_AppScoped):
    def get(self, request):
        pmap = self.progress_map(request.user)
        total = sum(p.total_xp for p in pmap.values())
        lvl, into, nxt = level_for_xp(total)
        return Response({
            "app": self.app_key,
            "overall_level": lvl, "overall_xp": total,
            "xp_into_level": into, "xp_to_next": nxt,
            "tracks": [{
                "track": p.track.key, "title": p.track.title,
                "level": level_for_xp(p.total_xp)[0], "total_xp": p.total_xp,
                "streak_days": p.streak_days,
            } for p in pmap.values()],
        })


class LeaderboardView(_AppScoped):
    def get(self, request):
        rows = (SkillProgress.objects.filter(track__app_key=self.app_key)
                .values("user__id").annotate(xp=Sum("total_xp")).order_by("-xp")[:25])
        board = [{"rank": i + 1, "user_id": r["user__id"], "xp": r["xp"] or 0,
                  "level": level_for_xp(r["xp"] or 0)[0]} for i, r in enumerate(rows)]
        return Response({"app": self.app_key, "leaderboard": board})


class AttemptView(_AppScoped):
    """POST {drill, score} -> record attempt, award XP, update level + streak."""
    def post(self, request):
        from .scoring import record_attempt
        drill_id = request.data.get("drill")
        score = int(request.data.get("score", 0))
        try:
            drill = Drill.objects.get(id=drill_id, track__app_key=self.app_key)
        except Drill.DoesNotExist:
            return Response({"detail": "drill not found"}, status=status.HTTP_404_NOT_FOUND)
        result = record_attempt(request.user, drill, score)
        return Response(result, status=status.HTTP_201_CREATED)


class BadgesView(_AppScoped):
    """Current user's earned badges for this app."""
    def get(self, request):
        rows = UserAchievement.objects.filter(user=request.user, app_key=self.app_key)
        return Response({"app": self.app_key, "badges": badge_engine.hydrate(rows),
                         "catalog": badge_engine.BADGE_CATALOG})


class PublicProgressView(APIView):
    """Any signed-in user can view another user's training progress + badges,
    for profile cards. Read-only summary across all creator apps."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        from django.contrib.auth import get_user_model
        from .models import SkillProgress
        from django.db.models import Sum
        U = get_user_model()
        if not U.objects.filter(pk=user_id).exists():
            return Response({"detail": "no such user"}, status=status.HTTP_404_NOT_FOUND)
        rows = (SkillProgress.objects.filter(user_id=user_id)
                .values("track__app_key").annotate(xp=Sum("total_xp")))
        apps = []
        for r in rows:
            xp = r["xp"] or 0
            apps.append({"app": r["track__app_key"], "xp": xp, "level": level_for_xp(xp)[0]})
        apps.sort(key=lambda a: -a["xp"])
        badge_rows = UserAchievement.objects.filter(user_id=user_id)
        return Response({"user_id": int(user_id), "apps": apps,
                         "badges": badge_engine.hydrate(badge_rows)})


class CapabilitiesView(APIView):
    """What tier-gated actions the current user can take (drives UI across the app + OCC)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        u = request.user
        return Response({
            "tier": tier_of(u),
            "can_suggest": can_suggest(u),          # Premium+: manual suggestions
            "can_auto_suggest": can_auto_suggest(u),# StatZ: auto-run suggestions
            "can_automate": can_automate(u),        # StatZ: automations
        })
