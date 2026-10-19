"""The endpoint for AttractivenessZ — the gate lives here, the model call
lives in attractivenessz.py. Kept apart so the two things that must never
drift — "who may ask" and "what the model is told" — are each one function,
not two responsibilities tangled into one view.
"""
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .attractivenessz import PRESENTATION_SCORES, rate_presentation, too_big
from .catalog import ai_cost
from .models import (can_afford_ai, charge_ai_usage, daily_prompt_state,
                     profile_for)
from .vocalcoach import INLINE_MAX_MB, _key


def presentation_price(user):
    """What a rating costs this member, and whether they may even ask —
    published BEFORE the upload, the same cost/gain-up-front rule every
    other AI surface in this codebase follows."""
    cost = ai_cost("standard")
    allowance, _, daily_left = daily_prompt_state(user)
    verified = bool(profile_for(user).verified_18plus)
    return {
        "cost_cents": cost,
        "daily_prompts": allowance,
        "daily_prompts_left": daily_left,
        "free_today": bool(cost) and daily_left > 0,
        "affordable": bool(not cost or daily_left > 0 or can_afford_ai(user, cost)),
        "configured": bool(_key()),
        "max_mb": INLINE_MAX_MB,
        "scores": PRESENTATION_SCORES,
        # The gate, published rather than discovered on submit — a member who
        # isn't verified sees WHY before they upload anything, not after.
        "requires_18plus_verification": True,
        "verified": verified,
    }


class AttractivenessZView(APIView):
    """GET the price and gate state; POST a photo (multipart) to rate it.

    POST body: `photo` (file), `confirm_self` ("true"/"1") — both required.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        return Response(presentation_price(request.user))

    def post(self, request):
        price = presentation_price(request.user)
        if not price["verified"]:
            return Response(
                {**price, "detail": "This is 18+ only, verified — not a self-reported "
                                    "birthday. Verify your identity in ProfileZ first."},
                status=status.HTTP_403_FORBIDDEN)

        confirm_self = str(request.data.get("confirm_self", "")).strip().lower() in ("true", "1", "yes")
        if not confirm_self:
            return Response(
                {**price, "detail": "You must confirm this is a photo of yourself. "
                                    "Rating someone else's photo isn't what this does."},
                status=status.HTTP_400_BAD_REQUEST)

        photo = request.FILES.get("photo")
        if not photo:
            return Response({**price, "detail": "Attach a photo."},
                            status=status.HTTP_400_BAD_REQUEST)

        if too_big(photo.size):
            return Response(
                {**price, "detail": f"That photo is over the {price['max_mb']}MB "
                                    "the coach can read in one go."},
                status=status.HTTP_400_BAD_REQUEST)

        if not price["affordable"]:
            return Response({**price, "detail": f"A rating costs {price['cost_cents']} 🏷️ "
                                                "and today's free prompts are spent."},
                            status=status.HTTP_402_PAYMENT_REQUIRED)

        payload, why = rate_presentation(photo, photo.content_type)
        if payload is None:
            return Response({**price, "detail": f"Couldn't read that — {why}."},
                            status=status.HTTP_502_BAD_GATEWAY)

        # Billed only now — a photo the coach couldn't read, or that read as
        # unreadable, is never charged, same rule vocalcoach and DirectZ
        # craft both bill on.
        if not payload["unreadable"]:
            charge_ai_usage(request.user, price["cost_cents"],
                            note="AttractivenessZ presentation rating", count_daily=True)

        return Response(payload)
