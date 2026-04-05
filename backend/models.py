# --- ParcelPrimate Campaign Model (Mailchimp Knockoff) ---
class ParcelPrimateCampaign(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('sending', 'Sending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    ]
    subject = models.CharField(max_length=255)
    content_html = models.TextField()
    content_text = models.TextField(blank=True)
    audience_filter = models.CharField(max_length=255, blank=True, help_text='Query or tag for audience selection')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='draft')
    scheduled_time = models.DateTimeField(null=True, blank=True)
    sent_time = models.DateTimeField(null=True, blank=True)
    total_sent = models.PositiveIntegerField(default=0)
    total_opens = models.PositiveIntegerField(default=0)
    total_clicks = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='parcelprimate_campaigns')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"ParcelPrimate: {self.subject} ({self.status})"
# --- Messaging Model for Pro WhatsApp-Style Chat ---
from django.utils import timezone
from datetime import timedelta

class ChatThread(models.Model):
    participants = models.ManyToManyField(User, related_name='chat_threads')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Thread: {', '.join([u.username for u in self.participants.all()])}"


# --- Chat Message with Unlimited Edits and Edit Log ---
class ChatMessage(models.Model):
    thread = models.ForeignKey(ChatThread, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    content = models.TextField(blank=True)
    attachment = models.FileField(upload_to='chat_attachments/', blank=True, null=True)
    message_type = models.CharField(max_length=16, default='text', choices=[
        ('text', 'Text'),
        ('image', 'Image'),
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('file', 'File'),
        ('call', 'Call'),
    ])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_edited_at = models.DateTimeField(null=True, blank=True)

    def log_edit(self, old_content, editor):
        ChatMessageEditLog.objects.create(
            message=self,
            old_content=old_content,
            edited_by=editor,
        )

    def get_edit_history(self):
        return self.edit_logs.order_by('edited_at')

    def __str__(self):
        return f"Msg from {self.sender.username} in Thread {self.thread.id}"

# --- Edit Log for Chat Messages ---
class ChatMessageEditLog(models.Model):
    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name='edit_logs')
    old_content = models.TextField()
    edited_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='edited_messages')
    edited_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Edit by {self.edited_by.username} at {self.edited_at} for Msg {self.message.id}"
# --- Imports ---
from django.db import models
from django.contrib.auth.models import User
# --- Payment Log for Auditing ---
class PaymentLog(models.Model):
    PROVIDER_CHOICES = [
        ('paypal', 'PayPal'),
        ('stripe', 'Stripe'),
        ('other', 'Other'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_logs')
    provider = models.CharField(max_length=16, choices=PROVIDER_CHOICES)
    order_id = models.CharField(max_length=128)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=8, default='USD')
    status = models.CharField(max_length=32)
    raw_data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.provider} {self.order_id} {self.user.username} {self.amount} {self.status}"
# --- Unified Post Model for v9.8 Paradigm ---
class Post(models.Model):
    POST_TYPE_CHOICES = [
        ('work', 'Work'),
        ('testimonial', 'Testimonial'),
        ('discussion', 'Discussion'),
        ('announcement', 'Announcement'),
        ('other', 'Other'),
    ]
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='posts')
    post_type = models.CharField(max_length=24, choices=POST_TYPE_CHOICES, default='other')
    title = models.CharField(max_length=200, blank=True)
    content = models.TextField(blank=True)
    work = models.ForeignKey('Work', null=True, blank=True, on_delete=models.SET_NULL, related_name='as_post')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_pinned = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    is_public = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.get_post_type_display()} by {self.author.username}: {self.title or self.content[:30]}"

# --- Comment Model for Posts ---
class PostComment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='post_comments')
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Comment by {self.author.username} on Post {self.post.id}"

# --- Rating Model for Posts and Comments ---
class PostRating(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='ratings')
    rater = models.ForeignKey(User, on_delete=models.CASCADE, related_name='post_ratings')
    value = models.PositiveSmallIntegerField(default=0)  # 0-10 scale
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('post', 'rater')

    def __str__(self):
        return f"Rating {self.value}/10 by {self.rater.username} on Post {self.post.id}"

