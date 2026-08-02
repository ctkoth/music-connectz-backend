"""18+ age verification via Stripe Identity.

A member starts a Stripe Identity VerificationSession (government ID + selfie);
Stripe runs the check and reports back. Only if the verified date of birth
proves the member is 18 or older does `Profile.verified_18plus` get set. This is
the real gate for money betting (BattleZ) and adult content — a self-reported
birthday is never trusted for it.

**Every outcome is recorded, not just success.** A member who finishes the flow
has to be told what happened; "not verified" looks identical to "never tried",
and leaving somebody staring at that is how you get a support ticket that says
"I did mine, I don't know if it passed."

Two paths keep the status fresh:

  * the webhook, which is the fast path, and
  * `POST {"action": "refresh"}`, which pulls the session straight from Stripe.

The second exists because webhooks genuinely go missing — a bad endpoint, a
deploy at the wrong moment — and a member whose only route to an answer is a
message that never arrived is stuck forever.
"""
import datetime

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Profile, profile_for

# Stripe's `last_error.code` turned into something a person can act on. The
# fallback matters as much as the entries: Stripe adds codes, and an unknown
# one must still produce a sentence rather than a blank box.
ERROR_COPY = {
    "consent_declined": "You declined the consent step, so the check couldn't run.",
    "device_unsupported": "That device couldn't run the ID check. Try a phone with a camera.",
    "abandoned": "The check was closed before it finished.",
    "under_supported_age": "Stripe won't verify someone under 13.",
    "country_not_supported": "ID checks aren't supported in that country yet.",
    "document_expired": "That ID is expired. Try a current one.",
    "document_type_not_supported": "That kind of document isn't accepted. Use a passport, "
                                   "driving licence, or national ID.",
    "document_unverified_other": "The document couldn't be read. Try again in better light, "
                                 "with the whole ID in frame.",
    "selfie_document_missing_photo": "That ID has no photo to match your selfie against.",
    "selfie_face_mismatch": "The selfie didn't match the photo on the ID.",
    "selfie_manipulated": "The selfie looked edited, so it couldn't be accepted.",
    "selfie_unverified_other": "The selfie couldn't be matched. Try again in better light.",
}

REASON_UNDER_18 = "under_18"
UNDER_18_DETAIL = ("Your ID checked out, but it shows you're under 18. Money "
                   "wagers and adult content stay locked until then — everything "
                   "else on Music ConnectZ works normally.")


def _age_from_dob(dob):
    """Age in whole years from a Stripe Identity dob dict {day,month,year}."""
    try:
        born = datetime.date(int(dob["year"]), int(dob["month"]), int(dob["day"]))
    except (KeyError, TypeError, ValueError):
        return None
    today = datetime.date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _save(profile, **fields):
    fields["verification_updated_at"] = timezone.now()
    for key, value in fields.items():
        setattr(profile, key, value)
    profile.save(update_fields=list(fields.keys()) + ["updated_at"])


def record_session(session, user=None):
    """Write whatever Stripe just told us onto the profile. Idempotent.

    Handles every session state, not only `verified`. Previously an under-18
    result and a failed document produced the same thing on screen as never
    having started — the function simply returned.
    """
    from django.contrib.auth import get_user_model

    session = session or {}
    if user is None:
        uid = (session.get("metadata") or {}).get("user_id")
        if not uid:
            return None
        user = get_user_model().objects.filter(pk=uid).first()
    if not user:
        return None

    p = profile_for(user)
    state = session.get("status") or ""
    session_id = session.get("id") or p.verification_session_id

    # A pass is terminal for an AGE gate — a date of birth doesn't change. Stripe
    # can deliver events out of order, and a late `created` or `processing` for
    # an old session would otherwise drop a verified member back to "Checking…".
    if p.verified_18plus and state != "verified":
        return p

    if state == "verified":
        dob = ((session.get("verified_outputs") or {}).get("dob")) or {}
        age = _age_from_dob(dob)
        if age is None:
            # Verified with no readable DOB. Not a pass for an AGE gate, and
            # saying "verified" would be a lie about the thing being checked.
            _save(p, verification_status=Profile.VERIFY_FAILED,
                  verification_reason="no_dob",
                  verification_detail="Your ID was accepted but we couldn't read a "
                                      "date of birth from it, so we can't confirm "
                                      "you're 18+. Try again with a different ID.",
                  verification_session_id=session_id)
        elif age < 18:
            _save(p, verification_status=Profile.VERIFY_FAILED,
                  verification_reason=REASON_UNDER_18,
                  verification_detail=UNDER_18_DETAIL,
                  verification_session_id=session_id)
        else:
            _save(p, verified_18plus=True,
                  verified_18plus_at=p.verified_18plus_at or timezone.now(),
                  verification_status=Profile.VERIFY_VERIFIED,
                  verification_reason="", verification_detail="",
                  verification_session_id=session_id)

    elif state == "processing":
        _save(p, verification_status=Profile.VERIFY_PROCESSING,
              verification_reason="", verification_session_id=session_id,
              verification_detail="Stripe is checking your ID. This usually takes "
                                  "under a minute.")

    elif state == "requires_input":
        err = session.get("last_error") or {}
        if not err:
            # `requires_input` is ALSO the status of a brand-new session — it
            # means "waiting on the member", and `identity.verification_session.
            # created` fires with it before they have done anything at all.
            # Without this branch, starting a check instantly reads as "Didn't
            # pass", which is worse than the silence it replaced.
            _save(p, verification_status=Profile.VERIFY_PROCESSING,
                  verification_reason="",
                  verification_detail="Waiting for you to finish the ID check.",
                  verification_session_id=session_id)
        else:
            code = err.get("code") or "unknown"
            _save(p, verification_status=Profile.VERIFY_FAILED,
                  verification_reason=code,
                  verification_detail=ERROR_COPY.get(
                      code,
                      err.get("reason") or "That check didn't go through. You can try again."),
                  verification_session_id=session_id)

    elif state == "canceled":
        _save(p, verification_status=Profile.VERIFY_CANCELED,
              verification_reason="canceled",
              verification_detail="The check was cancelled before it finished.",
              verification_session_id=session_id)

    return p


