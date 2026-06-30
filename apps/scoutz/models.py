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


# ── LIVE A&R MARKETPLACE ────────────────────────────────────────────────────
# "See real A&R through ScoutZ." Two-sided + LIVE, but ADULT-GATED ON BOTH SIDES
# so the platform's child-safety stance holds: a minor is NEVER listed to, nor
# able to contact, an adult scout. owner_adult_verified is snapshotted at create
# (views enforce AdultOnly), and every browse query filters on it — fail closed.

class TalentListing(models.Model):
    """An artist opts IN to be discoverable by real A&R. Adults only."""
    SEEKING = [("deal", "Record Deal"), ("distribution", "Distribution"),
               ("management", "Management"), ("sync", "Sync / Licensing"),
               ("feature", "Features / Collabs")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("scoutz_talent_listingz"))
    stage_name = models.CharField(max_length=160)
    genre = models.CharField(max_length=64, blank=True, default="")
    pitch = models.TextField(blank=True, default="")
    looking_for = models.CharField(max_length=16, choices=SEEKING, default="deal")
    links = models.JSONField(default=list, blank=True)        # streaming / social links
    post_ref = models.CharField(max_length=64, blank=True, default="")  # showcase PostZ
    open = models.BooleanField(default=True)
    owner_adult_verified = models.BooleanField(default=False)  # snapshot — gate fails closed
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]


class ScoutOpening(models.Model):
    """A real A&R/scout posts what they're actively looking for. Adults + Premium."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("scoutz_openingz"))
    label_or_company = models.CharField(max_length=160, blank=True, default="")
    title = models.CharField(max_length=200)
    looking_for = models.CharField(max_length=200, blank=True, default="")  # genres / vibe
    body = models.TextField(blank=True, default="")
    open = models.BooleanField(default=True)
    owner_adult_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ScoutInterest(models.Model):
    """A scout expresses interest in a TalentListing. Routes to gated messaging."""
    STATUS = [("new", "New"), ("contacted", "Contacted"), ("passed", "Passed")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("scoutz_interestz"))   # the scout
    listing = models.ForeignKey(TalentListing, on_delete=models.CASCADE, related_name="interestz")
    message = models.TextField(blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUS, default="new")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("owner", "listing")
