"""WriteZ models — the writing room for ghostwriters. Workspace + (via skillz) training.

Youth-safe creative tool.
"""
import uuid

from django.conf import settings
from django.db import models


class Project(models.Model):
    KINDS = [("song", "Song"), ("verse", "Verse"), ("topline", "Topline"),
             ("essay", "Essay"), ("contract", "Contract")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="writez_projectz")
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=12, choices=KINDS, default="song")
    genre = models.CharField(max_length=64, blank=True, default="")
    mood = models.CharField(max_length=64, blank=True, default="")
    body = models.TextField(blank=True, default="")        # the working text
    status = models.CharField(max_length=16, default="draft")
    is_public = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title


class Hook(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="writez_hookz")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="hookz")
    text = models.TextField()
    vibe = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class BarSet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="writez_barz")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="barz")
    text = models.TextField()
    scheme = models.CharField(max_length=120, blank=True, default="")  # rhyme scheme / flow note
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class RhymeStack(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="writez_rhymez")
    seed = models.CharField(max_length=120)
    words = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Reference(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="writez_referencez")
    title = models.CharField(max_length=200)
    url = models.URLField(blank=True, default="")
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Brief(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="writez_briefz")
    client = models.CharField(max_length=160)
    requirements = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, default="open")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Version(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="versionz")
    label = models.CharField(max_length=120, default="snapshot")
    snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
