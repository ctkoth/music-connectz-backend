"""Authentication for Music ConnectZ.

Out of the box (no config needed): username/password register, login, refresh, me
— returns {access, refresh, user}, matching what the frontend already posts to
/api/auth/register/ and /api/auth/login/.

OAuth (Google + GitHub): works once you set the provider client id/secret in env.
Flow for a website: frontend opens /api/auth/oauth/<provider>/start/, user
approves, provider redirects to /api/auth/oauth/<provider>/callback/, we create or
link the user and redirect to the frontend with freshly minted platform JWTs.
"""
import secrets
import urllib.parse

import requests
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.shortcuts import redirect
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import RegisterSerializer, UserSerializer

User = get_user_model()


def _tokens_for(user):
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def _auth_payload(user):
    return {**_tokens_for(user), "user": UserSerializer(user).data}


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        ser = RegisterSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = ser.save()
        return Response(_auth_payload(user), status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get("username") or request.data.get("email")
        password = request.data.get("password")
        user = authenticate(username=username, password=password)
        if user is None and username and "@" in str(username):
            # allow login by email
            match = User.objects.filter(email__iexact=username).first()
            if match:
                user = authenticate(username=match.username, password=password)
        if user is None:
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(_auth_payload(user))


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


# ── OAuth ───────────────────────────────────────────────────────────────────
def _callback_url(provider):
    return f"{settings.BACKEND_URL}/api/auth/oauth/{provider}/callback/"


def _link_or_create(email, username_hint):
    email = (email or "").strip().lower()
    if email:
        user = User.objects.filter(email__iexact=email).first()
        if user:
            return user
    base = (username_hint or (email.split("@")[0] if email else "user")).strip() or "user"
    username = base
    i = 0
    while User.objects.filter(username__iexact=username).exists():
        i += 1
        username = f"{base}{i}"
    user = User.objects.create_user(username=username, email=email)
    user.set_unusable_password()
    user.save()
    return user


def _finish(user):
    t = _tokens_for(user)
    frag = urllib.parse.urlencode({"access": t["access"], "refresh": t["refresh"]})
    return redirect(f"{settings.FRONTEND_URL}/#/oauth?{frag}")


class OAuthStartView(APIView):
    permission_classes = [AllowAny]
    provider = None

    def get(self, request):
        p = self.provider
        if p == "google":
            cid = settings.GOOGLE_OAUTH_CLIENT_ID
            if not cid:
                return Response({"detail": "Google OAuth not configured."}, status=501)
            params = {
                "client_id": cid, "redirect_uri": _callback_url("google"),
                "response_type": "code", "scope": "openid email profile",
                "access_type": "online", "prompt": "select_account",
            }
            return Response({"url": "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)})
        if p == "github":
            cid = settings.GITHUB_OAUTH_CLIENT_ID
            if not cid:
                return Response({"detail": "GitHub OAuth not configured."}, status=501)
            params = {"client_id": cid, "redirect_uri": _callback_url("github"),
                      "scope": "read:user user:email", "state": secrets.token_urlsafe(16)}
            return Response({"url": "https://github.com/login/oauth/authorize?" + urllib.parse.urlencode(params)})
        return Response({"detail": "Unknown provider."}, status=400)


class OAuthCallbackView(APIView):
    permission_classes = [AllowAny]
    provider = None

    def get(self, request):
        code = request.query_params.get("code")
        if not code:
            return Response({"detail": "Missing code."}, status=400)
        p = self.provider
        try:
            if p == "google":
                tok = requests.post("https://oauth2.googleapis.com/token", data={
                    "code": code, "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                    "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                    "redirect_uri": _callback_url("google"), "grant_type": "authorization_code",
                }, timeout=15).json()
                access = tok.get("access_token")
                info = requests.get("https://www.googleapis.com/oauth2/v2/userinfo",
                                    headers={"Authorization": f"Bearer {access}"}, timeout=15).json()
                user = _link_or_create(info.get("email"), info.get("name") or info.get("email"))
                return _finish(user)
            if p == "github":
                tok = requests.post("https://github.com/login/oauth/access_token", headers={"Accept": "application/json"},
                                    data={"code": code, "client_id": settings.GITHUB_OAUTH_CLIENT_ID,
                                          "client_secret": settings.GITHUB_OAUTH_CLIENT_SECRET,
                                          "redirect_uri": _callback_url("github")}, timeout=15).json()
                access = tok.get("access_token")
                h = {"Authorization": f"Bearer {access}", "Accept": "application/json"}
                profile = requests.get("https://api.github.com/user", headers=h, timeout=15).json()
                email = profile.get("email")
                if not email:
                    emails = requests.get("https://api.github.com/user/emails", headers=h, timeout=15).json()
                    if isinstance(emails, list):
                        primary = next((e for e in emails if e.get("primary")), emails[0] if emails else {})
                        email = primary.get("email")
                user = _link_or_create(email, profile.get("login"))
                return _finish(user)
        except Exception as exc:  # noqa: BLE001
            return Response({"detail": f"OAuth failed: {exc}"}, status=502)
        return Response({"detail": "Unknown provider."}, status=400)
