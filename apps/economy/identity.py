"""18+ age verification via Stripe Identity.

A member starts a Stripe Identity VerificationSession (government ID + selfie);
Stripe runs the check and fires `identity.verification_session.verified`. The
webhook (payments.StripeWebhookView) then reads the verified date-of-birth and,
only if it proves the member is 18 or older, sets `Profile.verified_18plus`.
This is the real gate for money betting (BattleZ) and adult content — a
self-reported birthday is never trusted for it.
"""
import datetime

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import profile_for


def _age_from_dob(dob):
    """Age in whole years from a Stripe Identity dob dict {day,month,year}."""
    try:
        born = datetime.date(int(dob["year"]), int(dob["month"]), int(dob["day"]))
    except (KeyError, TypeError, ValueError):
        return None
    today = datetime.date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def mark_18plus_from_session(session):
    """Called from the Stripe webhook on a verified session. Sets the profile
    flag iff the verified DOB proves 18+. Idempotent."""
    from django.contrib.auth import get_user_model
    meta = session.get("metadata") or {}
    uid = meta.get("user_id")
    if not uid:
        return
    user = get_user_model().objects.filter(pk=uid).first()
    if not user:
        return
    dob = ((session.get("verified_outputs") or {}).get("dob")) or {}
    age = _age_from_dob(dob)
    if age is None or age < 18:
        return
    p = profile_for(user)
    if not p.verified_18plus:
        p.verified_18plus = True
        p.verified_18plus_at = timezone.now()
        p.save(update_fields=["verified_18plus", "verified_18plus_at", "updated_at"])


class IdentityView(APIView):
    """GET the caller's 18+ status; POST starts a Stripe Identity session."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        p = profile_for(request.user)
        return Response({
            "verified_18plus": p.verified_18plus,
            "verified_at": p.verified_18plus_at.isoformat() if p.verified_18plus_at else None,
            "stripe_enabled": bool(settings.STRIPE_SECRET_KEY),
        })

    def post(self, request):
        if not settings.STRIPE_SECRET_KEY:
            return Response({"detail": "Identity verification is not configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        p = profile_for(request.user)
        if p.verified_18plus:
            return Response({"verified_18plus": True, "already": True})
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        session = stripe.identity.VerificationSession.create(
            type="document",
            metadata={"user_id": str(request.user.id)},
            options={"document": {"require_matching_selfie": True}},
            return_url=f"{settings.FRONTEND_URL}/v2?verify=done",
        )
        # `url` is the hosted verification flow the client redirects to.
        return Response({"url": session.url, "client_secret": session.client_secret, "id": session.id})
