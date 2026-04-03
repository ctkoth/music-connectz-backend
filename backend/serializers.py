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


from .models import DistributionAccount, Release, Track, DistributionJob, DistributionEvent, ReleaseRoyaltySplit, ReleaseContributor, ReleaseAnalytics, TrackAnalytics, StreamEvent, ContributorEarnings, PremiumFeature, UserPremiumFeature, PremiumBundle, UserInterest, WeeklyPromotionTemplate, UserWeeklyPromotion


class DistributionAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = DistributionAccount
        fields = (
            'id', 'provider', 'external_account_id', 'status', 'scopes_granted',
            'token_expires_at', 'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')


class TrackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Track
        fields = '__all__'
        read_only_fields = ('id', 'release', 'created_at', 'updated_at')


class ReleaseRoyaltySplitSerializer(serializers.ModelSerializer):
    participant_username = serializers.CharField(source='participant.username', read_only=True)

    class Meta:
        model = ReleaseRoyaltySplit
        fields = (
            'id', 'release', 'participant', 'participant_username', 'percentage',
            'source', 'agreement_split', 'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at', 'source', 'agreement_split')


class ReleaseContributorSerializer(serializers.ModelSerializer):
    participant_username = serializers.CharField(source='participant.username', read_only=True)
    role_display = serializers.CharField(source='get_role_display', read_only=True)

    class Meta:
        model = ReleaseContributor
        fields = (
            'id', 'release', 'participant', 'participant_username', 'role', 'role_display',
            'percentage', 'source', 'agreement_split', 'notes', 'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at', 'source', 'agreement_split')


class ReleaseSerializer(serializers.ModelSerializer):
    tracks = TrackSerializer(many=True, read_only=True)
    royalty_splits = ReleaseRoyaltySplitSerializer(many=True, read_only=True)
    contributors = ReleaseContributorSerializer(many=True, read_only=True)

    class Meta:
        model = Release
        fields = '__all__'
        read_only_fields = (
            'id', 'user', 'provider_release_id', 'validation_errors_json',
            'created_at', 'updated_at', 'tracks', 'royalty_splits', 'contributors',
        )


class DistributionJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = DistributionJob
        fields = '__all__'


class DistributionEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = DistributionEvent
        fields = '__all__'


class ReleaseAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReleaseAnalytics
        fields = (
            'id', 'release', 'total_streams', 'total_revenue', 'revenue_currency',
            'revenue_settled_date', 'unique_listeners', 'total_saves', 'total_skips',
            'earliest_stream_date', 'latest_stream_date', 'platform_breakdown_json',
            'last_updated', 'created_at',
        )
        read_only_fields = ('id', 'last_updated', 'created_at')


class TrackAnalyticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrackAnalytics
        fields = (
            'id', 'track', 'streams', 'revenue', 'unique_listeners', 'saves', 'skips',
            'skip_rate', 'completion_rate', 'average_listen_seconds', 'last_updated', 'created_at',
        )
        read_only_fields = ('id', 'last_updated', 'created_at')


class StreamEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = StreamEvent
        fields = (
            'id', 'track', 'provider', 'event_type', 'event_date', 'count', 'revenue',
            'listener_country', 'listener_device_type', 'raw_payload_json', 'created_at',
        )
        read_only_fields = ('id', 'created_at')


class ContributorEarningsSerializer(serializers.ModelSerializer):
    participant_username = serializers.CharField(source='participant.username', read_only=True)

    class Meta:
        model = ContributorEarnings
        fields = (
            'id', 'contributor', 'release', 'participant', 'participant_username', 'role',
            'royalty_percentage', 'total_revenue', 'participant_share', 'currency',
            'settled_date', 'settled_amount', 'payout_method', 'payout_status',
            'last_updated', 'created_at',
        )
        read_only_fields = (
            'id', 'total_revenue', 'participant_share', 'settled_date', 'settled_amount',
            'last_updated', 'created_at',
        )


class PremiumFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = PremiumFeature
        fields = (
            'feature_key', 'feature_type', 'display_name', 'description',
            'monthly_price', 'yearly_price', 'is_active', 'created_at',
        )
        read_only_fields = ('created_at',)


class UserPremiumFeatureSerializer(serializers.ModelSerializer):
    feature = PremiumFeatureSerializer(read_only=True)
    is_active_now = serializers.SerializerMethodField()

    class Meta:
        model = UserPremiumFeature
        fields = (
            'id', 'user', 'feature', 'status', 'subscription_start', 'subscription_expiry',
            'billing_cycle', 'auto_renew', 'renewal_date', 'paid_amount', 'last_payment_date',
            'is_active_now', 'updated_at', 'created_at',
        )
        read_only_fields = (
            'id', 'user', 'subscription_start', 'stripe_subscription_id', 'stripe_customer_id',
            'last_payment_date', 'updated_at', 'created_at',
        )

    def get_is_active_now(self, obj):
        return obj.is_active_now()


class PremiumBundleSerializer(serializers.ModelSerializer):
    features = PremiumFeatureSerializer(many=True, read_only=True)

    class Meta:
        model = PremiumBundle
        fields = (
            'bundle_key', 'bundle_name', 'description', 'features', 'monthly_price',
            'yearly_price', 'is_active', 'display_order', 'created_at',
        )
        read_only_fields = ('created_at',)


class UserInterestSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserInterest
        fields = ('id', 'user', 'interest', 'weight', 'is_active', 'created_at', 'updated_at')
        read_only_fields = ('id', 'user', 'created_at', 'updated_at')


class WeeklyPromotionTemplateSerializer(serializers.ModelSerializer):
    target_feature_name = serializers.CharField(source='target_feature.display_name', read_only=True)

    class Meta:
        model = WeeklyPromotionTemplate
        fields = (
            'id', 'template_key', 'title', 'description', 'target_feature', 'target_feature_name',
            'interest_tags_json', 'discount_percent', 'is_active', 'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')


class UserWeeklyPromotionSerializer(serializers.ModelSerializer):
    template_title = serializers.CharField(source='template.title', read_only=True)
    template_key = serializers.CharField(source='template.template_key', read_only=True)
    target_feature = serializers.CharField(source='template.target_feature.display_name', read_only=True)

    class Meta:
        model = UserWeeklyPromotion
        fields = (
            'id', 'user', 'template', 'template_title', 'template_key', 'target_feature',
            'week_start', 'week_end', 'promo_code', 'discount_percent', 'matched_interest',
            'claimed', 'expires_at', 'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'user', 'template', 'created_at', 'updated_at')
