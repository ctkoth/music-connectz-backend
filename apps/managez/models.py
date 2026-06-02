"""ManageZ models — the manager's back office. ADULT-ONLY (contracts, payouts)."""
import uuid

from django.conf import settings
from django.db import models


def _own(rel):
    return dict(to=settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name=rel)


class RosterArtist(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("managez_roster"))
    name = models.CharField(max_length=160)
    role = models.CharField(max_length=80, blank=True, default="artist")
    status = models.CharField(max_length=16, default="active")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]


class Client(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("managez_clientz"))
    name = models.CharField(max_length=160)
    company = models.CharField(max_length=160, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]


class Contract(models.Model):
    STATUS = [("draft", "Draft"), ("sent", "Sent"), ("signed", "Signed"), ("void", "Void")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("managez_contractz"))
    title = models.CharField(max_length=200)
    party = models.CharField(max_length=160, blank=True, default="")
    terms = models.TextField(blank=True, default="")
    value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=8, choices=STATUS, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Booking(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("managez_bookingz"))
    title = models.CharField(max_length=200)
    venue = models.CharField(max_length=160, blank=True, default="")
    date = models.DateField(null=True, blank=True)
    fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=16, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]


class Deal(models.Model):
    STAGE = [("lead", "Lead"), ("negotiating", "Negotiating"), ("won", "Won"), ("lost", "Lost")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("managez_dealz"))
    title = models.CharField(max_length=200)
    stage = models.CharField(max_length=12, choices=STAGE, default="lead")
    value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Invoice(models.Model):
    STATUS = [("unpaid", "Unpaid"), ("paid", "Paid"), ("overdue", "Overdue")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("managez_invoicez"))
    client = models.CharField(max_length=160, blank=True, default="")
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=8, choices=STATUS, default="unpaid")
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Payout(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("managez_payoutz"))
    payee = models.CharField(max_length=160)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=16, default="pending")
    note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Task(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(**_own("managez_taskz"))
    title = models.CharField(max_length=200)
    done = models.BooleanField(default=False)
    due = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["done", "-created_at"]