class CommentRating(models.Model):
    comment = models.ForeignKey(PostComment, on_delete=models.CASCADE, related_name='ratings')
    rater = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comment_ratings')
    value = models.PositiveSmallIntegerField(default=0)  # 0-10 scale
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('comment', 'rater')

    def __str__(self):
        return f"Rating {self.value}/10 by {self.rater.username} on Comment {self.comment.id}"



# --- Editable Reviews by Collaborators, Shareable as Posts ---
class CollabReview(models.Model):
    agreement = models.ForeignKey('CollabRoyaltyAgreement', on_delete=models.CASCADE, related_name='reviews')
    reviewer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='given_collab_reviews')
    reviewee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_collab_reviews')
    text = models.TextField(blank=True)
    is_shared = models.BooleanField(default=False)  # If true, show on reviewee's public profile
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('agreement', 'reviewer', 'reviewee')

    def __str__(self):
        return f"Review by {self.reviewer.username} for {self.reviewee.username} (Collab {self.agreement.id})"



class AgreementTemplate(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    template_text = models.TextField()
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Template: {self.name}"


class CollabRoyaltyAgreement(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_royalty_agreements')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    agreement_text = models.TextField(default="This agreement outlines the royalty splits for this collaboration.")
    is_finalized = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    previous_version = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='next_versions')
    template = models.ForeignKey(AgreementTemplate, null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return f"Royalty Agreement: {self.title} v{self.version} (Finalized: {self.is_finalized})"


class AgreementChangeLog(models.Model):
    agreement = models.ForeignKey(CollabRoyaltyAgreement, on_delete=models.CASCADE, related_name='change_logs')
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    change_time = models.DateTimeField(auto_now_add=True)
    change_summary = models.TextField()
    old_text = models.TextField()
    new_text = models.TextField()

    def __str__(self):
        return f"Change by {self.changed_by} at {self.change_time}"


class CollabRoyaltySplit(models.Model):
    agreement = models.ForeignKey(CollabRoyaltyAgreement, on_delete=models.CASCADE, related_name='splits')
    participant = models.ForeignKey(User, on_delete=models.CASCADE)
    percentage = models.DecimalField(max_digits=5, decimal_places=2)
    accepted = models.BooleanField(default=False)
    accepted_at = models.DateTimeField(null=True, blank=True)
    e_signature = models.CharField(max_length=256, blank=True, null=True)  # digital acknowledgment (hash or text)

    def __str__(self):
        return f"{self.participant.username}: {self.percentage}% ({'Accepted' if self.accepted else 'Pending'})"

# --- Reliability Rating: Editable by collaborators after collab begins ---
class CollabReliabilityRating(models.Model):
    agreement = models.ForeignKey(CollabRoyaltyAgreement, on_delete=models.CASCADE, related_name='reliability_ratings')
    rater = models.ForeignKey(User, on_delete=models.CASCADE, related_name='given_reliability_ratings')
    ratee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_reliability_ratings')
    score = models.PositiveSmallIntegerField(default=0)  # 0-10 scale
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('agreement', 'rater', 'ratee')

    def __str__(self):
        return f"Reliability {self.score}/10: {self.rater.username}  {self.ratee.username} (Collab {self.agreement.id})"

import secrets
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    referral_code = models.CharField(max_length=16, unique=True, blank=True)
    phone_number = models.CharField(max_length=32, blank=True, default='')
    email_verified = models.BooleanField(default=False)
    phone_verified = models.BooleanField(default=False)
    email_verification_code = models.CharField(max_length=8, blank=True, default='')
    phone_verification_code = models.CharField(max_length=8, blank=True, default='')
    email_verification_expires = models.DateTimeField(null=True, blank=True)
    phone_verification_expires = models.DateTimeField(null=True, blank=True)
    email_notifications = models.BooleanField(default=True)
    push_notifications = models.BooleanField(default=True)
    phone_notifications = models.BooleanField(default=False)
    marketing_notifications = models.BooleanField(default=False)
    referred_by = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='referrals')
    location = models.CharField(max_length=128, blank=True, default='')
    first_name = models.CharField(max_length=64, blank=True, default='')
    last_name = models.CharField(max_length=64, blank=True, default='')
    gender = models.CharField(max_length=32, blank=True, default='')
    birthday = models.DateField(null=True, blank=True)
	avatar_url = models.URLField(max_length=512, blank=True, default='')

    # DJ points system: Spina
    spina = models.PositiveIntegerField(default=0, help_text='DJ points (Spina) earned by the user')

    def save(self, *args, **kwargs):
        if not self.referral_code:
            self.referral_code = secrets.token_urlsafe(8)[:12]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Profile for {self.user.username}"


class AuthAuditLog(models.Model):
    EVENT_CHOICES = [
        ('register', 'Register'),
        ('login', 'Login'),
        ('oauth_profile_complete', 'OAuth Profile Complete'),
        ('oauth_account_connect', 'OAuth Account Connect'),
    ]
    OUTCOME_CHOICES = [
        ('success', 'Success'),
        ('failure', 'Failure'),
    ]

    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='auth_audit_logs')
    event = models.CharField(max_length=32, choices=EVENT_CHOICES)
    outcome = models.CharField(max_length=16, choices=OUTCOME_CHOICES)
    provider = models.CharField(max_length=32, blank=True, default='')
    identifier = models.CharField(max_length=255, blank=True, default='')
    ip_address = models.CharField(max_length=64, blank=True, default='')
    user_agent = models.CharField(max_length=512, blank=True, default='')
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        label = self.identifier or (self.user.username if self.user else 'unknown')
        return f"{self.event}:{self.outcome} for {label}"

