import re

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import OAuthIdentity, Profile
from .oauth import (
    OAUTH2_PROVIDERS,
    OAuthError,
    exchange_github,
    exchange_oauth2,
    verify_apple,
    verify_google,
)
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


def _clean_persona(raw):
    """Normalize one PersonaZ entry, keeping its skills and their start dates.

    Accepts the string form (just a key) and the dict form; always returns a
    dict so downstream code has one shape to reason about. Start dates are the
    input to profile_max_experience, so they are preserved when they look like a
    date and dropped when they don't.

    The date handling is deliberately generous. The skill picker writes
    `{name, startDate: "7/4/2020"}` while this only ever looked for a `start` key
    in ISO form — so every skill was stored undated and profile_max_experience
    answered None for everybody, no matter how long they'd been playing. Both
    field names and both formats are accepted now and stored as YYYY-MM-DD.
    """
    from apps.economy.personaz import normalize_start

    if not isinstance(raw, dict):
        return {"key": str(raw)[:60], "name": str(raw)[:60], "skills": []}

    skills = []
    for s in (raw.get("skills") or [])[:100]:
        if isinstance(s, dict):
            name = str(s.get("name", ""))[:80]
            start = normalize_start(
                s.get("start") or s.get("startDate") or s.get("start_date")
            )
        else:
            name, start = str(s)[:80], None
        if not name:
            continue
        skills.append({"name": name, "start": start} if start else {"name": name})

    key = str(raw.get("key") or raw.get("name") or "")[:60]
    return {"key": key, "name": str(raw.get("name") or key)[:60], "skills": skills}


def _user_from_oauth(info):
    """Find-or-create a user from a verified OAuth payload, return (user).

    Matching an existing account by email hands the caller that account, so we
    only do it when the provider actually ASSERTED the address is verified.
    A provider that lets someone set an arbitrary unverified email would
    otherwise be a way to take over any account by claiming its address.
    """
    identity = OAuthIdentity.objects.filter(
        provider=info["provider"], provider_uid=info["uid"]
    ).first()
    if identity:
        return identity.user

    user = None
    if info.get("email"):
        match = User.objects.filter(email__iexact=info["email"]).first()
        if match and not info.get("email_verified"):
            # Refuse rather than silently opening a second account on the same
            # address — duplicate emails would also make password login
            # ambiguous, since it resolves an identifier to a single user.
            raise OAuthError(
                f"An account already uses {info['email']}. "
                f"{info['provider'].title()} didn't confirm you own that address, "
                "so sign in with your original method and link it from there."
            )
        user = match

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
    throttle_scope = "auth-register"

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
    throttle_scope = "auth-login"

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        tokens = issue_tokens(user)
        return Response({"user": PublicUserSerializer(user).data, **tokens})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Self-heal owner promotion on any authenticated load.
        try:
            from apps.economy.views import ensure_owner
            ensure_owner(request.user)
            request.user.refresh_from_db()
        except Exception:
            pass
        return Response(PublicUserSerializer(request.user).data)

    def patch(self, request):
        """Update the member's editable profile fields (personas, birthday →
        drives ZodiacZ + the AdZ age gate, nationalities, and basic display
        bits) on the searchable economy profile. Returns the updated user."""
        from apps.economy.models import profile_for, zodiac_for
        p = profile_for(request.user)
        data = request.data or {}
        changed = []
        if isinstance(data.get("personas"), list):
            # A persona is {"key", "name", "skills": [{"name", "start"}]} once
            # the member has used the skill picker, or a bare key string from
            # before it existed. Stringifying everything flattened the dict form
            # to "{'key': ...}" and destroyed the skills — and with them the
            # start dates the whole experience metric is derived from.
            p.personas = [_clean_persona(x) for x in data["personas"]][:50]
            changed.append("personas")
        if isinstance(data.get("genres"), (list, str)):
            # Closed vocabulary: unknown genres are dropped rather than stored,
            # because a genre nobody can search for is not a genre.
            from apps.economy.genrez import normalize_genres
            p.genres = normalize_genres(data["genres"])
            changed.append("genres")
        if isinstance(data.get("nationalities"), list):
            p.nationalities = [str(x)[:60] for x in data["nationalities"]][:30]
            changed.append("nationalities")
        if "birthday" in data:
            bd = (data.get("birthday") or "")
            bd = bd.strip()[:10] if isinstance(bd, str) else ""
            p.birthday = bd
            p.sign = zodiac_for(bd)
            changed += ["birthday", "sign"]
        # Truncate to each column's real width — display_name/location/gender are
        # much narrower than bio, and overflowing them raises a DataError (500)
        # on PostgreSQL instead of quietly saving.
        for f in ("display_name", "bio", "location", "gender"):
            if isinstance(data.get(f), str):
                limit = p._meta.get_field(f).max_length
                setattr(p, f, data[f][:limit])
                changed.append(f)
        if changed:
            p.save(update_fields=list(dict.fromkeys(changed + ["updated_at"])))
        return Response(PublicUserSerializer(request.user).data)

    def delete(self, request):
        """Permanently delete the signed-in account and its owned data. FK
        cascades remove profile, wallet, membership, posts, follows, etc.
        Required for app-store login policies + GDPR/CCPA erasure."""
        user = request.user
        username = user.username
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReferralsView(APIView):
    """GET /api/auth/referrals/ — my referral code (username) + join stats."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.economy.models import (
            REFERRAL_REWARD_REFERRER_SPINAZ,
            Referral,
        )
        made = Referral.objects.filter(referrer=request.user).count()
        return Response({
            "code": request.user.username,
            "count": made,
            "spinaz_earned": made * REFERRAL_REWARD_REFERRER_SPINAZ,
            "reward_per_join": REFERRAL_REWARD_REFERRER_SPINAZ,
        })


class OnboardCompleteView(APIView):
    """POST /api/auth/onboard/complete/ — claim the one-time onboarding reward
    (idempotent). GET returns current status."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.economy.models import profile_for
        return Response({"onboarded": profile_for(request.user).onboarded})

    def post(self, request):
        from apps.economy.models import (
            ONBOARD_REWARD_ENERGY,
            ONBOARD_REWARD_SPINAZ,
            complete_onboarding,
        )
        result = complete_onboarding(request.user)
        return Response({
            "onboarded": True,
            "granted": not result["already"],
            "reward_spinaz": ONBOARD_REWARD_SPINAZ,
            "reward_energy": ONBOARD_REWARD_ENERGY,
        })


