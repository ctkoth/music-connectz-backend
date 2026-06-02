"""DevelopZ models — the developer console. Youth-safe (learning to build)."""
import uuid

from django.conf import settings
from django.db import models


def _own(rel):
    return dict(to=settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name=rel)


class Repo(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("developz_repoz"))
    name = models.CharField(max_length=160)
    url = models.URLField(blank=True, default="")
    branch = models.CharField(max_length=80, default="main")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]


class Build(models.Model):
    STATUS = [("queued", "Queued"), ("running", "Running"), ("passed", "Passed"), ("failed", "Failed")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("developz_buildz"))
    repo = models.ForeignKey(Repo, on_delete=models.SET_NULL, null=True, blank=True, related_name="buildz")
    commit = models.CharField(max_length=80, blank=True, default="")
    status = models.CharField(max_length=8, choices=STATUS, default="queued")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Deployment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("developz_deploymentz"))
    repo = models.ForeignKey(Repo, on_delete=models.SET_NULL, null=True, blank=True, related_name="deploymentz")
    environment = models.CharField(max_length=32, default="staging")
    status = models.CharField(max_length=16, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Environment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("developz_environmentz"))
    name = models.CharField(max_length=32)  # dev / staging / prod
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]


class ApiKey(models.Model):
    """Stores only a prefix + a hash of the key. The plaintext is returned ONCE
    on creation and never again — standard secure key handling."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("developz_api_keyz"))
    label = models.CharField(max_length=120)
    prefix = models.CharField(max_length=12, blank=True, default="")
    hashed = models.CharField(max_length=256, blank=True, default="")
    revoked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Webhook(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("developz_webhookz"))
    url = models.URLField()
    event = models.CharField(max_length=64, default="*")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Snippet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("developz_snippetz"))
    title = models.CharField(max_length=160)
    language = models.CharField(max_length=32, default="python")
    code = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Task(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("developz_taskz"))
    title = models.CharField(max_length=200)
    done = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["done", "-created_at"]
