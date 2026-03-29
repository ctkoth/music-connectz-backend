
from django.db import models
from django.contrib.auth.models import User

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
from django.db import models

from django.contrib.auth.models import User
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
from django.db import models
