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

from .models import PaymentIntent, credit_funds, grant_lifetime, founding_status, membership_for
from .serializers import WalletSerializer
from .models import wallet_for
from .catalog import FOUNDING_PLANS, FOUNDING_TIER

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


class FoundingView(APIView):
    """Public counter for the founding lifetime StatZ offer (X / 50 claimed)."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({**founding_status(), "stripe_enabled": bool(settings.STRIPE_SECRET_KEY)})


class FoundingClaimView(APIView):
    """Dev/preview: grant the current user founding lifetime StatZ without money.
    Real purchases come through the Stripe founding checkout + webhook."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        m = grant_lifetime(request.user)
        if m is None:
            return Response({"detail": "Founding offer is sold out.", **founding_status()}, status=status.HTTP_409_CONFLICT)
        return Response({"granted": True, "tier": m.tier, "lifetime": m.lifetime, **founding_status()})


class FoundingCheckoutView(APIView):
    """Start a Stripe Checkout for founding StatZ, tied to this user.
    plan = lifetime (one-time, webhook grants lifetime) | year | month
    (subscription at the founding rate; webhook grants StatZ, cancel downgrades)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not settings.STRIPE_SECRET_KEY:
            return Response({"detail": "Stripe is not configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        plan = str(request.data.get("plan", "lifetime")).lower()
        cfg = FOUNDING_PLANS.get(plan)
        if not cfg:
            return Response({"detail": f"plan must be one of {sorted(FOUNDING_PLANS)}"}, status=status.HTTP_400_BAD_REQUEST)
        st = founding_status()
        if st["sold_out"]:
            return Response({"detail": "Founding offer is sold out.", **st}, status=status.HTTP_409_CONFLICT)
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        price_data = {
            "currency": "usd",
            "product_data": {"name": f"Music ConnectZ — Founding StatZ ({plan}, 50% off)"},
            "unit_amount": cfg["cents"],
        }
        if cfg["interval"]:
            price_data["recurring"] = {"interval": cfg["interval"]}
        session = stripe.checkout.Session.create(
            mode=cfg["mode"],
            line_items=[{"price_data": price_data, "quantity": 1}],
            success_url=f"{settings.FRONTEND_URL}/v2?checkout=success&provider=stripe&kind=founding&plan={plan}",
            cancel_url=f"{settings.FRONTEND_URL}/v2?checkout=cancel&provider=stripe&kind=founding&plan={plan}",
            client_reference_id=str(request.user.id),
            metadata={"kind": cfg["kind"], "user_id": str(request.user.id), "plan": plan},
        )
        return Response({"url": session.url, "id": session.id, "plan": plan})


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

        from django.contrib.auth import get_user_model
        etype = event["type"]
        if etype == "checkout.session.completed":
            obj = event["data"]["object"]
            meta = obj.get("metadata") or {}
            kind = meta.get("kind")
            uid = meta.get("user_id") or obj.get("client_reference_id")
            user = get_user_model().objects.filter(pk=uid).first() if uid else None
            if kind == "lifetime" and user:
                grant_lifetime(user)  # idempotent
            elif kind == "founding_sub" and user:
                # Founding StatZ subscription — grant the tier and remember the
                # Stripe customer so a cancellation can downgrade the right user.
                m = membership_for(user)
                m.tier = FOUNDING_TIER
                cust = obj.get("customer")
                if cust:
                    m.stripe_customer_id = cust
                m.save(update_fields=["tier", "stripe_customer_id", "updated_at"])
            else:
                intent = PaymentIntent.objects.filter(
                    provider=PaymentIntent.PROVIDER_STRIPE, provider_ref=obj.get("id")
                ).first()
                if intent:
                    _complete_intent(intent)
        elif etype == "customer.subscription.deleted":
            # Founding StatZ subscription ended — downgrade to Free (unless lifetime).
            from .models import Membership
            cust = (event["data"]["object"] or {}).get("customer")
            if cust:
                m = Membership.objects.filter(stripe_customer_id=cust, lifetime=False).first()
                if m:
                    m.tier = "free"
                    m.save(update_fields=["tier", "updated_at"])
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
