"""DawZ — the DAW family + a 'build this first' vote.

DawProposal: one row per DAW concept (feature description + a 'comparable to'
familiarity anchor). DawVote: ONE vote per user, total — voting again just
moves your single vote to the new DAW (enforced by the OneToOne on user).
"""
import uuid

from django.conf import settings
from django.db import models


class DawProposal(models.Model):
    STATUS = [("proposed", "Proposed"), ("building", "Building"), ("live", "Live")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.SlugField(max_length=48, unique=True)        # "fruity-mobius"
    name = models.CharField(max_length=80)
    emoji = models.CharField(max_length=8, default="🎛️")
    color = models.CharField(max_length=9, default="#a855f7")
    comparable_to = models.CharField(max_length=120, blank=True, default="")  # "FL Studio"
    tagline = models.CharField(max_length=160, blank=True, default="")
    description = models.TextField(blank=True, default="")     # what its FEATURES would be
    features = models.JSONField(default=list, blank=True)      # ["Step sequencer", ...]
    status = models.CharField(max_length=12, choices=STATUS, default="proposed")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class DawVote(models.Model):
    """One vote per user, total. OneToOne enforces 'only one DAW' per person."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                primary_key=True, related_name="daw_vote")
    daw = models.ForeignKey(DawProposal, on_delete=models.CASCADE, related_name="votes")
    updated_at = models.DateTimeField(auto_now=True)
