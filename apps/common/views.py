"""Age-verification onboarding endpoints. The gates read UserFlags.age_status,
which is DERIVED here — never set directly by the user to 'adult'.
"""
import datetime

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import UserFlags


def _flags(user):
    obj, _ = UserFlags.objects.get_or_create(user=user)
    return obj


def _state(f):
    return {"age_status": f.age_status, "dob": f.dob, "age": f.age_years(),
            "adult_verified": f.adult_verified, "parental_consent": f.parental_consent}


class AgeStateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_state(_flags(request.user)))


class AgeDeclareView(APIView):
    """User submits date of birth. This alone NEVER grants adult — it only records
    DOB. Adults still need KYC (verify-adult); minors still need parental consent."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        dob = request.data.get("dob")  # 'YYYY-MM-DD'
        try:
            d = datetime.date.fromisoformat(dob)
        except (TypeError, ValueError):
            return Response({"detail": "dob must be YYYY-MM-DD"}, status=status.HTTP_400_BAD_REQUEST)
        if d > datetime.date.today():
            return Response({"detail": "dob in the future"}, status=status.HTTP_400_BAD_REQUEST)
        f = _flags(request.user)
        f.dob = d
        f.recompute()
        f.save()
        return Response(_state(f))


class ParentalConsentView(APIView):
    """Records parental consent for a minor. In production, call this only AFTER a
    verified guardian confirmation (e.g. signed email link); wire that check here."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        f = _flags(request.user)
        # TODO: verify guardian token before trusting this.
        f.parental_consent = bool(request.data.get("confirmed", True))
        f.recompute()
        f.save()
        return Response(_state(f))


class VerifyAdultView(APIView):
    """Marks a user as an age-verified ADULT. NOT self-serve: callable only by your
    KYC provider's webhook (shared secret) or a Django admin. This is the only path
    to 'adult'."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        secret = settings.__dict__.get("MCZ_KYC_SECRET") or getattr(settings, "MCZ_KYC_SECRET", None)
        header = request.headers.get("X-MCZ-KYC-Secret")
        is_admin = bool(getattr(request.user, "is_staff", False))
        if not (is_admin or (secret and header and header == secret)):
            return Response({"detail": "forbidden — KYC secret or admin required"},
                            status=status.HTTP_403_FORBIDDEN)
        # Which user are we verifying? admin/webhook may pass user_id; else self.
        from django.contrib.auth import get_user_model
        uid = request.data.get("user_id")
        target = request.user
        if uid:
            U = get_user_model()
            target = U.objects.filter(pk=uid).first() or request.user
        f = _flags(target)
        f.adult_verified = True
        f.recompute()
        f.save()
        return Response(_state(f))


# ── Stripe Identity (the real KYC path to 'adult') ───────────────────────────
import datetime as _dt

from django.conf import settings as _settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.permissions import AllowAny


def _stripe():
    """Lazy import so the app loads even if stripe isn't installed yet."""
    import stripe
    key = getattr(_settings, "STRIPE_SECRET_KEY", None) or __import__("os").environ.get("STRIPE_SECRET_KEY")
    if not key:
        return None
    stripe.api_key = key
    return stripe


class StripeIdentityStartView(APIView):
    """Create a Stripe Identity VerificationSession; returns the hosted URL to
    redirect the user to. On completion Stripe calls our webhook."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        stripe = _stripe()
        if stripe is None:
            return Response({"detail": "Stripe not configured (set STRIPE_SECRET_KEY)."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            session = stripe.identity.VerificationSession.create(
                type="document",
                metadata={"user_id": str(request.user.id)},
                options={"document": {"require_matching_selfie": True}},
            )
        except Exception as e:
            return Response({"detail": f"Stripe error: {e}"}, status=status.HTTP_502_BAD_GATEWAY)
        f = _flags(request.user)
        f.stripe_session_id = session.id
        f.save(update_fields=["stripe_session_id", "updated_at"])
        return Response({"url": session.url, "client_secret": session.client_secret})


@method_decorator(csrf_exempt, name="dispatch")
class StripeIdentityWebhookView(APIView):
    """Stripe -> us. Verifies signature, and on a VERIFIED session reads the real
    DOB and sets adult_verified ONLY if the verified age is >= 18 (minors are
    never marked adult, even though their ID verified)."""
    authentication_classes = []          # no session auth -> no CSRF
    permission_classes = [AllowAny]

    def post(self, request):
        stripe = _stripe()
        if stripe is None:
            return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)
        secret = getattr(_settings, "STRIPE_IDENTITY_WEBHOOK_SECRET", None) or \
            __import__("os").environ.get("STRIPE_IDENTITY_WEBHOOK_SECRET")
        sig = request.headers.get("Stripe-Signature")
        try:
            event = stripe.Webhook.construct_event(request.body, sig, secret)
        except Exception as e:
            return Response({"detail": f"bad signature: {e}"}, status=status.HTTP_400_BAD_REQUEST)

        if event["type"] == "identity.verification_session.verified":
            vs = event["data"]["object"]
            uid = (vs.get("metadata") or {}).get("user_id")
            try:
                full = stripe.identity.VerificationSession.retrieve(vs["id"], expand=["verified_outputs.dob"])
                dob_obj = (full.get("verified_outputs") or {}).get("dob") or {}
                dob = _dt.date(dob_obj["year"], dob_obj["month"], dob_obj["day"]) if dob_obj else None
            except Exception:
                dob = None
            from django.contrib.auth import get_user_model
            U = get_user_model()
            user = U.objects.filter(pk=uid).first() if uid else None
            if user:
                f = _flags(user)
                if dob:
                    f.dob = dob
                age = f.age_years()
                # Verified adult ONLY if real age >= 18. Minors are never made adult.
                f.adult_verified = bool(age is not None and age >= 18)
                f.recompute()
                f.save()
        return Response({"received": True})
