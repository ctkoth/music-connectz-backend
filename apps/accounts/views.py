import logging
import re

from django.contrib.auth import get_user_model
from django.core import signing
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.economy.personaz import clean_persona
from apps.economy.personalityz import clean_code as clean_personality

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
logger = logging.getLogger(__name__)


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


def _note_signup(user, request):
    """Record the signup address and raise a DupeZ flag if it is not the first.

    Swallows everything. A duplicate check is a hint for a human to read later;
    it may never be the reason somebody could not create an account.
    """
    try:
        from apps.economy.dupez import flag_signup
        flag_signup(user, request)
    except Exception:  # noqa: BLE001 — a hint must never break a signup
        logger.exception("dupez: could not flag signup for %s", getattr(user, "id", "?"))


def _note_seen(user, request):
    """Record an address a returning account was seen from. Same guarantee."""
    try:
        from apps.economy.dupez import remember_address
        remember_address(user, request)
    except Exception:  # noqa: BLE001
        logger.exception("dupez: could not record address for %s", getattr(user, "id", "?"))


# A provider hand-off we have verified but not yet acted on.
#
# An OAuth authorization code is single-use: the moment we exchange it, it is
# spent. So a member who is ASKED "do you already have an account?" cannot be
# made to answer by replaying the original request — the second POST carries
# this instead. It is signed by us and short-lived, so it proves we did the
# verification without trusting the client to hand back a uid.
PENDING_SALT = "oauth-pending-choice"
PENDING_MAX_AGE = 15 * 60


def _pending_token(info):
    return signing.dumps(info, salt=PENDING_SALT)


def _read_pending(token):
    try:
        return signing.loads(token, salt=PENDING_SALT, max_age=PENDING_MAX_AGE)
    except signing.SignatureExpired:
        raise OAuthError("That took too long — start the sign-in again.")
    except signing.BadSignature:
        raise OAuthError("That sign-in could not be verified. Start again.")


def disconnect_block(user, remaining):
    """Why this member may not disconnect a sign-in, or "" if they may.

    `remaining` is how many identities they would have LEFT. An OAuth signup
    gets `set_unusable_password()`, so for those members the provider is not a
    convenience on top of a password — it IS the password. Removing the last
    one with nothing behind it locks them out of their own account, and unlike
    a deleted post there is no support path back in: the account is still
    there, and nobody can prove it is theirs.

    So the rule is the one the delete rules already draw. A disconnect may cost
    a convenience; it may never cost the way in. It is refused only in the case
    that actually bites — no password AND nothing else linked — because a
    refusal that fires when a password exists is a control that does not work
    for the people who set one up properly.
    """
    if remaining > 0 or user.has_usable_password():
        return ""
    if user.email:
        return (
            "This is the only way you can sign in — your account has no "
            "password. Set one with Forgot password, then disconnect."
        )
    # No password and no address to send a reset to. Naming it is the whole
    # value: "set a password" is useless advice to somebody who cannot receive
    # the link, and they would find that out by being locked out.
    return (
        "This is the only way you can sign in, and there's no email on the "
        "account to send a password reset to. Add an email first."
    )


def connections_for(user):
    """Every linked sign-in, each carrying whether it can be removed and why.

    The reason rides on the ROW rather than being worked out by the client:
    whether a disconnect is refused depends on the password and on how many
    others are linked, and a screen recomputing that would be the second place
    the rule lives — the one that disagrees after the next change here.
    """
    rows = list(user.oauth_identities.all().order_by("created_at"))
    out = []
    for row in rows:
        why = disconnect_block(user, len(rows) - 1)
        out.append({
            "provider": row.provider,
            "email": row.email,
            "connected_at": row.created_at.isoformat(),
            "can_disconnect": not why,
            "blocked_reason": why,
        })
    return out


