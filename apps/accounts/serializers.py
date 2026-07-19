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


class PublicUserSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(source="profile.phone", read_only=True, default="")
    avatar_url = serializers.CharField(
        source="profile.avatar_url", read_only=True, default=""
    )
    # Owner/staff unlock the debug (god-mode) membership tier in the client.
    is_owner = serializers.SerializerMethodField()

    def get_is_owner(self, obj):
        return bool(obj.is_superuser or obj.is_staff)

    class Meta:
        model = User
        fields = ("id", "username", "email", "phone", "avatar_url", "is_owner")


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    password = serializers.CharField(write_only=True, min_length=8)

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
