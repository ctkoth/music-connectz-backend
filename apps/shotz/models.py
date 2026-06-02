"""ShotZ models — the video bay for videographers. Workspace + training. Youth-safe."""
import uuid
from django.conf import settings
from django.db import models

def _own(rel): return dict(to=settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name=rel)

class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("shotz_projectz"))
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=24, default="music-video")
    status = models.CharField(max_length=16, default="draft")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True); updated_at = models.DateTimeField(auto_now=True)
    class Meta: ordering = ["-updated_at"]

class Clip(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("shotz_clipz"))
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="clipz")
    name = models.CharField(max_length=200); url = models.URLField(blank=True, default="")
    duration_s = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-created_at"]

class Footage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("shotz_footage"))
    name = models.CharField(max_length=200); url = models.URLField(blank=True, default="")
    tag = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-created_at"]

class Storyboard(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("shotz_storyboardz"))
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="storyboardz")
    title = models.CharField(max_length=200); frames = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-created_at"]

class ShotListItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("shotz_shotlistz"))
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="shotlistz")
    shot = models.CharField(max_length=200); captured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["captured", "-created_at"]

class Location(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("shotz_locationz"))
    name = models.CharField(max_length=200); address = models.CharField(max_length=240, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["name"]

class Render(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("shotz_renderz"))
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="renderz")
    label = models.CharField(max_length=200); status = models.CharField(max_length=16, default="queued")
    output_url = models.URLField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-created_at"]
