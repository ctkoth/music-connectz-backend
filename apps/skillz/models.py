"""SkillZ — the gamified training engine behind the creator apps.

Modeled on SingZ/RapZ: a creator app is a set of skill TRACKS, each holding
DRILLS. Users do drills (ATTEMPT), earn XP, level up (SkillProgress), keep a
streak, and climb a leaderboard. One engine serves every app via `app_key`.
"""
import uuid

from django.conf import settings
from django.db import models


class SkillTrack(models.Model):
    """A training track within an app, e.g. ProduceZ > 'Drum Programming'."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    app_key = models.CharField(max_length=32, db_index=True)   # "mixez", "producez", ...
    key = models.SlugField(max_length=64)                      # "drum-programming"
    title = models.CharField(max_length=120)
    persona_skill = models.CharField(max_length=64, blank=True, default="")  # links to a persona SkillZ
    description = models.TextField(blank=True, default="")
    emoji = models.CharField(max_length=8, blank=True, default="🎯")
    color = models.CharField(max_length=9, blank=True, default="#a855f7")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["app_key", "order"]
        unique_together = ("app_key", "key")

    def __str__(self):
        return f"{self.app_key}:{self.title}"


class Drill(models.Model):
    KINDS = [("quiz", "Quiz"), ("practice", "Practice"), ("recording", "Recording"),
             ("freeform", "Freeform"), ("challenge", "Challenge")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    track = models.ForeignKey(SkillTrack, on_delete=models.CASCADE, related_name="drillz")
    title = models.CharField(max_length=160)
    prompt = models.TextField(blank=True, default="")
    kind = models.CharField(max_length=12, choices=KINDS, default="practice")
    difficulty = models.PositiveSmallIntegerField(default=1)   # 1-5
    xp_reward = models.PositiveIntegerField(default=20)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["track", "order"]

    def __str__(self):
        return self.title


class SkillProgress(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="skillz_progress")
    track = models.ForeignKey(SkillTrack, on_delete=models.CASCADE, related_name="progress")
    total_xp = models.PositiveIntegerField(default=0)
    streak_days = models.PositiveIntegerField(default=0)
    last_practiced = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = ("user", "track")


class Attempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="skillz_attempts")
    drill = models.ForeignKey(Drill, on_delete=models.CASCADE, related_name="attempts")
    score = models.PositiveSmallIntegerField(default=0)  # 0-100
    xp_earned = models.PositiveIntegerField(default=0)
    passed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class UserAchievement(models.Model):
    """A badge a user has earned (per app). Catalog metadata is in badges.py."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="skillz_badges")
    code = models.CharField(max_length=48)
    app_key = models.CharField(max_length=32, blank=True, default="")
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "code", "app_key")
        ordering = ["-earned_at"]


class Submission(models.Model):
    """A challenge answer produced IN-APP (ImageZ/SentenceZ/VideoZ) or IMPORTED
    from anywhere, scored and funneled through the SkillZ engine. One model serves
    every creator app via app_key — DesignZ, WriteZ, ShotZ, etc."""
    SOURCES = [("editor", "Edited in-app"), ("import", "Imported"), ("asset", "From asset")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="skillz_submissionz")
    app_key = models.CharField(max_length=32, db_index=True)
    drill = models.ForeignKey(Drill, on_delete=models.CASCADE, related_name="submissionz")
    source = models.CharField(max_length=8, choices=SOURCES, default="editor")
    artifact_url = models.URLField(blank=True, default="")
    content = models.TextField(blank=True, default="")     # for text work (WriteZ)
    notes = models.TextField(blank=True, default="")
    score = models.PositiveSmallIntegerField(default=0)
    passed = models.BooleanField(default=False)
    xp_earned = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
