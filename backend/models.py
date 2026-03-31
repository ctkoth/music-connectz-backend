from django.db import models
from django.contrib.auth.models import User
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

from django.db import models
from django.contrib.auth.models import User

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
    referred_by = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='referrals')

    def save(self, *args, **kwargs):
        if not self.referral_code:
            self.referral_code = secrets.token_urlsafe(8)[:12]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Profile for {self.user.username}"

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
