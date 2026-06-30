"""Minimal, tolerant surfaces the frontend hits right after login so the live
site is usable (not a wall of 404s). These return safe defaults; richer apps can
replace them later without changing the frontend.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class MembershipView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import Membership
        from apps.common.tiergate import tier_of, can_suggest, can_automate
        Membership.objects.get_or_create(user=request.user)
        tier = tier_of(request.user)
        return Response({
            "tier": tier,
            "limits": {"can_use_suggestions": can_suggest(request.user),
                       "can_use_automations": can_automate(request.user)},
            "status": "active",
        })


class NotificationsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response([])


class NotificationsMarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return Response({"ok": True, "marked": 0})


class MyReferralCodeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        code = f"MCZ-{request.user.username}".upper().replace(" ", "")
        return Response({"code": code, "uses": 0})
