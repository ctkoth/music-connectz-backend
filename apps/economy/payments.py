"""Wallet funding via Stripe Checkout and PayPal Orders.

Each provider is optional: the endpoints report "unavailable" (503) when its
keys aren't configured, so the client can hide the button and the rest of the
app is unaffected. Crediting always runs through `credit_funds` (developer tax
enforced server-side) and is made idempotent by the unique PaymentIntent
provider_ref — a replayed Stripe webhook or a double PayPal capture can never
credit a wallet twice.
"""
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PaymentIntent, credit_funds
from .serializers import WalletSerializer
from .models import wallet_for

MIN_CENTS = 100          # $1 minimum
MAX_CENTS = 1_000_000    # $10,000 cap per funding


def _amount_or_error(request):
    try:
        amount_cents = int(request.data.get("amount_cents"))
    except (TypeError, ValueError):
        return None, Response({"detail": "amount_cents (integer) required"}, status=status.HTTP_400_BAD_REQUEST)
    if not (MIN_CENTS <= amount_cents <= MAX_CENTS):
        return None, Response({"detail": f"amount must be between {MIN_CENTS} and {MAX_CENTS} cents"}, status=status.HTTP_400_BAD_REQUEST)
    return amount_cents, None


def _complete_intent(intent):
    """Credit the wallet for a confirmed payment, exactly once."""
    with transaction.atomic():
        pi = PaymentIntent.objects.select_for_update().get(pk=intent.pk)
        if pi.status == PaymentIntent.STATUS_COMPLETED:
            return pi  # already credited — idempotent no-op
        dev, net = credit_funds(pi.user, pi.amount_cents, note=f"Wallet funding ({pi.provider})")
        pi.dev_tax_cents = dev
        pi.net_cents = net
        pi.status = PaymentIntent.STATUS_COMPLETED
        pi.completed_at = timezone.now()
        pi.save(update_fields=["dev_tax_cents", "net_cents", "status", "completed_at"])
    return pi


# ---------------------------------------------------------------- config

class CheckoutConfigView(APIView):
    """Tells the client which providers are live + the Stripe publishable key."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "stripe_enabled": bool(settings.STRIPE_SECRET_KEY),
            "stripe_publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
            "paypal_enabled": bool(settings.PAYPAL_CLIENT_ID and settings.PAYPAL_SECRET),
            "min_cents": MIN_CENTS,
            "max_cents": MAX_CENTS,
        })


# ---------------------------------------------------------------- Stripe

class StripeCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not settings.STRIPE_SECRET_KEY:
            return Response({"detail": "Stripe is not configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        amount_cents, err = _amount_or_error(request)
        if err:
            return err
        import stripe  # imported lazily so the app runs without the SDK when unused
        stripe.api_key = settings.STRIPE_SECRET_KEY
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "Music ConnectZ wallet funds"},
                    "unit_amount": amount_cents,
                },
                "quantity": 1,
            }],
            success_url=f"{settings.FRONTEND_URL}/v2?checkout=success&provider=stripe",
            cancel_url=f"{settings.FRONTEND_URL}/v2?checkout=cancel&provider=stripe",
            client_reference_id=str(request.user.id),
            metadata={"user_id": str(request.user.id), "amount_cents": str(amount_cents)},
        )
        PaymentIntent.objects.create(
            user=request.user, provider=PaymentIntent.PROVIDER_STRIPE,
            provider_ref=session.id, amount_cents=amount_cents,
        )
        return Response({"url": session.url, "id": session.id})


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(APIView):
    """Stripe calls this server-to-server; no user auth, signature-verified."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        if not (settings.STRIPE_SECRET_KEY and settings.STRIPE_WEBHOOK_SECRET):
            return Response({"detail": "Stripe is not configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        import stripe
        sig = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        try:
            event = stripe.Webhook.construct_event(request.body, sig, settings.STRIPE_WEBHOOK_SECRET)
        except (ValueError, stripe.error.SignatureVerificationError):
            return Response({"detail": "invalid signature"}, status=status.HTTP_400_BAD_REQUEST)

        if event["type"] == "checkout.session.completed":
            session_id = event["data"]["object"]["id"]
            intent = PaymentIntent.objects.filter(
                provider=PaymentIntent.PROVIDER_STRIPE, provider_ref=session_id
            ).first()
            if intent:
                _complete_intent(intent)
        return Response({"received": True})


# ---------------------------------------------------------------- PayPal

def _paypal_token():
    import requests
    r = requests.post(
        f"{settings.PAYPAL_API_BASE}/v1/oauth2/token",
        data={"grant_type": "client_credentials"},
        auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_SECRET),
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["access_token"]


class PaypalCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not (settings.PAYPAL_CLIENT_ID and settings.PAYPAL_SECRET):
            return Response({"detail": "PayPal is not configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        amount_cents, err = _amount_or_error(request)
        if err:
            return err
        import requests
        token = _paypal_token()
        resp = requests.post(
            f"{settings.PAYPAL_API_BASE}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "intent": "CAPTURE",
                "purchase_units": [{
                    "amount": {"currency_code": "USD", "value": f"{amount_cents / 100:.2f}"},
                    "description": "Music ConnectZ wallet funds",
                }],
                "application_context": {
                    "brand_name": "Music ConnectZ",
                    "user_action": "PAY_NOW",
                    "return_url": f"{settings.FRONTEND_URL}/v2?checkout=success&provider=paypal",
                    "cancel_url": f"{settings.FRONTEND_URL}/v2?checkout=cancel&provider=paypal",
                },
            },
            timeout=20,
        )
        if resp.status_code not in (200, 201):
            return Response({"detail": "PayPal order creation failed"}, status=status.HTTP_502_BAD_GATEWAY)
        order = resp.json()
        approve = next((l["href"] for l in order.get("links", []) if l.get("rel") == "approve"), None)
        PaymentIntent.objects.create(
            user=request.user, provider=PaymentIntent.PROVIDER_PAYPAL,
            provider_ref=order["id"], amount_cents=amount_cents,
        )
        return Response({"id": order["id"], "approve_url": approve})


class PaypalCaptureView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not (settings.PAYPAL_CLIENT_ID and settings.PAYPAL_SECRET):
            return Response({"detail": "PayPal is not configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        order_id = str(request.data.get("order_id", ""))
        # Only the user who created the intent can capture it.
        intent = PaymentIntent.objects.filter(
            provider=PaymentIntent.PROVIDER_PAYPAL, provider_ref=order_id, user=request.user
        ).first()
        if not intent:
            return Response({"detail": "unknown order"}, status=status.HTTP_404_NOT_FOUND)
        if intent.status == PaymentIntent.STATUS_COMPLETED:
            return Response({"wallet": WalletSerializer(wallet_for(request.user)).data, "already": True})

        import requests
        token = _paypal_token()
        resp = requests.post(
            f"{settings.PAYPAL_API_BASE}/v2/checkout/orders/{order_id}/capture",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=20,
        )
        data = resp.json() if resp.content else {}
        if resp.status_code not in (200, 201) or data.get("status") != "COMPLETED":
            return Response({"detail": "capture not completed"}, status=status.HTTP_402_PAYMENT_REQUIRED)
        _complete_intent(intent)
        return Response({"wallet": WalletSerializer(wallet_for(request.user)).data})
