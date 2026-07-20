"""Stripe saved-card auto top-up — hands-off recurring wallet funding.

A Stripe Subscription bills the member's saved card on their chosen cadence;
Stripe owns the schedule + dunning. Each paid invoice credits the in-app wallet
with money (dev tax via credit_funds) + tier Energy — handled idempotently in
the Stripe webhook (see payments.StripeWebhookView) keyed by the unique invoice
id through PaymentIntent.provider_ref.
"""
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AutoTopUp

VALID_INTERVALS = {"week", "month", "year"}
MIN_CENTS = 100
MAX_CENTS = 1_000_000


def _autotopup_dict(a):
    return {
        "id": a.id,
        "amount_cents": a.amount_cents,
        "amount": round(a.amount_cents / 100, 2),
        "interval": a.interval,
        "active": a.active,
        "created_at": a.created_at.isoformat(),
    }


class AutoTopUpView(APIView):
    """GET the caller's auto top-ups; POST starts one (Stripe Checkout, subscription)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = AutoTopUp.objects.filter(user=request.user)
        return Response({"auto_topups": [_autotopup_dict(a) for a in rows], "stripe_enabled": bool(settings.STRIPE_SECRET_KEY)})

    def post(self, request):
        if not settings.STRIPE_SECRET_KEY:
            return Response({"detail": "Stripe is not configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            amount_cents = int(request.data.get("amount_cents"))
        except (TypeError, ValueError):
            return Response({"detail": "amount_cents (integer) required"}, status=status.HTTP_400_BAD_REQUEST)
        if not (MIN_CENTS <= amount_cents <= MAX_CENTS):
            return Response({"detail": f"amount must be between {MIN_CENTS} and {MAX_CENTS} cents"}, status=status.HTTP_400_BAD_REQUEST)
        interval = str(request.data.get("interval", "month")).lower()
        if interval not in VALID_INTERVALS:
            return Response({"detail": f"interval must be one of {sorted(VALID_INTERVALS)}"}, status=status.HTTP_400_BAD_REQUEST)

        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f"Music ConnectZ auto top-up (${amount_cents / 100:.2f}/{interval})"},
                    "unit_amount": amount_cents,
                    "recurring": {"interval": interval},
                },
                "quantity": 1,
            }],
            success_url=f"{settings.FRONTEND_URL}/v2?checkout=success&provider=stripe&kind=autotopup",
            cancel_url=f"{settings.FRONTEND_URL}/v2?checkout=cancel&provider=stripe&kind=autotopup",
            client_reference_id=str(request.user.id),
            metadata={"kind": "autotopup", "user_id": str(request.user.id), "amount_cents": str(amount_cents), "interval": interval},
        )
        return Response({"url": session.url, "id": session.id})


class AutoTopUpCancelView(APIView):
    """Cancel an auto top-up: delete the Stripe subscription + mark inactive."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        a = AutoTopUp.objects.filter(pk=pk, user=request.user).first()
        if not a:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        if a.active and settings.STRIPE_SECRET_KEY and a.stripe_subscription_id:
            try:
                import stripe
                stripe.api_key = settings.STRIPE_SECRET_KEY
                stripe.Subscription.delete(a.stripe_subscription_id)
            except Exception:
                pass  # already gone / network — flip local state regardless
        a.active = False
        a.save(update_fields=["active"])
        return Response(_autotopup_dict(a))
