from django.contrib.auth import authenticate, get_user_model
from django.db import transaction
from django.db.models import Q
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Profile

User = get_user_model()


def issue_tokens(user):
    """Return SimpleJWT access/refresh. Frontend stores access as `mcz_access`."""
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


class PublicUserSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(source="profile.phone", read_only=True, default="")
    avatar_url = serializers.CharField(
        source="profile.avatar_url", read_only=True, default=""
    )
    # Owner/staff unlock the debug (god-mode) membership tier in the client.
    is_owner = serializers.SerializerMethodField()
    # Economy + onboarding fields the client reads off /api/auth/me/ (membership
    # tier, wallet balances, onboarding state, and the searchable profile bits).
    tier = serializers.SerializerMethodField()
    spinaz = serializers.SerializerMethodField()
    energy = serializers.SerializerMethodField()
    onboarded = serializers.SerializerMethodField()
    personas = serializers.SerializerMethodField()
    nationalities = serializers.SerializerMethodField()
    birthday = serializers.SerializerMethodField()
    age = serializers.SerializerMethodField()
    zodiac = serializers.SerializerMethodField()
    zodiac_cn = serializers.SerializerMethodField()
    # VoiceZ. `voice_explicit_allowed` is served alongside the switch itself
    # so the client can explain a disabled toggle instead of letting somebody
    # flip it and watch it silently flip back.
    voice = serializers.SerializerMethodField()
    # Linked sign-ins, each carrying whether it can be disconnected and why
    # not. Served here because this is what the account screen already reads,
    # and a member cannot manage a link they cannot see they have.
    connections = serializers.SerializerMethodField()
    # Real name, separate from the handle. This serializer answers /api/auth/me/
    # — the member's OWN view — so both halves are always returned here, and
    # `visibility` says who else may see them. The surfaces that render another
    # member read `public_name()` instead of these.
    #
    # Every field is listed, including the ones left at their default: a member
    # can only check what they are exposing by seeing the whole list, which is
    # the same reason the ZodiacZ panel publishes all twenty-four bonuses.
    visibility = serializers.SerializerMethodField()

    # Nine of the fields below live on the economy profile/wallet/membership. Look
    # each row up ONCE per user and cache it on the serializer — resolving them
    # field-by-field cost ten round-trips to Postgres on every /api/auth/me/,
    # /login/ and /register/ response, which is most of those endpoints' latency.
    def _economy(self, obj, kind):
        cache = self.__dict__.setdefault("_mcz_cache", {})
        key = (kind, obj.pk)
        if key not in cache:
            from apps.economy.models import membership_for, profile_for, wallet_for
            cache[key] = {
                "profile": profile_for,
                "wallet": wallet_for,
                "membership": membership_for,
            }[kind](obj)
        return cache[key]

    def get_birthday(self, obj):
        return self._economy(obj, "profile").birthday or ""

    def get_age(self, obj):
        from apps.economy.models import profile_age
        return profile_age(self._economy(obj, "profile"))

    def get_voice(self, obj):
        from apps.economy.models import may_be_explicit
        p = self._economy(obj, "profile")
        allowed = may_be_explicit(p)
        return {
            # Effective, not stored. Somebody can set this at 18 and then edit
            # their birthday to fifteen; the stored bit would still say True
            # and every screen reading it would swear at a child. The gate is
            # applied on the way OUT as well as on the way in.
            "explicit": bool(p.voice_explicit) and allowed,
            "emoji": bool(p.voice_emoji),
            "slang": bool(p.voice_slang),
            "explicit_allowed": allowed,
        }

    def get_zodiac(self, obj):
        return self._economy(obj, "profile").sign or ""

    def get_zodiac_cn(self, obj):
        """The animal, derived from the birthday rather than stored beside it.

        `sign` is a column and needed a second writer to remember it, which is
        how it got out of step once already. This reads the one source of
        truth, so it cannot drift.
        """
        from apps.economy.models import chinese_zodiac_for
        return chinese_zodiac_for(self._economy(obj, "profile").birthday)

    def get_is_owner(self, obj):
        return bool(obj.is_superuser or obj.is_staff)

    def get_tier(self, obj):
        return self._economy(obj, "membership").tier

    def get_spinaz(self, obj):
        return self._economy(obj, "wallet").spinaz

    def get_energy(self, obj):
        # Settling here is what makes passive Energy real: /api/auth/me/ is hit
        # on every page load, so the balance is current wherever it's shown.
        from apps.economy.models import settle_energy
        return settle_energy(obj).energy

    def get_onboarded(self, obj):
        return self._economy(obj, "profile").onboarded

    def get_personas(self, obj):
        # Through the normalizer, not straight off the column: a row that was
        # written before the write path was fixed still holds a persona as the
        # printed form of a dict, and serving it raw is what put
        # "{'name': 'Independent Artist', ...}" on somebody's own profile.
        from apps.economy.personaz import personas_of
        return personas_of(self._economy(obj, "profile"))

    def get_nationalities(self, obj):
        return self._economy(obj, "profile").nationalities or []

    class Meta:
        model = User
        fields = (
            "id", "username", "email", "phone", "avatar_url", "is_owner",
            "tier", "spinaz", "energy", "onboarded", "personas", "nationalities",
            "birthday", "age", "zodiac", "zodiac_cn", "voice", "connections",
            "first_name", "last_name", "visibility",
        )

    def get_connections(self, obj):
        from .views import connections_for

        return connections_for(obj)

    def get_visibility(self, obj):
        from apps.economy.visibility import settings_for

        return settings_for(self._economy(obj, "profile"))


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    password = serializers.CharField(write_only=True, min_length=8)
    birthday = serializers.CharField(required=False, allow_blank=True, allow_null=True, default="")
    # Inviter's referral code (their username). Credits both sides once on join.
    ref = serializers.CharField(required=False, allow_blank=True, allow_null=True, default="")
    # Token from a no-account trial Boss Take. Signing up with it attaches that
    # take to the new account, so the thing they made at the door isn't lost.
    trial_token = serializers.CharField(required=False, allow_blank=True, allow_null=True, default="")

    def validate(self, attrs):
        username = (attrs.get("username") or "").strip()
        email = (attrs.get("email") or "").strip()
        phone = (attrs.get("phone") or "").strip()

        if not username and not email and not phone:
            raise serializers.ValidationError(
                "Please provide a username, email address, or phone number."
            )

        attrs["username"] = username
        attrs["email"] = email
        attrs["phone"] = phone
        return attrs

    def validate_username(self, value):
        # `username_problem` is the same rule `check-username/` answers with.
        # It was the checker's alone until now, and the checker cannot create
        # an account — so a handle the availability endpoint would have
        # refused was registered anyway, and there was nothing to notice.
        # Empty username is allowed when email is provided.
        if not value or not value.strip():
            return ""
        from .usernames import username_problem
        value = value.strip()
        problem = username_problem(value)
        if problem:
            raise serializers.ValidationError(problem)
        return value

    def validate_password(self, value):
        """Django's own validators — the ones `AUTH_PASSWORD_VALIDATORS` has
        been configured with since the project was started.

        `passwords.py` runs them on a RESET and this never ran them on a
        REGISTER, so the rule was enforced at the weaker moment and not the
        stronger one: you could sign up with the literal string "password",
        and then be refused that same password if you ever tried to change to
        it. Held forever, and the only way to find out it was not allowed was
        to try to stop using it.
        """
        from django.contrib.auth import password_validation
        password_validation.validate_password(value)
        return value

    def validate_email(self, value):
        value = (value or "").strip().lower()
        if value and User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account already uses that email.")
        return value

    def validate_phone(self, value):
        value = (value or "").strip()
        if value and Profile.objects.filter(phone=value).exists():
            raise serializers.ValidationError("An account already uses that phone number.")
        return value

    def create(self, validated):
        # Everything below used to run un-transacted: `create_user` committed
        # immediately, and every step after it (the welcome bonus, the owner's
        # bonus, the zodiac write, the referral, the trial claim) could still
        # raise. When one did, the member got a 500 and NOT an account — but
        # the username and email were already taken, permanently, by a user row
        # with no way back to it. Retrying "register" then failed with "that
        # username/email is taken", by themselves, forever. That is a dead end
        # this screen exists to prevent, not cause. One atomic block: either
        # the whole join happens or none of it does, and a bug in the welcome
        # bonus can never brick a signup.
        with transaction.atomic():
            # Username is required by Django's User model, so use email or phone as
            # fallback when registering without an explicit username.
            username = validated["username"] or validated["email"] or validated["phone"]
            user = User.objects.create_user(
                username=username,
                email=validated["email"],
                password=validated["password"],
            )
            Profile.objects.update_or_create(
                user=user, defaults={"phone": validated.get("phone", "")}
            )
            # Welcome bonus for signing up — kickstart their balance
            from apps.economy.models import award_spinaz, SIGNUP_WELCOME_SPINAZ
            award_spinaz(user, SIGNUP_WELCOME_SPINAZ, "signup welcome bonus",
                         app_key="profilez", target="signup")
            # Platform owner bonus for each new join — incentivizes growth focus
            from apps.economy.views import platform_owner
            owner = platform_owner()
            if owner and owner.id != user.id:
                award_spinaz(owner, SIGNUP_WELCOME_SPINAZ, f"new member join ({user.username})",
                             app_key="profilez", target="signup")
            # Store the birthday on the searchable economy profile if provided.
            birthday = (validated.get("birthday") or "").strip()
            if birthday:
                # Derive the sign here too, exactly as PATCH /api/auth/me/ does —
                # otherwise a member who gave their birthday at signup had a blank
                # ZodiacZ sign until they edited their profile again.
                from apps.economy.models import profile_for, zodiac_for
                ep = profile_for(user)
                ep.birthday = birthday[:10]
                ep.sign = zodiac_for(ep.birthday)
                ep.save(update_fields=["birthday", "sign", "updated_at"])
            # Two-sided referral: credit the inviter + welcome the joinee (once).
            code = (validated.get("ref") or "").strip()
            if code and code.lower() != user.username.lower():
                from apps.economy.models import record_referral
                referrer = User.objects.filter(username__iexact=code).first()
                if referrer:
                    record_referral(referrer, user)
            # Claim the trial take, if they came in through one. Best-effort by
            # design — a stale token must never cost somebody their registration.
            token = (validated.get("trial_token") or "").strip()
            if token:
                from apps.economy.models import claim_trial_take
                claim_trial_take(user, token)
        return user


class LoginSerializer(serializers.Serializer):
    """Accept a single `identifier` that may be username, email, or phone."""

    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        ident = attrs["identifier"].strip()
        password = attrs["password"]

        user_obj = (
            User.objects.filter(
                Q(username__iexact=ident)
                | Q(email__iexact=ident)
                | Q(profile__phone=ident)
            )
            .distinct()
            .first()
        )
        if not user_obj:
            raise serializers.ValidationError("No account matches that login.")

        user = authenticate(username=user_obj.username, password=password)
        if not user:
            raise serializers.ValidationError("Incorrect password.")
        if not user.is_active:
            raise serializers.ValidationError("This account is disabled.")

        attrs["user"] = user
        return attrs