def mark_18plus_from_session(session):
    """Back-compat name used by the Stripe webhook."""
    return record_session(session)


def status_payload(profile):
    """Everything the screen needs to say what happened — headline, detail, and
    what to do next. The client shouldn't have to own this copy; then two
    clients would word a failure two different ways."""
    state = profile.verification_status
    verified = bool(profile.verified_18plus)
    under_18 = profile.verification_reason == REASON_UNDER_18

    headline = {
        Profile.VERIFY_UNSTARTED: "Not verified yet",
        Profile.VERIFY_PROCESSING: "Checking your ID…",
        Profile.VERIFY_VERIFIED: "Verified 18+ ✅",
        Profile.VERIFY_FAILED: "Didn't pass ❌",
        Profile.VERIFY_CANCELED: "Cancelled",
    }.get(state, "Not verified yet")

    if state == Profile.VERIFY_UNSTARTED:
        detail = ("Verify your age to unlock money wagers in BattleZ and adult "
                  "content. Takes about a minute — a photo ID and a selfie.")
        next_step = "Start verification"
    elif state == Profile.VERIFY_VERIFIED:
        detail = "You're verified. Money wagers and adult content are unlocked."
        next_step = None
    elif state == Profile.VERIFY_PROCESSING:
        detail = profile.verification_detail or "Stripe is still checking."
        next_step = "Refresh"
    else:
        detail = profile.verification_detail or "That check didn't go through."
        next_step = None if under_18 else "Try again"

    return {
        # The boolean stays, because everything else gates on it.
        "verified_18plus": verified,
        "verified_at": (profile.verified_18plus_at.isoformat()
                        if profile.verified_18plus_at else None),
        "status": state,
        "reason": profile.verification_reason or None,
        "headline": headline,
        "detail": detail,
        "next_step": next_step,
        # Retrying an under-18 result is not a retry, it's the same answer with
        # more steps. Say so instead of inviting them to waste the attempt.
        "can_retry": state in (Profile.VERIFY_FAILED, Profile.VERIFY_CANCELED,
                               Profile.VERIFY_UNSTARTED) and not under_18,
        "attempts": profile.verification_attempts,
        "checked_at": (profile.verification_updated_at.isoformat()
                       if profile.verification_updated_at else None),
        "stripe_enabled": bool(settings.STRIPE_SECRET_KEY),
    }


def refresh_from_stripe(user):
    """Pull the session straight from Stripe. Returns (payload, error).

    The webhook is the fast path, not the only one. If it never arrives the
    member would otherwise sit on "Checking…" indefinitely with no way out.
    """
    p = profile_for(user)
    if not p.verification_session_id:
        return status_payload(p), None
    if not settings.STRIPE_SECRET_KEY:
        return status_payload(p), "Identity verification is not configured."
    try:
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        session = stripe.identity.VerificationSession.retrieve(p.verification_session_id)
    except Exception:
        # Don't surface a Stripe stack trace to a member; the stored status is
        # still the best answer we have.
        return status_payload(p), "Couldn't reach Stripe just now. Try again in a moment."
    record_session(dict(session), user=user)
    return status_payload(profile_for(user)), None


class IdentityView(APIView):
    """GET the caller's verification status; POST starts or refreshes a check."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(status_payload(profile_for(request.user)))

    def post(self, request):
        action = (request.data or {}).get("action")
        if action == "refresh":
            payload, error = refresh_from_stripe(request.user)
            if error:
                payload["error"] = error
            return Response(payload)

        # What we already know about this member comes FIRST. Whether Stripe is
        # configured is our problem, not theirs — telling somebody already
        # verified, or already told they're under 18, that the service is
        # unavailable answers a question they didn't ask.
        p = profile_for(request.user)
        if p.verified_18plus:
            return Response({**status_payload(p), "already": True})
        if p.verification_reason == REASON_UNDER_18:
            # Re-running the check cannot change their date of birth.
            return Response({**status_payload(p), "detail": UNDER_18_DETAIL},
                            status=status.HTTP_403_FORBIDDEN)

        if not settings.STRIPE_SECRET_KEY:
            return Response({"detail": "Identity verification is not configured"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        session = stripe.identity.VerificationSession.create(
            type="document",
            metadata={"user_id": str(request.user.id)},
            options={"document": {"require_matching_selfie": True}},
            return_url=f"{settings.FRONTEND_URL}/?verify=done",
        )
        _save(p, verification_status=Profile.VERIFY_PROCESSING,
              verification_session_id=session.id,
              verification_reason="", verification_attempts=p.verification_attempts + 1,
              verification_detail="Finish the check in the window that opens.")
        # `url` is the hosted verification flow the client redirects to.
        return Response({"url": session.url, "client_secret": session.client_secret,
                         "id": session.id, **status_payload(profile_for(request.user))})