class Referral(models.Model):
    referrer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_referrals')
    referred = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_referral')
    created_at = models.DateTimeField(auto_now_add=True)
    reward_granted = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.referrer.username} referred {self.referred.username}"

class Skill(models.Model):
    name = models.CharField(max_length=100)
    def __str__(self):
        return self.name

class Persona(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    skills = models.ManyToManyField(Skill, blank=True)
    def __str__(self):
        return f"{self.name} ({self.user.username})"

class Work(models.Model):
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to='uploads/')
    date_created = models.DateField()
    date_uploaded = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE)
    price = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    genre = models.CharField(max_length=100, blank=True)
    thumbnail = models.ImageField(upload_to='thumbnails/', blank=True, null=True)
    skills = models.ManyToManyField(Skill, blank=True)

    def __str__(self):
        return self.title


class SiteAnalytics(models.Model):
    key = models.CharField(max_length=32, unique=True, default='global')
    total_visits = models.PositiveIntegerField(default=0)
    unique_visitors = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.key}: {self.total_visits} visits"


class VisitorRecord(models.Model):
    visitor_key = models.CharField(max_length=128, unique=True)
    visit_count = models.PositiveIntegerField(default=1)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.visitor_key


class DistributionProvider(models.TextChoices):
    DITTO = 'ditto', 'Ditto'
    GENERIC = 'generic_partner', 'Generic Partner'


class DistributionAccount(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('pending', 'Pending'),
        ('disconnected', 'Disconnected'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='distribution_accounts')
    provider = models.CharField(max_length=32, choices=DistributionProvider.choices)
    external_account_id = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='pending')
    scopes_granted = models.CharField(max_length=512, blank=True, default='')
    access_token_encrypted = models.TextField(blank=True, default='')
    refresh_token_encrypted = models.TextField(blank=True, default='')
    token_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = ('user', 'provider', 'external_account_id')

    def __str__(self):
        return f"{self.user.username} {self.provider} ({self.status})"


