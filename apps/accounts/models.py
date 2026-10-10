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
    # Whether the PROVIDER vouched for `email` when this identity was linked or
    # last signed in. It is the difference between two accounts that share an
    # address and two accounts that share an inbox: an unconfirmed address is a
    # string somebody typed into a provider, and DupeZ lets a shared one close an
    # account (`dupez.has_proof`). False for everything linked before this
    # column existed, which is the safe answer — "we cannot say" never counts as
    # proof — and a member's next sign-in with that provider upgrades it.
    email_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("provider", "provider_uid")
        verbose_name_plural = "OAuth identities"

    def __str__(self):
        return f"{self.provider}:{self.provider_uid}"
