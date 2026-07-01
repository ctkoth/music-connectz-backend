"""
DirectZ (app_key "directz") — Dynamic Scene Creation, Audio-Visual Harmony,
and Creative Collaborations training for the DirectZ production pipeline.

DirectZ is an ADULT-GATED app in the platform's child-safety model. This module
adds SkillZ training on top of the existing pipeline. It does NOT recompute the
age-gate at post time — gating is enforced at the view/permission layer using the
platform's existing gate (snapshot-at-activation pattern preserved).

NOTE: if your existing pipeline already uses a different app_key, change APP_KEY
below and the string passed to training_urlpatterns() in urls.py to match, so the
SkillZ XP / badges / leaderboard stay unified with your current data.
"""
from django.conf import settings
from django.db import models

APP_KEY = "directz"

FOCUS_SCENE = "scene"
FOCUS_AV = "av_harmony"
FOCUS_COLLAB = "collab"
FOCUS_CHOICES = [
    (FOCUS_SCENE, "Dynamic Scene Creation"),
    (FOCUS_AV, "Audio-Visual Harmony"),
    (FOCUS_COLLAB, "Creative Collaborations"),
]


class DirectZDraft(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="directz_drafts",
    )
    focus = models.CharField(max_length=16, choices=FOCUS_CHOICES, default=FOCUS_SCENE)
    drill_key = models.CharField(max_length=80, blank=True, default="")
    title = models.CharField(max_length=160, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    scene_count = models.PositiveIntegerField(default=1)
    score = models.PositiveIntegerField(default=0)  # 0-100 craft rating
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.user} · directz:{self.focus}"