class Release(models.Model):
    RELEASE_TYPE_CHOICES = [
        ('single', 'Single'),
        ('ep', 'EP'),
        ('album', 'Album'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('processing', 'Processing'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='releases')
    title = models.CharField(max_length=255)
    version_title = models.CharField(max_length=255, blank=True, default='')
    primary_artist = models.CharField(max_length=255)
    release_type = models.CharField(max_length=16, choices=RELEASE_TYPE_CHOICES, default='single')
    genre = models.CharField(max_length=128, blank=True, default='')
    language = models.CharField(max_length=32, blank=True, default='en')
    explicit = models.BooleanField(default=False)
    upc = models.CharField(max_length=32, blank=True, default='')
    planned_release_date = models.DateField(null=True, blank=True)
    original_release_date = models.DateField(null=True, blank=True)
    cover_art_file = models.FileField(upload_to='distribution/covers/', null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='draft')
    provider = models.CharField(max_length=32, blank=True, default='')
    provider_release_id = models.CharField(max_length=255, blank=True, default='')
    collab_agreement = models.ForeignKey('CollabRoyaltyAgreement', null=True, blank=True, on_delete=models.SET_NULL, related_name='distribution_releases')
    auto_apply_collab_royalties = models.BooleanField(default=True)
    premium_required = models.BooleanField(default=True)
    validation_errors_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.title} ({self.user.username})"


class Track(models.Model):
    release = models.ForeignKey(Release, on_delete=models.CASCADE, related_name='tracks')
    sequence_number = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=255)
    featured_artists = models.CharField(max_length=255, blank=True, default='')
    isrc = models.CharField(max_length=32, blank=True, default='')
    audio_file = models.FileField(upload_to='distribution/audio/', null=True, blank=True)
    explicit = models.BooleanField(default=False)
    duration_seconds = models.PositiveIntegerField(default=0)
    composer_writers_json = models.JSONField(default=list, blank=True)
    publisher_info_json = models.JSONField(default=dict, blank=True)
    lyrics_text = models.TextField(blank=True, default='')
    language = models.CharField(max_length=32, blank=True, default='en')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sequence_number', 'id']

    def __str__(self):
        return f"{self.release.title} - {self.sequence_number}. {self.title}"


class ReleaseRoyaltySplit(models.Model):
    SOURCE_CHOICES = [
        ('agreement', 'Agreement'),
        ('manual', 'Manual'),
    ]

    release = models.ForeignKey(Release, on_delete=models.CASCADE, related_name='royalty_splits')
    participant = models.ForeignKey(User, on_delete=models.CASCADE, related_name='release_royalty_splits')
    percentage = models.DecimalField(max_digits=5, decimal_places=2)
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default='agreement')
    agreement_split = models.ForeignKey('CollabRoyaltySplit', null=True, blank=True, on_delete=models.SET_NULL, related_name='release_snapshots')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('release', 'participant')
        ordering = ['-percentage', 'participant_id']

    def __str__(self):
        return f"{self.release_id}: {self.participant.username} {self.percentage}%"


class ReleaseContributor(models.Model):
    ROLE_CHOICES = [
        ('writer', 'Writer'),
        ('performer', 'Performer'),
        ('mix_engineer', 'Mix Engineer'),
        ('producer', 'Producer'),
        ('visual_designer', 'Visual Designer (Cover)'),
        ('business_manager', 'Business Manager'),
        ('other', 'Other'),
    ]
    SOURCE_CHOICES = [
        ('agreement', 'Agreement'),
        ('manual', 'Manual'),
    ]

    release = models.ForeignKey(Release, on_delete=models.CASCADE, related_name='contributors')
    participant = models.ForeignKey(User, on_delete=models.CASCADE, related_name='release_contributions')
    role = models.CharField(max_length=32, choices=ROLE_CHOICES)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, help_text='Royalty percentage for this role')
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default='manual')
    agreement_split = models.ForeignKey('CollabRoyaltySplit', null=True, blank=True, on_delete=models.SET_NULL, related_name='release_contributor_snapshots')
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['role', '-percentage', 'participant_id']
        indexes = [
            models.Index(fields=['release', 'role']),
            models.Index(fields=['participant', 'role']),
        ]

    def __str__(self):
        return f"{self.release_id}: {self.participant.username} ({self.get_role_display()}) {self.percentage}%"


class PremiumFeature(models.Model):
    FEATURE_TYPES = [
        ('distribution', 'Music Distribution'),
        ('unlimited_contributors', 'Unlimited Contributors'),
        ('advanced_analytics', 'Advanced Analytics'),
        ('pending_edits', 'Pending Release Edits'),
        ('lyrics_management', 'Lyrics Management'),
        ('priority_support', 'Priority Support'),
        ('api_access', 'API Access'),
        ('white_label', 'White Label Branding'),
        ('pro_settle_fast', 'Fast Settlement (48h)'),
        ('master_analytics', 'Master/Catalog Analytics'),
    ]

    feature_key = models.CharField(max_length=32, unique=True, primary_key=True)
    feature_type = models.CharField(max_length=32, choices=FEATURE_TYPES)
    display_name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    monthly_price = models.DecimalField(max_digits=6, decimal_places=2)
    yearly_price = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['monthly_price', 'feature_key']

    def __str__(self):
        return f"{self.display_name} (${self.monthly_price}/mo)"


