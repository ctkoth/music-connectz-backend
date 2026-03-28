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
        fields = ('user', 'referral_code', 'referred_by')

class ReferralSerializer(serializers.ModelSerializer):
    referrer = serializers.StringRelatedField()
    referred = serializers.StringRelatedField()
    class Meta:
        model = Referral
        fields = ('referrer', 'referred', 'created_at', 'reward_granted')

class RegisterSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(
        required=True,
        validators=[UniqueValidator(queryset=User.objects.all())]
    )
    password1 = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')

    def validate(self, attrs):
        if attrs['password1'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        user = User.objects.create(
            username=validated_data['username'],
            email=validated_data['email']
        )
        user.set_password(validated_data['password1'])
        user.save()
        return user
