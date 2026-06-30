"""DesignZ models — the Designer workshop. Youth-safe."""
import uuid

from django.conf import settings
from django.db import models


class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="designz_projectz")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=32, default="draft")  # draft|active|done
    width = models.PositiveIntegerField(default=1080)
    height = models.PositiveIntegerField(default=1080)
    cover_url = models.URLField(blank=True, default="")
    canvas = models.JSONField(default=dict, blank=True)  # layers, shapes, etc.
    is_public = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title


class Asset(models.Model):
    KINDS = [("image", "Image"), ("font", "Font"), ("icon", "Icon"), ("other", "Other")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="designz_assetz")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="assetz")
    name = models.CharField(max_length=200)
    file_url = models.URLField(blank=True, default="")
    kind = models.CharField(max_length=12, choices=KINDS, default="image")
    size_bytes = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class Template(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              null=True, blank=True, related_name="designz_templatez")
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=64, default="cover")  # cover|promo|thumbnail
    thumbnail_url = models.URLField(blank=True, default="")
    data = models.JSONField(default=dict, blank=True)
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class BrandKit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="designz_brandkitz")
    name = models.CharField(max_length=120)
    colors = models.JSONField(default=list, blank=True)  # ["#a855f7", ...]
    fonts = models.JSONField(default=list, blank=True)
    logo_url = models.URLField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class Palette(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="designz_palettez")
    name = models.CharField(max_length=120)
    colors = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class Comment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="commentz")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="designz_commentz")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class Version(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="versionz")
    label = models.CharField(max_length=120, default="snapshot")
    snapshot = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, related_name="designz_versionz")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ChallengeSubmission(models.Model):
    """A designer's answer to a SkillZ challenge — produced IN-APP via ImageZ or
    IMPORTED from anything (use whatever tool you like). Stored, scored, and fed
    into the SkillZ engine so it earns XP/badges like any other attempt."""
    SOURCES = [("imagez", "Edited in ImageZ"), ("import", "Imported file"), ("asset", "From DesignZ asset")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="designz_submissionz")
    drill_id = models.UUIDField(db_index=True)              # the SkillZ challenge/drill
    track_key = models.CharField(max_length=64, blank=True, default="")
    source = models.CharField(max_length=8, choices=SOURCES, default="imagez")
    artifact_url = models.URLField(blank=True, default="")  # ImageZ export / imported file / asset url
    asset = models.ForeignKey(Asset, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="submissionz")
    notes = models.TextField(blank=True, default="")
    score = models.PositiveSmallIntegerField(default=0)
    passed = models.BooleanField(default=False)
    xp_earned = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
