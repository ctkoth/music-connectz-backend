"""
Profile extends the default Django User without swapping AUTH_USER_MODEL
(swapping mid-project is risky). Phone lives here; username/email/password
stay on User. OAuth links are stored so a Google/GitHub/Apple login maps back
to the same account on return visits.
"""
from django.conf import settings
from django.db import models


class Profile(models.Model):
    PROVIDER_PASSWORD = "password"
    PROVIDER_GOOGLE = "google"
    PROVIDER_GITHUB = "github"
    PROVIDER_APPLE = "apple"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    phone = models.CharField(max_length=32, blank=True, default="", db_index=True)
    avatar_url = models.URLField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Profile<{self.user}>"


class OAuthIdentity(models.Model):
    """A verified third-party identity linked to a user."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="oauth_identities",
    )
    provider = models.CharField(max_length=20)
    provider_uid = models.CharField(max_length=191)
    email = models.EmailField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("provider", "provider_uid")
        verbose_name_plural = "OAuth identities"

    def __str__(self):
        return f"{self.provider}:{self.provider_uid}"


class OTPVerification(models.Model):
    """Temporary OTP codes for email/phone verification during registration."""

    CHANNEL_EMAIL = "email"
    CHANNEL_PHONE = "phone"
    CHANNEL_CHOICES = [
        (CHANNEL_EMAIL, "Email"),
        (CHANNEL_PHONE, "Phone"),
    ]

    identifier = models.CharField(max_length=255)  # email or phone number
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES)
    code = models.CharField(max_length=6)
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        unique_together = ("identifier", "channel")
        indexes = [
            models.Index(fields=["identifier", "channel", "expires_at"]),
        ]

    def __str__(self):
        return f"OTP {self.channel} {self.identifier} ({'verified' if self.verified else 'pending'})"
