"""GameZ models — games created in OCC, plus OCC-produced media with routing.

Tier rules (enforced in views via tiergate):
  • Premium  : code GameZ in OCC WITH AI suggestions (manual).
  • StatZ    : AUTO mode + the Unreal Engine route.
Media routing:
  • Non-owner users: media made in OCC routes to the Intelligence app.
  • Platform owner (staff): may export directly.
"""
import uuid

from django.conf import settings
from django.db import models


class Game(models.Model):
    ENGINES = [("web", "Web (HTML/JS/Canvas)"), ("unreal", "Unreal Engine")]
    STATUS = [("draft", "Draft"), ("building", "Building"), ("playable", "Playable"), ("published", "Published")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="gamez")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    genre = models.CharField(max_length=48, blank=True, default="")
    subgenre = models.CharField(max_length=48, blank=True, default="")
    engine = models.CharField(max_length=8, choices=ENGINES, default="web")
    status = models.CharField(max_length=10, choices=STATUS, default="draft")
    occ_project_ref = models.CharField(max_length=120, blank=True, default="")  # OCC virtual-fs project id
    auto_mode = models.BooleanField(default=False)        # StatZ auto-build
    tier_at_creation = models.CharField(max_length=12, default="premium")
    exported = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]


class OCCMedia(models.Model):
    KINDS = [("image", "Image"), ("audio", "Audio"), ("video", "Video"),
             ("code", "Code"), ("build", "Game Build"), ("other", "Other")]
    ROUTES = [("intelligence", "Routed to Intelligence"), ("export", "Exported by owner")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="occ_mediaz")
    game = models.ForeignKey(Game, on_delete=models.SET_NULL, null=True, blank=True, related_name="mediaz")
    kind = models.CharField(max_length=8, choices=KINDS, default="image")
    url = models.URLField(blank=True, default="")
    source = models.CharField(max_length=16, default="occ")
    routed_to = models.CharField(max_length=16, choices=ROUTES, default="intelligence")
    intelligence_ref = models.CharField(max_length=120, blank=True, default="")  # where it landed in Intelligence
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