class UserPremiumFeature(models.Model):
    SUBSCRIPTION_STATUS_CHOICES = [
        ('active', 'Active'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
        ('paused', 'Paused'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='premium_features')
    feature = models.ForeignKey(PremiumFeature, on_delete=models.CASCADE, related_name='subscriptions')
    status = models.CharField(max_length=16, choices=SUBSCRIPTION_STATUS_CHOICES, default='active')
    subscription_start = models.DateTimeField(auto_now_add=True)
    subscription_expiry = models.DateTimeField(null=True, blank=True)
    billing_cycle = models.CharField(max_length=16, choices=[('monthly', 'Monthly'), ('yearly', 'Yearly')], default='monthly')
    stripe_subscription_id = models.CharField(max_length=255, blank=True, default='')
    stripe_customer_id = models.CharField(max_length=255, blank=True, default='')
    auto_renew = models.BooleanField(default=True)
    renewal_date = models.DateField(null=True, blank=True)
    paid_amount = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    last_payment_date = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'feature')
        ordering = ['-subscription_start']

    def is_active_now(self):
        from django.utils import timezone
        if self.status != 'active':
            return False
        if self.subscription_expiry and self.subscription_expiry < timezone.now():
            return False
        return True

    def __str__(self):
        return f"{self.user.username} -> {self.feature.display_name} ({self.status})"


class PremiumBundle(models.Model):
    bundle_key = models.CharField(max_length=32, unique=True, primary_key=True)
    bundle_name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    features = models.ManyToManyField(PremiumFeature, related_name='bundles')
    monthly_price = models.DecimalField(max_digits=6, decimal_places=2)
    yearly_price = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_order', 'monthly_price']

    def __str__(self):
        return f"{self.bundle_name} (${self.monthly_price}/mo)"


class DistributionJob(models.Model):
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('sent', 'Sent'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
    ]

    release = models.ForeignKey(Release, on_delete=models.CASCADE, related_name='distribution_jobs')
    provider = models.CharField(max_length=32)
    operation = models.CharField(max_length=32)
    request_payload_json = models.JSONField(default=dict, blank=True)
    response_payload_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='queued')
    error_code = models.CharField(max_length=64, blank=True, default='')
    error_message = models.TextField(blank=True, default='')
    retry_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.operation} {self.provider} ({self.status})"


class DistributionEvent(models.Model):
    release = models.ForeignKey(Release, on_delete=models.CASCADE, related_name='distribution_events')
    provider = models.CharField(max_length=32)
    event_type = models.CharField(max_length=64)
    event_time = models.DateTimeField()
    payload_json = models.JSONField(default=dict, blank=True)
    signature_valid = models.BooleanField(default=False)
    processed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-event_time', '-id']

    def __str__(self):
        return f"{self.provider} {self.event_type} ({self.release_id})"


class ReleaseAnalytics(models.Model):
    PLATFORM_CHOICES = [
        ('spotify', 'Spotify'),
        ('apple_music', 'Apple Music'),
        ('youtube_music', 'YouTube Music'),
        ('amazon_music', 'Amazon Music'),
        ('tidal', 'Tidal'),
        ('deezer', 'Deezer'),
        ('bandcamp', 'Bandcamp'),
        ('other', 'Other'),
    ]

    release = models.OneToOneField(Release, on_delete=models.CASCADE, related_name='analytics')
    total_streams = models.BigIntegerField(default=0)
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    revenue_currency = models.CharField(max_length=3, default='USD')
    revenue_settled_date = models.DateField(null=True, blank=True)
    unique_listeners = models.IntegerField(default=0)
    total_saves = models.IntegerField(default=0)
    total_skips = models.IntegerField(default=0)
    earliest_stream_date = models.DateTimeField(null=True, blank=True)
    latest_stream_date = models.DateTimeField(null=True, blank=True)
    platform_breakdown_json = models.JSONField(default=dict, blank=True)
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Release Analytics'

    def __str__(self):
        return f"Analytics: {self.release.title} ({self.total_streams} streams)"


