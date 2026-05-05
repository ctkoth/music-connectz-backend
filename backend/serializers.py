from rest_framework import serializers
from .models import CollabReliabilityRating, CollabReview, Post
# --- Post Serializer ---
class PostSerializer(serializers.ModelSerializer):
    author = serializers.StringRelatedField(read_only=True)

    def validate_content(self, value):
        user = self.context['request'].user if 'request' in self.context else None
        if user and user.is_authenticated:
            from .models import validate_character_limit
            validate_character_limit(user, value)
        return value
    class Meta:
        model = Post
        fields = '__all__'
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

    def validate_text(self, value):
        user = self.context['request'].user if 'request' in self.context else None
        if user and user.is_authenticated:
            from .models import validate_character_limit
            validate_character_limit(user, value)
        return value
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

# --- Royalty & Agreement Dashboard Serializers ---
from .models import Agreement, AgreementSignature, RoyaltySplit, RoyaltyPayment

class AgreementSerializer(serializers.ModelSerializer):
    owner = serializers.StringRelatedField(read_only=True)
    class Meta:
        model = Agreement
        fields = '__all__'

class AgreementSignatureSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    agreement = serializers.StringRelatedField(read_only=True)
    class Meta:
        model = AgreementSignature
        fields = '__all__'

class RoyaltySplitSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    agreement = serializers.StringRelatedField(read_only=True)
    class Meta:
        model = RoyaltySplit
        fields = '__all__'

class RoyaltyPaymentSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    agreement = serializers.StringRelatedField(read_only=True)
    class Meta:
        model = RoyaltyPayment
        fields = '__all__'
# Add these serializers to your serializers.py file

from rest_framework import serializers
from .models import (
    Post, PostRating, PostJoin, OCCLog,
    UserProfile, Skill, Persona, CollabReliabilityRating,
    VideoZ, VideoZTrack, BugZ, BugZComment,
    UserWeeklyPromotion, WeeklyPromotionTemplate
)
from django.contrib.auth.models import User

# --- User Serializers ---
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']

class UserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = UserProfile
        fields = ['id', 'user', 'bio', 'location', 'profile_picture', 'is_teacher', 'is_verified', 'total_earnings', 'created_at', 'updated_at']

# --- Skill Serializers ---
class SkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = ['id', 'name', 'category', 'description', 'base_price', 'created_at', 'updated_at']

# --- Persona Serializers ---
class PersonaSerializer(serializers.ModelSerializer):
    skills = SkillSerializer(many=True, read_only=True)
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = Persona
        fields = ['id', 'user', 'name', 'description', 'skills', 'hourly_rate', 'is_active', 'created_at', 'updated_at']

# --- Rating Serializers ---
class CollabReliabilityRatingSerializer(serializers.ModelSerializer):
    rater = UserSerializer(read_only=True)
    ratee = UserSerializer(read_only=True)
    
    class Meta:
        model = CollabReliabilityRating
        fields = ['id', 'ratee', 'rater', 'score', 'feedback', 'created_at', 'updated_at']

class PostRatingSerializer(serializers.ModelSerializer):
    rater = UserSerializer(read_only=True)
    
    class Meta:
        model = PostRating
        fields = ['id', 'post', 'rater', 'score', 'comment', 'is_helpful', 'helpful_count', 'created_at', 'updated_at']

# --- Post Serializers ---
class PostJoinSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = PostJoin
        fields = ['id', 'post', 'user', 'status', 'created_at', 'updated_at']

class PostSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    ratings = PostRatingSerializer(many=True, read_only=True)
    joins = PostJoinSerializer(many=True, read_only=True)
    
    class Meta:
        model = Post
        fields = ['id', 'title', 'content', 'author', 'post_type', 'visibility', 'ratings', 'joins', 'created_at', 'updated_at']

# --- OCC Log Serializer ---
class OCCLogSerializer(serializers.ModelSerializer):
    editor = UserSerializer(read_only=True)
    post = PostSerializer(read_only=True)
    
    class Meta:
        model = OCCLog
        fields = ['id', 'post', 'editor', 'old_title', 'new_title', 'old_content', 'new_content', 'version', 'change_summary', 'created_at']

# --- VideoZ Serializers ---
class VideoZTrackSerializer(serializers.ModelSerializer):
    class Meta:
        model = VideoZTrack
        fields = ['id', 'videoz', 'track_type', 'name', 'order', 'file', 'start_time', 'duration', 'volume', 'is_visible', 'is_locked', 'created_at', 'updated_at']

class VideoZSerializer(serializers.ModelSerializer):
    owner = UserSerializer(read_only=True)
    tracks = VideoZTrackSerializer(many=True, read_only=True)
    
    class Meta:
        model = VideoZ
        fields = ['id', 'owner', 'title', 'description', 'duration_seconds', 'fps', 'resolution', 'is_published', 'is_public', 'thumbnail', 'video_file', 'total_collaborators', 'view_count', 'tracks', 'created_at', 'updated_at']

# --- BugZ Serializers ---
class BugZCommentSerializer(serializers.ModelSerializer):
    commenter = UserSerializer(read_only=True)
    
    class Meta:
        model = BugZComment
        fields = ['id', 'bug', 'commenter', 'comment', 'is_solution', 'upvote_count', 'created_at', 'updated_at']

class BugZSerializer(serializers.ModelSerializer):
    reporter = UserSerializer(read_only=True)
    assigned_to = UserSerializer(read_only=True)
    comments = BugZCommentSerializer(many=True, read_only=True)
    
    class Meta:
        model = BugZ
        fields = ['id', 'reporter', 'assigned_to', 'title', 'description', 'screenshot', 'reproduction_steps', 'expected_behavior', 'actual_behavior', 'status', 'priority', 'feature_affected', 'browser', 'os', 'app_version', 'upvote_count', 'resolution_notes', 'resolved_at', 'comments', 'created_at', 'updated_at']

# --- Weekly Promotion Serializers ---
class WeeklyPromotionTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = WeeklyPromotionTemplate
        fields = ['id', 'template_key', 'title', 'description', 'target_feature', 'interest_tags_json', 'discount_percent', 'is_active', 'created_at', 'updated_at']

class UserWeeklyPromotionSerializer(serializers.ModelSerializer):
    template = WeeklyPromotionTemplateSerializer(read_only=True)
    
    class Meta:
        model = UserWeeklyPromotion
        fields = ['id', 'user', 'template', 'week_start', 'week_end', 'promo_code', 'discount_percent', 'matched_interest', 'claimed', 'expires_at', 'created_at', 'updated_at']
