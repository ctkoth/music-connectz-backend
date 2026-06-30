"""Minimal membership so tier gating works in this deployable backend.

tiergate.py resolves the tier from user.membership (this related_name). The full
billing system can replace this later; for now it gives a real free/premium/statz
tier with optional per-feature limit flags.
"""
from django.conf import settings
from django.db import models


class Membership(models.Model):
    TIERS = [("free", "Free"), ("premium", "Premium"), ("statz", "StatZ")]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="membership")
    tier = models.CharField(max_length=12, choices=TIERS, default="free")
    limits = models.JSONField(default=dict, blank=True)   # optional explicit flags
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} · {self.tier}"
