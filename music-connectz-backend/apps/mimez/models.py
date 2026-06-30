"""
MimeZ — mime lipsyncs, selfies, and dance training.

Teen-safe by design: MimeZ is NOT adult-gated. Submissions store metadata and a
reference only (no NSFW pathways, no adult-gating snapshot). Media itself is
handled by the platform's existing upload pipeline; here we record the practice
attempt so it can feed SkillZ XP and the leaderboard.
"""
from django.conf import settings
from django.db import models

APP_KEY = "mimez"

KIND_LIPSYNC = "lipsync"
KIND_SELFIE = "selfie"
KIND_DANCE = "dance"
KIND_CHOICES = [
    (KIND_LIPSYNC, "Lipsync"),
    (KIND_SELFIE, "Selfie expression"),
    (KIND_DANCE, "Dance"),
]


class MimeZSubmission(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mimez_submissions",
    )
    kind = models.CharField(max_length=12, choices=KIND_CHOICES, default=KIND_LIPSYNC)
    drill_key = models.CharField(max_length=80, blank=True, default="")
    caption = models.CharField(max_length=240, blank=True, default="")
    media_ref = models.CharField(
        max_length=255, blank=True, default="",
        help_text="Reference id from the platform upload pipeline (no raw media here).",
    )
    score = models.PositiveIntegerField(default=0)  # 0-100 self/auto rated
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.user} · mimez:{self.kind}"
