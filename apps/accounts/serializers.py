from django.contrib.auth import authenticate, get_user_model
from django.db.models import Q
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Profile

User = get_user_model()


def issue_tokens(user):
    """Return SimpleJWT access/refresh. Frontend stores access as `mcz_access`."""
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def revoke_all_refresh_tokens(user):
    """Blacklist every outstanding refresh token for this user.

    Called on password reset. Access tokens are stateless and can't be recalled,
    so an attacker keeps theirs for up to the access lifetime (60 minutes) — but
    they lose the ability to mint new ones, which is what turns a stolen token
    from two weeks of access into one hour.

    Returns the number revoked. Silently does nothing if the blacklist app isn't
    installed, so this can't break a deployment that hasn't migrated yet.
    """
    try:
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken, OutstandingToken)
    except ImportError:                                   # pragma: no cover
        return 0
    revoked = 0
    for token in OutstandingToken.objects.filter(user=user):
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        revoked += 1 if created else 0
    return revoked


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
    genres = serializers.SerializerMethodField()
    nationalities = serializers.SerializerMethodField()
    birthday = serializers.SerializerMethodField()
    age = serializers.SerializerMethodField()
    zodiac = serializers.SerializerMethodField()

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

    def get_zodiac(self, obj):
        return self._economy(obj, "profile").sign or ""

    def get_is_owner(self, obj):
        return bool(obj.is_superuser or obj.is_staff)

    def get_tier(self, obj):
        return self._economy(obj, "membership").tier

    def get_spinaz(self, obj):
        return self._economy(obj, "wallet").spinaz

    def get_energy(self, obj):
        return self._economy(obj, "wallet").energy

    def get_onboarded(self, obj):
        return self._economy(obj, "profile").onboarded

    def get_personas(self, obj):
        return self._economy(obj, "profile").personas or []

    def get_genres(self, obj):
        return self._economy(obj, "profile").genres or []

    def get_nationalities(self, obj):
        return self._economy(obj, "profile").nationalities or []

    class Meta:
        model = User
        fields = (
            "id", "username", "email", "phone", "avatar_url", "is_owner",
            "tier", "spinaz", "energy", "onboarded", "personas", "genres", "nationalities",
            "birthday", "age", "zodiac",
        )


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    password = serializers.CharField(write_only=True, min_length=8)
    birthday = serializers.CharField(required=False, allow_blank=True, allow_null=True, default="")
    # Inviter's referral code (their username). Credits both sides once on join.
    ref = serializers.CharField(required=False, allow_blank=True, allow_null=True, default="")

    def validate_username(self, value):
        value = value.strip()
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("That username is taken.")
        return value

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account already uses that email.")
        return value

    def validate_phone(self, value):
        value = (value or "").strip()
        if value and Profile.objects.filter(phone=value).exists():
            raise serializers.ValidationError("An account already uses that phone number.")
        return value

    def create(self, validated):
        user = User.objects.create_user(
            username=validated["username"],
            email=validated["email"],
            password=validated["password"],
        )
        Profile.objects.update_or_create(
            user=user, defaults={"phone": validated.get("phone", "")}
        )
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