class TrackAnalytics(models.Model):
    track = models.OneToOneField(Track, on_delete=models.CASCADE, related_name='analytics')
    streams = models.BigIntegerField(default=0)
    revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unique_listeners = models.IntegerField(default=0)
    saves = models.IntegerField(default=0)
    skips = models.IntegerField(default=0)
    skip_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text='Skip rate %')
    completion_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text='Completion rate %')
    average_listen_seconds = models.IntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Track Analytics'

    def __str__(self):
        return f"Analytics: {self.track.title} ({self.streams} streams)"


class StreamEvent(models.Model):
    EVENT_TYPE_CHOICES = [
        ('stream', 'Stream'),
        ('preview', 'Preview'),
        ('sale', 'Sale'),
        ('skip', 'Skip'),
        ('save', 'Save'),
        ('share', 'Share'),
    ]

    track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name='stream_events')
    provider = models.CharField(max_length=32)
    event_type = models.CharField(max_length=16, choices=EVENT_TYPE_CHOICES)
    event_date = models.DateField()
    count = models.IntegerField(default=1)
    revenue = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    listener_country = models.CharField(max_length=2, blank=True, default='')
    listener_device_type = models.CharField(max_length=32, blank=True, default='')
    raw_payload_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-event_date', '-id']
        indexes = [
            models.Index(fields=['track', 'event_date']),
            models.Index(fields=['provider', 'event_type', 'event_date']),
        ]

    def __str__(self):
        return f"{self.provider} {self.event_type} on {self.event_date}: {self.track.title}"


class ContributorEarnings(models.Model):
    contributor = models.ForeignKey(ReleaseContributor, on_delete=models.CASCADE, related_name='earnings')
    release = models.ForeignKey(Release, on_delete=models.CASCADE, related_name='contributor_earnings')
    participant = models.ForeignKey(User, on_delete=models.CASCADE, related_name='distribution_earnings')
    role = models.CharField(max_length=32)
    royalty_percentage = models.DecimalField(max_digits=5, decimal_places=2)
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    participant_share = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text='Calculated: total_revenue * royalty_percentage / 100')
    currency = models.CharField(max_length=3, default='USD')
    settled_date = models.DateField(null=True, blank=True)
    settled_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    payout_method = models.CharField(max_length=32, blank=True, default='')
    payout_status = models.CharField(max_length=32, default='pending', choices=[
        ('pending', 'Pending Settlement'),
        ('processing', 'Processing'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
    ])
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('contributor', 'release')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.participant.username} ({self.role}): {self.participant_share} {self.currency}"


class UserInterest(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='interests')
    interest = models.CharField(max_length=64)
    weight = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'interest')
        ordering = ['-weight', 'interest']

    def __str__(self):
        return f"{self.user.username}: {self.interest} ({self.weight})"


class WeeklyPromotionTemplate(models.Model):
    template_key = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    target_feature = models.ForeignKey(PremiumFeature, null=True, blank=True, on_delete=models.SET_NULL, related_name='promotion_templates')
    interest_tags_json = models.JSONField(default=list, blank=True)
    discount_percent = models.PositiveSmallIntegerField(default=10)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-discount_percent', 'template_key']

    def __str__(self):
        return f"{self.template_key}: {self.discount_percent}%"


class UserWeeklyPromotion(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='weekly_promotions')
    template = models.ForeignKey(WeeklyPromotionTemplate, on_delete=models.CASCADE, related_name='user_promotions')
    week_start = models.DateField()
    week_end = models.DateField()
    promo_code = models.CharField(max_length=40)
    discount_percent = models.PositiveSmallIntegerField(default=10)
    matched_interest = models.CharField(max_length=64, blank=True, default='')
    claimed = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'template', 'week_start')
        ordering = ['-week_start', '-created_at']

    def __str__(self):
        return f"{self.user.username} {self.promo_code} ({self.discount_percent}%)"
