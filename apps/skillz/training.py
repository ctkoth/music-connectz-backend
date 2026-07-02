"""
SkillZ training endpoints, generated per app_key.

Usage in any creator app's urls.py (defensive — Render-safe):

    try:
        from apps.common.training import training_urlpatterns      # canonical, if present
    except Exception:                                              # pragma: no cover
        from apps.skillz.training import training_urlpatterns      # bundled fallback

    urlpatterns = [ ... ] + training_urlpatterns("mimez")

Endpoints produced (all relative to wherever you mount them):
    GET  skillz/profile/        my profile for this app
    GET  skillz/drills/         active drills for this app
    GET  skillz/badges/         all badges + earned flags
    POST skillz/complete/       complete a drill -> award XP, bump streak, check badges
    GET  skillz/leaderboard/    top profiles by XP for this app
"""
from django.db import transaction
from django.urls import path
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Badge, Drill, EarnedBadge, TrainingEvent, TrainingProfile
from .serializers import (
    BadgeSerializer,
    DrillSerializer,
    LeaderboardEntrySerializer,
    TrainingProfileSerializer,
)


def _get_or_create_profile(user, app_key):
    profile, _ = TrainingProfile.objects.get_or_create(user=user, app_key=app_key)
    return profile


def _check_and_award_badges(profile):
    """Award any newly-eligible badges. Returns list of newly earned codes."""
    already = set(
        profile.earned_badges.values_list("badge__code", flat=True)
    )
    newly = []
    for badge in Badge.objects.filter(app_key=profile.app_key):
        if badge.code in already:
            continue
        if badge.is_met_by(profile):
            EarnedBadge.objects.get_or_create(profile=profile, badge=badge)
            newly.append(badge.code)
    return newly


class _ProfileView(APIView):
    permission_classes = [IsAuthenticated]
    app_key = None

    def get(self, request):
        profile = _get_or_create_profile(request.user, self.app_key)
        return Response(TrainingProfileSerializer(profile).data)


class _DrillsView(APIView):
    permission_classes = [IsAuthenticated]
    app_key = None

    def get(self, request):
        drills = Drill.objects.filter(app_key=self.app_key, is_active=True)
        return Response(DrillSerializer(drills, many=True).data)


class _BadgesView(APIView):
    permission_classes = [IsAuthenticated]
    app_key = None

    def get(self, request):
        profile = _get_or_create_profile(request.user, self.app_key)
        earned_codes = set(profile.earned_badges.values_list("badge__code", flat=True))
        badges = Badge.objects.filter(app_key=self.app_key)
        data = BadgeSerializer(
            badges, many=True, context={"earned_codes": earned_codes}
        ).data
        return Response(data)


class _CompleteView(APIView):
    permission_classes = [IsAuthenticated]
    app_key = None

    @transaction.atomic
    def post(self, request):
        drill_key = (request.data or {}).get("drill_key")
        score = int((request.data or {}).get("score", 0) or 0)
        if not drill_key:
            return Response(
                {"detail": "drill_key is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            drill = Drill.objects.get(
                app_key=self.app_key, key=drill_key, is_active=True
            )
        except Drill.DoesNotExist:
            return Response(
                {"detail": f"Unknown drill '{drill_key}' for {self.app_key}."},
                status=status.HTTP_404_NOT_FOUND,
            )

        profile = (
            TrainingProfile.objects.select_for_update()
            .get_or_create(user=request.user, app_key=self.app_key)[0]
        )

        xp_gain = drill.xp + max(0, min(score, 100))  # base + perf bonus, capped
        profile.add_xp(xp_gain)
        profile.drills_completed += 1
        profile.touch_streak()
        profile.save()

        TrainingEvent.objects.create(
            profile=profile,
            drill_key=drill_key,
            score=score,
            xp_awarded=xp_gain,
        )

        new_badges = _check_and_award_badges(profile)

        payload = TrainingProfileSerializer(profile).data
        payload["xp_awarded"] = xp_gain
        payload["new_badges"] = new_badges
        return Response(payload, status=status.HTTP_200_OK)


class _LeaderboardView(APIView):
    permission_classes = [IsAuthenticated]
    app_key = None

    def get(self, request):
        limit = min(int(request.query_params.get("limit", 25) or 25), 100)
        qs = (
            TrainingProfile.objects.filter(app_key=self.app_key)
            .select_related("user")
            .order_by("-xp", "-longest_streak")[:limit]
        )
        return Response(LeaderboardEntrySerializer(qs, many=True).data)


def training_urlpatterns(app_key: str):
    """Return SkillZ url patterns bound to a specific app_key."""

    def _bind(view_cls):
        # subclass per app_key so the class attr is set without shared mutation
        return type(f"{view_cls.__name__}_{app_key}", (view_cls,), {"app_key": app_key})

    return [
        path("skillz/profile/", _bind(_ProfileView).as_view(), name=f"{app_key}-skillz-profile"),
        path("skillz/drills/", _bind(_DrillsView).as_view(), name=f"{app_key}-skillz-drills"),
        path("skillz/badges/", _bind(_BadgesView).as_view(), name=f"{app_key}-skillz-badges"),
        path("skillz/complete/", _bind(_CompleteView).as_view(), name=f"{app_key}-skillz-complete"),
        path("skillz/leaderboard/", _bind(_LeaderboardView).as_view(), name=f"{app_key}-skillz-leaderboard"),
    ]
