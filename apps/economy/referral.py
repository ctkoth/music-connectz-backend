"""Referrals (two-sided) + one-time onboarding reward.

Referral flow:
  * A member's referral code IS their username (case-insensitive). GET returns
    the caller's own code and how many people they've brought in + SpinAZ earned.
  * A new member redeems a code once via POST {code}. Both sides are paid once;
    a member can never be referred twice or refer themselves.

Onboarding:
  * GET  -> {onboarded: bool}
  * POST -> grants the one-time SpinAZ + Energy reward (idempotent).
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    REFERRAL_REWARD_JOINEE_SPINAZ,
    REFERRAL_REWARD_REFERRER_SPINAZ,
    Referral,
    complete_onboarding,
    profile_for,
    record_referral,
)

User = get_user_model()


class ReferralView(APIView):
    """GET my code + stats · POST {code} to redeem an inviter's code once."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        made = Referral.objects.filter(referrer=u).count()
        referred_by = Referral.objects.filter(joinee=u).select_related("referrer").first()
        return Response({
            "code": u.username,
            "referrals": made,
            "spinaz_earned": made * REFERRAL_REWARD_REFERRER_SPINAZ,
            "referred_by": referred_by.referrer.username if referred_by else "",
            "reward_referrer": REFERRAL_REWARD_REFERRER_SPINAZ,
            "reward_joinee": REFERRAL_REWARD_JOINEE_SPINAZ,
        })

    def post(self, request):
        code = str((request.data or {}).get("code", "")).strip()
        if not code:
            return Response({"detail": "Enter a referral code."}, status=status.HTTP_400_BAD_REQUEST)
        if code.lower() == request.user.username.lower():
            return Response({"detail": "You can't refer yourself."}, status=status.HTTP_400_BAD_REQUEST)
        if Referral.objects.filter(joinee=request.user).exists():
            return Response({"detail": "You've already used a referral code."}, status=status.HTTP_400_BAD_REQUEST)
        referrer = User.objects.filter(username__iexact=code).first()
        if not referrer:
            return Response({"detail": "That referral code isn't valid."}, status=status.HTTP_400_BAD_REQUEST)
        ref = record_referral(referrer, request.user)
        if not ref:
            return Response({"detail": "Couldn't apply that code."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "ok": True,
            "referred_by": referrer.username,
            "reward_spinaz": REFERRAL_REWARD_JOINEE_SPINAZ,
        }, status=status.HTTP_201_CREATED)


class OnboardCompleteView(APIView):
    """GET onboarding status · POST to claim the one-time reward (idempotent)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"onboarded": profile_for(request.user).onboarded})

    def post(self, request):
        result = complete_onboarding(request.user)
        return Response({"onboarded": True, **result})