class OAuthLoginView(APIView):
    """POST /api/auth/oauth/<provider>/ — verify provider token, return JWT."""

    permission_classes = [AllowAny]
    # Unauthenticated, and every call reaches out to Google/GitHub/Apple —
    # without a cap this endpoint is a free proxy for hammering them.
    throttle_scope = "auth-oauth"

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
            elif provider in OAUTH2_PROVIDERS:
                info = exchange_oauth2(
                    provider,
                    data.get("code"),
                    data.get("redirect_uri", ""),
                    data.get("code_verifier", ""),
                )
            else:
                return Response(
                    {"detail": f"Unsupported provider '{provider}'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # Linking lives inside the same try so a refused link answers 400
            # with its reason, not a 500.
            user = _user_from_oauth(info)
        except OAuthError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        tokens = issue_tokens(user)
        return Response({"user": PublicUserSerializer(user).data, **tokens})


class OAuthConfigView(APIView):
    """GET /api/auth/oauth-config/ — the PUBLIC OAuth client IDs the backend is
    configured with, so the login buttons can read them at runtime instead of
    relying on build-time VITE_* vars. Client IDs are public; secrets stay here.
    Covers every provider the backend can complete a sign-in for — the id_token
    verifiers (google/apple), GitHub, and the generic code-flow providers
    (spotify/microsoft/facebook/soundcloud/twitter)."""

    permission_classes = [AllowAny]

    def get(self, request):
        import os

        from django.conf import settings

        cfg = {
            "google": getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "") or "",
            "github": getattr(settings, "GITHUB_OAUTH_CLIENT_ID", "") or "",
            "apple": getattr(settings, "APPLE_OAUTH_CLIENT_ID", "") or "",
        }
        # Generic code-flow providers advertise their PUBLIC client id from env;
        # a provider stays hidden/disabled on the client until its id is present.
        for provider in OAUTH2_PROVIDERS:
            cfg[provider] = os.environ.get(f"{provider.upper()}_OAUTH_CLIENT_ID", "").strip()
        return Response(cfg)
