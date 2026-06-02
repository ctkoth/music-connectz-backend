"""ScoutZ — A&R scouting CRM. Premium + ADULT only.

Design note (child safety): this is a PRIVATE notebook for a scout — prospects
the scout is tracking, their own reports, and a pipeline. It is NOT a directory
of artists and creates NO contact channel. Any outreach happens through the
platform's normal (gated) messaging, which separately prevents adult→minor
private contact. We deliberately do not build an open "browse all artists"
discovery feed here, to avoid surfacing minors to adult scouts.
"""
import uuid
from django.conf import settings
from django.db import models

def _own(rel): return dict(to=settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name=rel)


class Prospect(models.Model):
    STAGE = [("watching", "Watching"), ("contacted", "Contacted"),
             ("shortlisted", "Shortlisted"), ("signed", "Signed"), ("passed", "Passed")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("scoutz_prospectz"))
    handle = models.CharField(max_length=120)          # @artist or name (scout's own note)
    name = models.CharField(max_length=160, blank=True, default="")
    genre = models.CharField(max_length=64, blank=True, default="")
    source = models.CharField(max_length=120, blank=True, default="")  # where you found them
    stage = models.CharField(max_length=12, choices=STAGE, default="watching")
    rating = models.PositiveSmallIntegerField(default=0)  # 0-100 your gut score
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta: ordering = ["-updated_at"]


class ScoutingReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("scoutz_reportz"))
    prospect = models.ForeignKey(Prospect, on_delete=models.SET_NULL, null=True, blank=True, related_name="reportz")
    summary = models.CharField(max_length=240)
    scores = models.JSONField(default=dict, blank=True)  # {talent, marketability, fit,...}
    body = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-created_at"]


class Task(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("scoutz_taskz"))
    title = models.CharField(max_length=200)
    done = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["done", "-created_at"]