def _user_from_oauth(info, with_created=False, create=True):
    """Find-or-create a user from a verified OAuth payload, return (user).

    `with_created` returns `(user, created)` instead, so a caller can tell a
    brand-new account from a returning one — DupeZ needs the difference, and
    every other caller keeps the original single-value shape.

    Matching an existing account by email hands the caller that account, so we
    only do it when the provider actually ASSERTED the address is verified.
    A provider that lets someone set an arbitrary unverified email would
    otherwise be a way to take over any account by claiming its address.

    `create=False` stops at the point where a NEW account would be opened and
    returns `None` instead, so the caller can ask the member whether they
    already have one. That question is only worth asking here — where we could
    not tell — and not on the two paths above it, which know:

      * a known `provider_uid` IS the member, decided by a unique constraint;
      * a verified email match IS the member, and links silently.

    Asking a returning member on every sign-in would be friction on the common
    path and, worse, would train people to click through an identity question
    — which is how a safeguard turns into a duplicate factory.
    """
    identity = OAuthIdentity.objects.filter(
        provider=info["provider"], provider_uid=info["uid"]
    ).first()
    if identity:
        return (identity.user, False) if with_created else identity.user

    made = False
    user = None
    # Only auto-link if the provider VERIFIED the email. For unverified emails,
    # the provider didn't assert ownership, so we ask the member instead of
    # risking a duplicate account. If they say "yes I have one", they authenticate
    # and link it via OAuthLinkView.
    if info.get("email") and info.get("email_verified"):
        match = User.objects.filter(email__iexact=info["email"]).first()
        user = match

    if not user and not create:
        # We genuinely cannot tell. Twitter reaches here EVERY time — its API
        # returns no email at all, so before this there was nothing to match on
        # and a second account was opened for an existing member every single
        # time they used it.
        return (None, False) if with_created else None

    if not user:
        # Opening an account on an address somebody else already holds. The
        # provider did not verify it, so this is an arbitrary string that
        # happens to name a real member — and an `OAuthIdentity` carrying it
        # is a STRONG duplicate signal in `dupez`, which is what lets a member
        # close "their other account" without an owner reviewing it.
        #
        # `accounts_user_email_ci_uniq` already refused this, so the hole was
        # closed — but by an IntegrityError, which reaches the member as a 500
        # and reaches the next reader as nothing at all. Refusing here on
        # purpose is the same protection with a sentence attached, and the
        # sentence is the useful half: the member who legitimately lands on
        # this is one who forgot they had an account, and the answer they need
        # is the other button, not an error page.
        if info.get("email") and User.objects.filter(email__iexact=info["email"]).exists():
            raise OAuthError(
                "An account already uses that email address. Sign in to it and "
                f"link {info['provider'].title()} from there."
            )
        made = True
        base = info.get("name") or (info["email"].split("@")[0] if info.get("email") else info["provider"])
        # Split the provider's name into first/last as a PREFILL. Only here, in
        # the branch that opens a new account — a returning member's own edit
        # must never be overwritten by whatever their Facebook says this week,
        # and this is the one path where there is nothing to overwrite.
        #
        # One split on the first space: "de la Cruz" belongs in a last name
        # whole, and a cleverer parse would be a guess about somebody's name
        # rather than a field they can correct.
        first, _, last = (info.get("name") or "").strip().partition(" ")
        user = User.objects.create_user(
            username=_unique_username(base),
            email=info.get("email", ""),
            first_name=first[:150],
            last_name=last.strip()[:150],
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
    return (user, made) if with_created else user


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        # DupeZ: note where this account was made from, and raise a flag if
        # another account was made from the same place. It flags — it never
        # blocks a signup and never deletes anything, and it is wrapped
        # because a duplicate check must not be able to fail a registration.
        _note_signup(user, request)
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
        _note_seen(user, request)
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
        bits) on the searchable economy profile. Returns the updated user.

        Premium members can also update their username/handle via the `username`
        field. Free members cannot."""
        from apps.economy.catalog import over_char_limit
        from apps.economy.models import (EXPLICIT_MIN_AGE, may_be_explicit,
                                         membership_for, profile_for, zodiac_for)
        p = profile_for(request.user)
        data = request.data or {}
        changed = []

        # Handle username updates (Premium only)
        if "username" in data:
            new_username = data.get("username", "").strip()
            member = membership_for(request.user)

            # Premium-only check
            if member.tier != "premium":
                return Response(
                    {"detail": "Only Premium members can customize their handle. Upgrade in MembershipZ."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Validate format: alphanumeric + underscore, 3-20 chars
            if not re.match(r"^[a-zA-Z0-9_]{3,20}$", new_username):
                return Response(
                    {"detail": "Handle must be 3-20 characters: letters, numbers, and underscores only."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Check availability (case-insensitive)
            if User.objects.filter(username__iexact=new_username).exclude(id=request.user.id).exists():
                return Response(
                    {"detail": f"The handle '{new_username}' is taken. Try another."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            request.user.username = new_username
            request.user.save(update_fields=["username"])
            changed.append("username")
        # A real name, kept separate from the handle. `username` is the address
        # other members type; these are what somebody is called, and a provider
        # supplies them at signup (Facebook through Spotify hands over a legal
        # name). Django's own columns, so no third place to look.
        #
        # They are stored and displayed and NEVER matched on. Matching an
        # account by name would hand it to anyone who typed that name into a
        # provider's display-name field, which nobody verifies — the email rule
        # above, minus the part that makes it safe.
        # Tracked apart from `changed`, which is the Profile's update_fields —
        # putting a User column in there makes Profile.save() raise for a field
        # it has never heard of.
        named = [f for f in ("first_name", "last_name") if f in data]
        for field in named:
            setattr(request.user, field, str(data.get(field) or "").strip()[:150])
        if named:
            request.user.save(update_fields=named)
        if "name_public" in data:
            p.name_public = bool(data["name_public"])
            changed.append("name_public")
        if isinstance(data.get("personas"), list):
            # A persona is {"key", "name", "skills": [{"name", "start"}]} once
            # the member has used the skill picker, or a bare key string from
            # before it existed. Stringifying everything flattened the dict form
            # to "{'key': ...}" and destroyed the skills — and with them the
            # start dates the whole experience metric is derived from.
            p.personas = [_clean_persona(x) for x in data["personas"]][:50]
            changed.append("personas")
        if "personality" in data:
            # The SAME cleaner the other writer uses. A field with two
            # endpoints gets one cleaner — see the note above PROFILE_FIELDS
            # in economy/social.py about what happens when it gets two.
            p.personality = clean_personality(data["personality"])
            changed.append("personality")
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


class UsernameAvailabilityView(APIView):
    """GET /api/auth/check-username/?username=<handle> — check if a username is
    available. Returns {available: bool, reason: str | null}."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        username = request.query_params.get("username", "").strip()

        # Validate format first
        if not re.match(r"^[a-zA-Z0-9_]{3,20}$", username):
            return Response({
                "available": False,
                "reason": "Must be 3-20 characters: letters, numbers, and underscores only.",
            })

        # Check if current user's own username
        if username.lower() == request.user.username.lower():
            return Response({
                "available": False,
                "reason": "This is already your handle.",
            })

        # Check availability
        if User.objects.filter(username__iexact=username).exists():
            return Response({
                "available": False,
                "reason": "This handle is taken.",
            })

        return Response({
            "available": True,
            "reason": None,
        })


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
            # Answering the "do you already have one?" question. The original
            # authorization code was spent on the first exchange, so the answer
            # carries the signed result of that exchange instead of re-running
            # it. Never the client's own idea of who they are.
            if data.get("pending"):
                info = _read_pending(data["pending"])
                if info.get("provider") != provider:
                    raise OAuthError("That sign-in was for a different provider.")
                user, made = _user_from_oauth(info, with_created=True, create=True)
                _note_signup(user, request) if made else _note_seen(user, request)
                return Response({
                    "user": PublicUserSerializer(user).data,
                    **issue_tokens(user),
                })

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
            user, made = _user_from_oauth(info, with_created=True, create=False)
        except OAuthError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if user is None:
            # A new identity we could not tie to anybody. Ask rather than
            # assume — but never refuse: a member whose only sign-in is a
            # provider that hands over no email has to be able to join, or the
            # safeguard becomes a limit that says WHETHER.
            #
            # 200, not an error: nothing went wrong, we just have a question.
            return Response({
                "needs_choice": True,
                "provider": provider,
                "email": info.get("email", ""),
                "suggested_username": _unique_username(
                    info.get("name")
                    or (info["email"].split("@")[0] if info.get("email") else provider)
                ),
                "pending": _pending_token(info),
                "detail": "Do you already have a Music ConnectZ account?",
            })

        # Signing in with a different provider is how most duplicates on this
        # platform get made, so an account created HERE is the one worth
        # noticing — the same call, gated on whether the account is new.
        _note_signup(user, request) if made else _note_seen(user, request)
        tokens = issue_tokens(user)
        return Response({"user": PublicUserSerializer(user).data, **tokens})


