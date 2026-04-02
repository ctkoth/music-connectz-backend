from rest_framework import serializers
from .models import CollabReliabilityRating, CollabReview
# --- Reliability Rating Serializer ---
class CollabReliabilityRatingSerializer(serializers.ModelSerializer):
    rater = serializers.StringRelatedField(read_only=True)
    ratee = serializers.StringRelatedField(read_only=True)
    class Meta:
        model = CollabReliabilityRating
        fields = '__all__'

# --- Collab Review Serializer ---
class CollabReviewSerializer(serializers.ModelSerializer):
    reviewer = serializers.StringRelatedField(read_only=True)
    reviewee = serializers.StringRelatedField(read_only=True)
    class Meta:
        model = CollabReview
        fields = '__all__'
from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework.validators import UniqueValidator


from .models import UserProfile, Referral, AgreementTemplate, CollabRoyaltyAgreement, AgreementChangeLog, CollabRoyaltySplit
class AgreementTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgreementTemplate
        fields = '__all__'


class CollabRoyaltyAgreementSerializer(serializers.ModelSerializer):
    class Meta:
        model = CollabRoyaltyAgreement
        fields = '__all__'


class AgreementChangeLogSerializer(serializers.ModelSerializer):
    changed_by = serializers.StringRelatedField()
    class Meta:
        model = AgreementChangeLog
        fields = '__all__'


class CollabRoyaltySplitSerializer(serializers.ModelSerializer):
    participant = serializers.StringRelatedField()
    class Meta:
        model = CollabRoyaltySplit
        fields = '__all__'

class UserProfileSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField()
    class Meta:
        model = UserProfile
        fields = (
            'user', 'referral_code', 'phone_number', 'referred_by',
            'email_verified', 'phone_verified',
            'email_notifications', 'push_notifications', 'phone_notifications', 'marketing_notifications',
        )

class ReferralSerializer(serializers.ModelSerializer):
    referrer = serializers.StringRelatedField()
    referred = serializers.StringRelatedField()
    class Meta:
        model = Referral
        fields = ('referrer', 'referred', 'created_at', 'reward_granted')

class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True, default='')
    username = serializers.CharField(required=False, allow_blank=True, max_length=150, default='')
    phone_number = serializers.CharField(required=False, allow_blank=True, max_length=30, default='')
    password1 = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True, required=True)

    def validate_email(self, value):
        value = (value or '').strip()
        if value and User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("This email is already registered.")
        return value

    def validate_username(self, value):
        value = (value or '').strip()
        if value and User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate_phone_number(self, value):
        value = (value or '').strip()
        if value and UserProfile.objects.filter(phone_number=value).exists():
            raise serializers.ValidationError("This phone number is already registered.")
        return value

    def validate(self, attrs):
        email = (attrs.get('email') or '').strip()
        username = (attrs.get('username') or '').strip()
        phone_number = (attrs.get('phone_number') or '').strip()
        if not email and not username and not phone_number:
            raise serializers.ValidationError({"identifier": "Provide an email, username, or phone number."})
        if attrs['password1'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        import re as _re
        email = (validated_data.get('email') or '').strip()
        username = (validated_data.get('username') or '').strip()
        phone_number = (validated_data.get('phone_number') or '').strip()
        password = validated_data['password1']

        if not username:
            if email:
                base = email.split('@')[0]
            elif phone_number:
                base = 'user' + _re.sub(r'\D', '', phone_number)[-6:]
            else:
                base = 'user'
            candidate = base
            counter = 1
            while User.objects.filter(username__iexact=candidate).exists():
                candidate = f"{base}{counter}"
                counter += 1
            username = candidate

        user = User.objects.create(username=username, email=email or '')
        user.set_password(password)
        user.save()

        if phone_number:
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.phone_number = phone_number
            profile.save(update_fields=['phone_number'])

        return user
