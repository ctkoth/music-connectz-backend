import re

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.economy.personaz import clean_persona

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


# The persona normalizer lives in apps.economy.personaz, next to the recovery
# for the rows that lost the shape and the sweep that repairs them. It used to
# be defined here, which meant the WRITE path knew how to normalize a persona
# and no read path did — so a member whose row was already mangled stayed
# mangled until they happened to save their profile again.
_clean_persona = clean_persona


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
        from apps.economy.catalog import over_char_limit
        from apps.economy.models import (EXPLICIT_MIN_AGE, may_be_explicit,
                                         membership_for, profile_for, zodiac_for)
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
        if isinstance(data.get("nationalities"), list):
            p.nationalities = [str(x)[:60] for x in data["nationalities"]][:30]
            changed.append("nationalities")
        if "birthday" in data:
            bd = (data.get("birthday") or "")
            bd = bd.strip()[:10] if isinstance(bd, str) else ""
            p.birthday = bd
            p.sign = zodiac_for(bd)
            changed += ["birthday", "sign"]
            # A birthday that no longer clears the bar takes the explicit
            # voice with it, rather than leaving a dormant True behind.
            if p.voice_explicit and not may_be_explicit(p):
                p.voice_explicit = False
                changed.append("voice_explicit")
        # The bio is member-authored prose, so its ceiling is the tier's
        # character limit — not a column width. It used to share the truncation
        # below, which silently cut a Premium member at the old varchar(500);
        # now that the column is a TextField, `max_length` is None and slicing
        # by it would let anyone write without limit. Refuse instead, naming
        # the cap, the same as ProfileView and MessagesView do.
        if isinstance(data.get("bio"), str):
            cap = over_char_limit(data["bio"], membership_for(request.user).tier)
            if cap:
                return Response(
                    {"detail": f"Your bio is over your {cap:,}-character limit — upgrade in MembershipZ for more room.",
                     "char_limit": cap},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            p.bio = data["bio"]
            changed.append("bio")
        # Truncate to each column's real width — display_name/location/gender
        # are short identifiers, not prose, and overflowing them raises a
        # DataError (500) on PostgreSQL instead of quietly saving.
        # VoiceZ switches. Explicit is the only one with a gate, and the gate
        # is here rather than in the client: a request to be sworn at from an
        # account that is thirteen is refused, and refused OUT LOUD, because
        # silently storing False for something somebody just switched on is
        # how a setting screen starts lying about itself.
        if "voice" in data and isinstance(data["voice"], dict):
            v = data["voice"]
            if "explicit" in v:
                want = bool(v["explicit"])
                if want and not may_be_explicit(p):
                    return Response(
                        {"detail": f"The explicit voice is {EXPLICIT_MIN_AGE}+. Add a birthday that says so in ProfileZ.",
                         "voice_explicit_allowed": False},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                p.voice_explicit = want
                changed.append("voice_explicit")
            for key in ("emoji", "slang"):
                if key in v:
                    setattr(p, f"voice_{key}", bool(v[key]))
                    changed.append(f"voice_{key}")
        for f in ("display_name", "location", "gender"):
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
    (spotify/microsoft/facebook/soundcloud/twitter).

    This is also the only diagnostic for "every button says it isn't available".
    It is deliberately open: the login screen is signed-out, so it cannot need
    auth, and everything here — client IDs, env var NAMES — is public by
    definition. No secret, and no secret's presence, is reported beyond the
    single bit of whether it is set.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        import os

        from django.conf import settings

        from .oauth import provider_status

        # Prefer settings for the three that have named settings entries (which
        # is also what makes them overridable in tests), then fall back to the
        # environment the verifiers themselves read.
        def value(name):
            got = getattr(settings, name, None)
            return os.environ.get(name, "") if got is None else (got or "")

        status_by_provider = provider_status(value)

        cfg = {name: s["client_id"] for name, s in status_by_provider.items()}
        needs = {name: s["missing"] for name, s in status_by_provider.items() if s["missing"]}

        # A configured-but-wrong key is the hardest OAuth failure to diagnose,
        # because Google's button does not error — it just never renders, and
        # every screen stays silent about why. So say it here. Client IDs are
        # public, so naming the shape gives nothing away.
        warnings = []
        g = cfg["google"]
        if g and not g.endswith(".apps.googleusercontent.com"):
            warnings.append(
                "GOOGLE_OAUTH_CLIENT_ID doesn't look like a Google client ID — those "
                "end in .apps.googleusercontent.com. Check you pasted the client ID "
                "and not the client secret."
            )
        if cfg["apple"] and "." not in cfg["apple"]:
            warnings.append(
                "APPLE_OAUTH_CLIENT_ID should be the Services ID (a reverse-domain "
                "string), not the Team ID."
            )
        # Half-configured is a mistake; unconfigured is a choice. Only the first
        # one gets a warning — and it needs one, because the ID being present
        # makes it look done from every side except the one that fails.
        for name, s in sorted(status_by_provider.items()):
            if s["client_id_set"] and s["missing"]:
                warnings.append(
                    f"{name.title()} has a client ID but no {', '.join(s['missing'])}. "
                    f"The button stays hidden rather than sending members to "
                    f"{name.title()} and failing on the way back."
                )
        return Response({**cfg, "warnings": warnings, "needs": needs})
