"""
Password reset — request a link, then redeem it.

Built on Django's own PasswordResetTokenGenerator rather than a token model, so
there is no extra table and no cleanup job. Those tokens carry three properties
worth knowing:

  * they expire on their own (settings.PASSWORD_RESET_TIMEOUT, 3 days default);
  * they are single-use in practice — the hash mixes in the current password
    hash and last_login, so redeeming one invalidates it and every older one;
  * they are unguessable without SECRET_KEY.

The frontend pages are /forgot (asks for an identifier) and /reset-password
(reads ?uid= and ?token= off the query string), so the emailed link must point
at FRONTEND_URL/reset-password with exactly those two parameters.
"""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db.models import Q
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import issue_tokens, revoke_all_refresh_tokens

User = get_user_model()
logger = logging.getLogger(__name__)

# Deliberately identical whether or not an account matched. Saying "no account
# with that email" would turn this endpoint into a membership oracle.
SENT_DETAIL = (
    "If that account exists, we've sent a reset link to its email address. "
    "Check your spam folder if it doesn't arrive in a few minutes."
)


def _user_for_identifier(identifier):
    """Same three-way lookup as login: username, email, or profile phone."""
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    return (
        User.objects.filter(
            Q(username__iexact=identifier)
            | Q(email__iexact=identifier)
            | Q(profile__phone=identifier)
        )
        .distinct()
        .first()
    )


def reset_link_for(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    base = getattr(settings, "FRONTEND_URL", "").rstrip("/")
    return f"{base}/reset-password?uid={uid}&token={token}"


class ForgotPasswordView(APIView):
    """POST /api/auth/password/forgot/ — {identifier} -> emails a reset link."""

    permission_classes = [AllowAny]
    throttle_scope = "auth-password"
    authentication_classes = []

    def post(self, request):
        user = _user_for_identifier((request.data or {}).get("identifier"))

        # An account with no email address on file has nowhere to send the link.
        # Still answer with SENT_DETAIL so the response reveals nothing.
        if user and not user.email:
            logger.warning(
                "Password reset requested for %r, but that account has no email "
                "address on file — nothing was sent.", user.username,
            )

        if user and user.email:
            link = reset_link_for(user)
            try:
                # fail_silently=False so the exception reaches the handler below
                # and gets logged. The RESPONSE is unchanged either way — a
                # caller must not be able to tell delivery from failure, or from
                # the account not existing.
                send_mail(
                    subject="Reset your Music ConnectZ password",
                    message=(
                        f"Hi {user.username},\n\n"
                        "Someone asked to reset the password on your Music ConnectZ "
                        "account. Open this link to choose a new one:\n\n"
                        f"{link}\n\n"
                        "The link expires in a few days and can only be used once. "
                        "If this wasn't you, ignore this email — your password stays "
                        "as it is.\n\n"
                        "— Music ConnectZ"
                    ),
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                    recipient_list=[user.email],
                    fail_silently=False,
                )
                logger.info("Password reset link sent to %r.", user.username)
            except Exception:
                # Log the username, never the address — this line ends up in the
                # Render stream. The traceback carries the SMTP error, which is
                # the whole point: a misconfigured mail host used to fail in
                # complete silence.
                logger.exception(
                    "Password reset email FAILED for %r via EMAIL_HOST=%r port=%s "
                    "TLS=%s backend=%s",
                    user.username,
                    getattr(settings, "EMAIL_HOST", ""),
                    getattr(settings, "EMAIL_PORT", ""),
                    getattr(settings, "EMAIL_USE_TLS", ""),
                    getattr(settings, "EMAIL_BACKEND", ""),
                )

        return Response({"detail": SENT_DETAIL})


class ResetPasswordView(APIView):
    """POST /api/auth/password/reset/ — {uid, token, new_password} -> JWTs.

    Returns tokens on success so the member lands back in the app signed in,
    which is what the frontend's ResetPassword page expects.
    """

    permission_classes = [AllowAny]
    throttle_scope = "auth-password"
    authentication_classes = []

    def post(self, request):
        data = request.data or {}
        uid = data.get("uid") or ""
        token = data.get("token") or ""
        new_password = data.get("new_password") or ""

        invalid = Response(
            {"detail": "That reset link is invalid or has expired. Request a new one."},
            status=status.HTTP_400_BAD_REQUEST,
        )

        try:
            pk = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=pk)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return invalid

        if not default_token_generator.check_token(user, token):
            return invalid

        try:
            password_validation.validate_password(new_password, user)
        except Exception as exc:
            return Response(
                {"detail": " ".join(getattr(exc, "messages", [str(exc)]))},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Changing the password rotates the hash the token generator mixes in,
        # so this link — and any older one — stops working from here.
        user.set_password(new_password)
        user.save(update_fields=["password"])

        # And so does every session already signed in. A reset is what somebody
        # does when they think their account is taken; leaving the attacker's
        # refresh token alive for the rest of its fourteen days would make the
        # reset theatre. The new pair below is issued after the revocation, so
        # the person resetting stays signed in and everyone else is kicked out.
        revoke_all_refresh_tokens(user)

        from .serializers import PublicUserSerializer

        return Response({"user": PublicUserSerializer(user).data, **issue_tokens(user)})
