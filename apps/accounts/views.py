import re

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import OAuthIdentity, Profile
from .oauth import OAuthError, exchange_github, verify_apple, verify_google
from .serializers import (
    LoginSerializer,
    PublicUserSerializer,
    RegisterSerializer,
    issue_tokens,
)

User = get_user_model()


def _unique_username(base):
    base = re.sub(r"[^a-zA-Z0-9_.-]", "", (base or "user")).strip(".-_") or "user"
    candidate = base[:140]
    i = 1
    while User.objects.filter(username__iexact=candidate).exists():
        candidate = f"{base[:140]}{i}"
        i += 1
    return candidate


def _user_from_oauth(info):
    """Find-or-create a user from a verified OAuth payload, return (user)."""
    identity = OAuthIdentity.objects.filter(
        provider=info["provider"], provider_uid=info["uid"]
    ).first()
    if identity:
        return identity.user

    user = None
    if info.get("email"):
        user = User.objects.filter(email__iexact=info["email"]).first()

    if not user:
        base = info.get("name") or (info["email"].split("@")[0] if info.get("email") else info["provider"])
        user = User.objects.create_user(
            username=_unique_username(base),
            email=info.get("email", ""),
        )
        user.set_unusable_password()
        user.save()

    Profile.objects.get_or_create(
        user=user, defaults={"avatar_url": info.get("avatar_url", "")}
    )
    OAuthIdentity.objects.get_or_create(
        provider=info["provider"],
        provider_uid=info["uid"],
        defaults={"user": user, "email": info.get("email", "")},
    )
    return user


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        tokens = issue_tokens(user)
        return Response(
            {"user": PublicUserSerializer(user).data, **tokens},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        tokens = issue_tokens(user)
        return Response({"user": PublicUserSerializer(user).data, **tokens})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(PublicUserSerializer(request.user).data)


class OAuthLoginView(APIView):
    """POST /api/auth/oauth/<provider>/ — verify provider token, return JWT."""

    permission_classes = [AllowAny]

    def post(self, request, provider):
        data = request.data or {}
        try:
            if provider == "google":
                info = verify_google(data.get("credential") or data.get("id_token"))
            elif provider == "github":
                info = exchange_github(
                    data.get("code"), data.get("redirect_uri", "")
                )
            elif provider == "apple":
                info = verify_apple(data.get("id_token") or data.get("credential"))
            else:
                return Response(
                    {"detail": f"Unsupported provider '{provider}'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except OAuthError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        user = _user_from_oauth(info)
        tokens = issue_tokens(user)
        return Response({"user": PublicUserSerializer(user).data, **tokens})
