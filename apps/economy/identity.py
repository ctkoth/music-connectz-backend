"""18+ age verification via Stripe Identity.

A member starts a Stripe Identity VerificationSession (government ID + selfie);
Stripe runs the check and fires `identity.verification_session.verified`. The
webhook (payments.StripeWebhookView) then fetches the verified date-of-birth
and, only if it proves the member is 18 or older, sets
`Profile.verified_18plus`. This is the real gate for money betting (BattleZ) and
adult content — a self-reported birthday is never trusted for it.

**Fetches**, not reads. The event body carries the session's status and nothing
personal — no `verified_outputs`, by design on Stripe's side. So the DOB comes
from a retrieve with `expand=["verified_outputs"]`, and a verification that
can't be read leaves the member unverified rather than waved through.
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


def _pluck(obj, key):
    """Read one key from either a plain dict or a Stripe object.

    Both support `[]`; only one of them supports `.get()`, and which one that
    is has changed with the library version. Subscript is the stable answer.
    """
    try:
        return obj[key]
    except (KeyError, TypeError, AttributeError):
        return None


def _verified_dob(session):
    """The verified date of birth, fetching it if the event didn't carry one.

    Stripe withholds `verified_outputs` from the webhook body — the payload for
    a verified session contains the status and the report id and nothing
    personal. Reading it straight off the event therefore always came back
    empty, so no member was ever marked 18+ by a check that had in fact
    passed. It only exists on a retrieve, and only when explicitly expanded.
    """
    dob = _pluck(_pluck(session, "verified_outputs") or {}, "dob")
    if dob:
        return dob
    session_id = _pluck(session, "id")
    if not (session_id and settings.STRIPE_SECRET_KEY):
        return {}
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        full = stripe.identity.VerificationSession.retrieve(
            session_id, expand=["verified_outputs"])
    except Exception:
        # A verification we can't read is not a verification. Leaving the flag
        # unset is the safe failure for an age gate: the member is asked again,
        # rather than being let through on a check that never completed.
        return {}
    return _pluck(_pluck(full, "verified_outputs") or {}, "dob") or {}


def mark_18plus_from_session(session):
    """Called from the Stripe webhook on a verified session. Sets the profile
    flag iff the verified DOB proves 18+. Idempotent.

    Returns (ok, reason) so callers can log what happened.
    """
    from django.contrib.auth import get_user_model
    meta = _pluck(session, "metadata") or {}
    uid = _pluck(meta, "user_id")
    if not uid:
        return False, "No user_id in session metadata"
    user = get_user_model().objects.filter(pk=uid).first()
    if not user:
        return False, f"User {uid} not found"
    age = _age_from_dob(_verified_dob(session))
    if age is None:
        return False, "Could not read verified DOB from session"
    if age < 18:
        return False, f"User is {age}, under 18"
    p = profile_for(user)
    if not p.verified_18plus:
        p.verified_18plus = True
        p.verified_18plus_at = timezone.now()
        p.save(update_fields=["verified_18plus", "verified_18plus_at", "updated_at"])
    return True, "Marked 18+ verified"


class IdentityView(APIView):
    """GET the caller's 18+ status; POST starts a Stripe Identity session."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        p = profile_for(request.user)
        # If a verification session was recently started but hasn't completed,
        # report "pending" so the frontend can show "waiting for Stripe..." instead
        # of falsely claiming verification failed.
        status_text = ""
        if p.verified_18plus:
            status_text = "verified"
        elif p.stripe_verification_attempted_at:
            # Less than 10 minutes ago, it's probably still pending. After 10
            # minutes with no webhook, something went wrong.
            elapsed = timezone.now() - p.stripe_verification_attempted_at
            if elapsed.total_seconds() < 600:
                status_text = "pending"
            else:
                status_text = "failed"
        return Response({
            "verified_18plus": p.verified_18plus,
            "verified_at": p.verified_18plus_at.isoformat() if p.verified_18plus_at else None,
            "status": status_text,  # "verified" | "pending" | "failed" | ""
            "attempted_at": p.stripe_verification_attempted_at.isoformat() if p.stripe_verification_attempted_at else None,
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
            return_url=f"{settings.FRONTEND_URL}/?verify=done",
        )
        # Record the attempt so the GET endpoint can tell the frontend whether
        # verification is pending (started but webhook hasn't fired yet) or done.
        p.stripe_verification_session_id = session.id
        p.stripe_verification_attempted_at = timezone.now()
        p.save(update_fields=["stripe_verification_session_id", "stripe_verification_attempted_at", "updated_at"])
        # `url` is the hosted verification flow the client redirects to.
        return Response({"url": session.url, "client_secret": session.client_secret, "id": session.id})
