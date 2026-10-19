"""18+ age verification via Stripe Identity.

**Every check ends in a stated result.** One `IdentityCheck` row per session records how it
ended and why — SUCCESS, or FAILURE with the reason in words — and `GET /identity/` serves it,
so a member is never left guessing whether a scan worked. After a success a new scan is
refused (it would cost a Stripe check to prove what is already proven); after failures the
number of scans a day is capped, with the last reason in the refusal. The webhook is not the
only way an outcome arrives: GET and POST first ask Stripe about any session still open, so a
deploy with the identity webhook unconfigured still reports results.

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



MAX_FAILED_PER_DAY = 3
REUSE_OPEN_MINUTES = 30

REASONS = {
    "document_expired": "The ID has expired. Use one that is still valid.",
    "document_type_not_supported": "That kind of ID is not accepted. Use a passport, driver's licence or national ID card.",
    "document_unverified_other": "The ID could not be read or confirmed. Retake the photos in good light with all four corners visible.",
    "selfie_face_mismatch": "The selfie did not match the photo on the ID.",
    "selfie_document_missing_photo": "The ID photo could not be seen. Make sure your photo is not covered or cut off.",
    "selfie_manipulated": "The selfie looked altered or was not a live capture. Take it fresh with your camera.",
    "selfie_unverified_other": "The selfie could not be confirmed. Take it again facing the camera in good light.",
    "country_not_supported": "IDs from that country cannot be checked yet.",
    "under_supported_age": "The check does not accept IDs for someone that age.",
    "consent_declined": "The consent step was declined, so the check could not run.",
    "device_unsupported": "That device or browser cannot do the check. Try a phone with a camera.",
    "abandoned": "The check was left unfinished.",
    "under_18": "The ID is genuine but shows you are under 18, so the 18+ badge was not granted.",
    "unreadable": "The ID passed but its date of birth could not be read back, so the badge was not granted. Try again.",
    "canceled": "The check was cancelled before it finished.",
}


def reason_sentence(code):
    if not code:
        return ""
    return REASONS.get(code) or f"Stripe could not verify it (reason: {code})."


def _create_or_get(user, session):
    from .models import IdentityCheck
    sid = _pluck(session, "id")
    if not sid:
        return None
    row = IdentityCheck.objects.filter(session_id=sid).first()
    if row is None:
        row = IdentityCheck.objects.create(user=user, session_id=sid)
    return row if row.user_id == user.id else None


def apply_session(session, user=None):
    """Record how this session ended and, on a real pass at 18+, set the profile flag.
    Idempotent, and a final result is never overwritten by a later, stale event."""
    from django.contrib.auth import get_user_model
    from .models import IdentityCheck
    if user is None:
        uid = _pluck(_pluck(session, "metadata") or {}, "user_id")
        user = get_user_model().objects.filter(pk=uid).first() if uid else None
    if not user:
        return None
    row = _create_or_get(user, session)
    if row is None or row.status not in IdentityCheck.OPEN:
        return row
    st = _pluck(session, "status")
    if st == "verified":
        age = _age_from_dob(_verified_dob(session))
        if age is None:
            row.status, row.reason = IdentityCheck.UNREADABLE, "unreadable"
        elif age < 18:
            row.status, row.reason = IdentityCheck.UNDER_18, "under_18"
        else:
            row.status, row.reason = IdentityCheck.VERIFIED, ""
            p = profile_for(user)
            if not p.verified_18plus:
                p.verified_18plus = True
                p.verified_18plus_at = timezone.now()
                p.save(update_fields=["verified_18plus", "verified_18plus_at", "updated_at"])
    elif st == "requires_input":
        err = _pluck(session, "last_error") or {}
        code = _pluck(err, "code")
        if not code:
            return row                      # still waiting on the member to finish; not an ending
        row.status, row.reason = IdentityCheck.FAILED, str(code)[:60]
    elif st == "canceled":
        row.status, row.reason = IdentityCheck.CANCELED, "canceled"
    elif st == "processing":
        row.status = IdentityCheck.PROCESSING
    else:
        return row
    row.save(update_fields=["status", "reason", "updated_at"])
    return row


def mark_18plus_from_session(session):
    """Webhook entry (every identity.verification_session.* event)."""
    apply_session(session)


def refresh(user):
    """Ask Stripe about this member's sessions that have not ended. Best effort: a Stripe
    outage leaves them open, which the screen reports as 'still checking'."""
    from .models import IdentityCheck
    if not settings.STRIPE_SECRET_KEY:
        return
    cutoff = timezone.now() - datetime.timedelta(days=2)
    open_rows = list(IdentityCheck.objects.filter(user=user, status__in=IdentityCheck.OPEN, created_at__gte=cutoff)[:5])
    if not open_rows:
        return
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    for row in open_rows:
        try:
            full = stripe.identity.VerificationSession.retrieve(row.session_id, expand=["verified_outputs"])
        except Exception:
            continue
        apply_session(full, user=user)


def _last(user):
    from .models import IdentityCheck
    return IdentityCheck.objects.filter(user=user).first()


def _result(row):
    """The outcome in words. `result` is the one-word answer the screen leads with."""
    from .models import IdentityCheck
    if row is None:
        return None
    if row.status == IdentityCheck.VERIFIED:
        return {"result": "success", "detail": "Your ID was checked and you are verified 18+.", "reason": "", "at": row.updated_at.isoformat()}
    if row.status in IdentityCheck.OPEN:
        return {"result": "pending", "detail": "Stripe is still checking your ID. This usually takes a minute or two.", "reason": "", "at": row.created_at.isoformat()}
    return {"result": "failure", "detail": reason_sentence(row.reason) or "The check did not pass.",
            "reason": row.reason, "at": row.updated_at.isoformat()}


def _failed_today(user):
    from .models import IdentityCheck
    since = timezone.now() - datetime.timedelta(hours=24)
    return IdentityCheck.objects.filter(user=user, created_at__gte=since).exclude(
        status__in=(IdentityCheck.VERIFIED,) + IdentityCheck.OPEN).count()


class IdentityView(APIView):
    """GET the caller's 18+ status and how the last check ended; POST starts a Stripe Identity session."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        refresh(request.user)
        p = profile_for(request.user)
        left = max(0, MAX_FAILED_PER_DAY - _failed_today(request.user))
        return Response({
            "verified_18plus": p.verified_18plus,
            "verified_at": p.verified_18plus_at.isoformat() if p.verified_18plus_at else None,
            "stripe_enabled": bool(settings.STRIPE_SECRET_KEY),
            "last": _result(_last(request.user)),
            "attempts_left_today": 0 if p.verified_18plus else left,
            "can_start": (not p.verified_18plus) and left > 0,
        })

    def post(self, request):
        from .models import IdentityCheck
        if not settings.STRIPE_SECRET_KEY:
            return Response({"detail": "Identity verification is not configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        refresh(request.user)                                   # a finished check is counted before another starts
        p = profile_for(request.user)
        if p.verified_18plus:
            return Response({"verified_18plus": True, "already": True,
                             "detail": "You are already verified 18+. A new scan is not needed."})
        if _failed_today(request.user) >= MAX_FAILED_PER_DAY:
            last = _result(_last(request.user)) or {}
            return Response({"detail": (f"{MAX_FAILED_PER_DAY} checks did not pass in the last 24 hours, so a new one cannot start yet. "
                                        f"The last said: {last.get('detail', 'it did not pass')} Try again tomorrow."),
                             "last": last}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        # A check still open (waiting on Stripe, or started but not finished) is picked up, not duplicated.
        row = _last(request.user)
        if row and row.status == IdentityCheck.PROCESSING:
            return Response({"pending": True, "last": _result(row), "detail": _result(row)["detail"]})
        if row and row.status == IdentityCheck.STARTED and row.url and \
                row.created_at >= timezone.now() - datetime.timedelta(minutes=REUSE_OPEN_MINUTES):
            return Response({"url": row.url, "id": row.session_id, "reused": True})
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        session = stripe.identity.VerificationSession.create(
            type="document",
            metadata={"user_id": str(request.user.id)},
            options={"document": {"require_matching_selfie": True}},
            return_url=f"{settings.FRONTEND_URL}/?verify=done",
        )
        IdentityCheck.objects.create(user=request.user, session_id=session.id, url=str(session.url or "")[:500])
        # `url` is the hosted verification flow the client redirects to.
        return Response({"url": session.url, "client_secret": session.client_secret, "id": session.id})