class OAuthLinkView(APIView):
    """POST /api/auth/oauth/<provider>/link/ — link an OAuth provider to the
    current user's account. For authenticated users only. Requires the user to
    already have an account before linking.

    Supports two flows:
    1. Fresh OAuth verification: provide code/credential (same as direct linking)
    2. Pending token: provide a pending token from an earlier OAuth attempt
       (used when user logs in first, then links OAuth after authentication)
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, provider):
        data = request.data or {}
        try:
            # Linking after a login: the member answered "I already have one",
            # signed in, and is now spending the signed result of the exchange
            # that already happened. Same key as the register path above — the
            # authorization code was spent on that first exchange and cannot be
            # replayed, so a pending token is the only thing left to present.
            if data.get("pending"):
                info = _read_pending(data["pending"])
                if info.get("provider") != provider:
                    raise OAuthError("That sign-in was for a different provider.")
            else:
                # Fresh OAuth verification (traditional flow)
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

            # Check if this OAuth identity is already linked to another account
            existing_identity = OAuthIdentity.objects.filter(
                provider=info["provider"], provider_uid=info["uid"]
            ).first()

            if existing_identity:
                if existing_identity.user_id == request.user.id:
                    # Already linked to this account
                    return Response(
                        {"detail": f"{provider.title()} is already linked to your account."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                else:
                    # Linked to a different account
                    return Response(
                        {
                            "detail": f"This {provider.title()} account is already linked to another user. "
                            "Please use a different account or contact support."
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            # Link this OAuth identity to the current user
            OAuthIdentity.objects.create(
                user=request.user,
                provider=info["provider"],
                provider_uid=info["uid"],
                email=info.get("email", ""),
            )

            return Response(
                {
                    "detail": f"{provider.title()} successfully linked to your account.",
                    "user": PublicUserSerializer(request.user).data,
                }
            )

        except OAuthError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, provider):
        """Disconnect a linked sign-in.

        Linking existed from the start and unlinking never did, so a provider
        attached to the wrong account could only be moved by someone with a
        database shell. That is not an edge case: `_user_from_oauth` matches a
        known `provider_uid` BEFORE anything else and signs you into whichever
        account holds it, so a member whose SoundCloud landed on the wrong
        account gets returned to it every single time, with no screen anywhere
        offering a way out.

        It takes the provider from the URL rather than a uid in the body: the
        member is removing THEIR link to a provider, and a uid in a body is a
        chance to name somebody else's.
        """
        identity = request.user.oauth_identities.filter(provider=provider).first()
        if not identity:
            return Response(
                {"detail": f"No {provider.title()} sign-in is linked to your account."},
                status=status.HTTP_404_NOT_FOUND,
            )

        remaining = request.user.oauth_identities.exclude(pk=identity.pk).count()
        blocked = disconnect_block(request.user, remaining)
        if blocked:
            return Response({"detail": blocked}, status=status.HTTP_400_BAD_REQUEST)

        identity.delete()
        return Response(
            {
                "detail": f"{provider.title()} disconnected. You can link it again any time.",
                "user": PublicUserSerializer(request.user).data,
            }
        )


class OAuthConfigView(APIView):
    """GET /api/auth/oauth-config/ — the PUBLIC OAuth client IDs the backend is
    configured with, so the login buttons can read them at runtime instead of
    relying on build-time VITE_* vars. Client IDs are public; secrets stay here.
    Covers every provider the backend can complete a sign-in for — the id_token
    verifiers (google), GitHub, and the generic code-flow providers
    (spotify/microsoft/facebook/soundcloud/twitter).
    Note: Apple OAuth is temporarily disabled; verify_apple() is retained for re-enabling.

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
        g = cfg.get("google", "")
        if g and not g.endswith(".apps.googleusercontent.com"):
            warnings.append(
                "GOOGLE_OAUTH_CLIENT_ID doesn't look like a Google client ID — those "
                "end in .apps.googleusercontent.com. Check you pasted the client ID "
                "and not the client secret."
            )
        # Apple is temporarily disabled; skip the Services ID validation
        if cfg.get("apple") and "." not in cfg.get("apple", ""):
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


class UsersView(APIView):
    """DELETE /api/auth/users/{username}/ — owner can delete any account."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, username):
        from apps.economy.dupez import is_owner_candidate, is_owner

        # Check if caller is an owner
        if not (is_owner(request.user) or is_owner_candidate(request.user)):
            return Response({"detail": "owner only"}, status=status.HTTP_403_FORBIDDEN)

        # Get the target user
        target = User.objects.filter(username=username).first()
        if not target:
            return Response({"detail": "user not found"}, status=status.HTTP_404_NOT_FOUND)

        # Delete the user
        target.delete()
        return Response({"deleted": username}, status=status.HTTP_200_OK)
