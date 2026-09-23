"""Parcel Primate — the "Mailchimp knockoff" the blueprint's toolz sign draws
a lemur into, and the actual bulk-email tool that name promises.

**This is not the same feature as MessageZ's Inbox/Outbox.** MessageZ is a
member's own DIRECT MESSAGES to other members — one-to-one, free, and already
served by `messages_view.py`. Parcel Primate is a member sending mail to a
LIST OF EXTERNAL EMAIL ADDRESSES they collected — one-to-many, real SendGrid
spend, and a real unsubscribe obligation. They share the word "mail" and
nothing else: different data, different screen, different cost. Keeping them
in one system would be the cross-pollination rule read backwards — two
genuinely different things forced through one door.

## The gate, same shape as WidgetZ's scan key

`SENDGRID_API_KEY` may not be configured. Building lists and drafting
campaigns needs no external call at all, so that half works with no key.
Sending does — `sendgrid_available()` is the one place that decides, read by
both the view (refuses with a stated reason) and `apps.py`'s system check
(warns in the deploy log, same as `storage_health` warns about uploads with
no durable disk). An unset key must never look like a working Send button
that silently does nothing; it must look like a Send button that says why it
can't.

## Cost — Corey's pricing call is not made here

Sending costs SpinaZ, metered like PromptZ: `PARCEL_FREE_SENDS_DAILY` (100
recipients/day, every tier) covers ordinary use for free, and
`PARCEL_SPINAZ_PER_SEND` (1 🍥 per recipient) is charged only past that free
allowance for that calendar day — so a first campaign to a small list costs
nothing, and a large blast pays per name the way `DAILY_PROMPT_MAX_CENTS`
caps model spend rather than leaving it open-ended. **This number is a
placeholder** — a real number is Corey's price to set, not this file's, per
his own "apply your recommendation, don't ask" instruction: the shape (a
generous free daily floor, then a per-recipient charge) is the recommendation
being applied; the actual 100/1 figures are a guess sized so a first-timer's
test send is always free.

`send_cost()` computes the price BEFORE anything is spent, exactly as the
cost/gain rule asks, so the campaign screen can show "-40 🍥" beside the Send
button before it is pressed, not after.

## Rate limit — capacity, not permission

`PARCEL_MAX_SENDS_DAILY` (500 recipients/member/day, every tier) is the hard
ceiling underneath the SpinaZ meter, the same shape `ratelimit.py` gives
login: SpinaZ can be bought, so a meter alone caps nothing for somebody
willing to pay for it, and a compromised or careless account should not be
able to run SendGrid's API against its own daily volume regardless of
balance. It is address-blind on purpose — this is authenticated, member-keyed
spend, not an anonymous door, so `clientip` has nothing to add here.

## Unsubscribe — a real link, not a promise

Every send appends `unsubscribe_url`, a signed, unauthenticated GET that
flips `MailContact.subscribed = False` and never bounces the contact off a
login wall. `_unsub_token` is HMAC'd off `settings.SECRET_KEY` so a token
cannot be forged from the contact id alone. This is CAN-SPAM's actual
requirement, not a nice-to-have, and the substance rule already says a fake
version of this is worse than none.

## What is NOT built in this pass

* No CSV import — contacts are added one at a time. Said, not hidden.
* No open/click analytics. SendGrid CAN report these via webhooks or the
  Stats API, but wiring a webhook receiver and a stats poll is a second
  feature; faking a percentage here is exactly what the substance rule
  forbids, so none is shown. `MailCampaign.sent_count` is the one number this
  ships with, because it is the one number the send call itself returns.
* No merge-tag templating. Plain per-recipient sends only.
"""
import hashlib
import hmac
import logging
from datetime import date

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pricing / limits — see module docstring. Placeholders pending Corey's call.
# ---------------------------------------------------------------------------
PARCEL_FREE_SENDS_DAILY = 100      # recipients/day covered free, every tier
PARCEL_SPINAZ_PER_SEND = 1         # 🍥 per recipient past the free floor
PARCEL_MAX_SENDS_DAILY = 500       # hard ceiling, regardless of balance


def sendgrid_available():
    """The one reader of the key, so the view and the system check can never
    disagree about whether sending is possible."""
    return bool(getattr(settings, "SENDGRID_API_KEY", "") or "")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class MailList(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="mail_lists")
    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"MailList<{self.name}>"


class MailContact(models.Model):
    mail_list = models.ForeignKey(MailList, on_delete=models.CASCADE, related_name="contacts")
    email = models.EmailField()
    name = models.CharField(max_length=120, blank=True, default="")
    subscribed = models.BooleanField(default=True)
    added_at = models.DateTimeField(auto_now_add=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("mail_list", "email")
        ordering = ("-added_at",)

    def __str__(self):
        return f"MailContact<{self.email}>"


class MailCampaign(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_SENDING = "sending"
    STATUS_SENT = "sent"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SENDING, "Sending"),
        (STATUS_SENT, "Sent"),
    ]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="mail_campaigns")
    mail_list = models.ForeignKey(MailList, on_delete=models.CASCADE, related_name="campaigns")
    subject = models.CharField(max_length=200)
    body = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"MailCampaign<{self.subject}>"


class MailSendLog(models.Model):
    """One row per recipient per campaign send — stops a retried/duplicate
    send call from mailing the same contact twice, and is the real record of
    what actually went out (never invented stats)."""
    campaign = models.ForeignKey(MailCampaign, on_delete=models.CASCADE, related_name="log")
    contact = models.ForeignKey(MailContact, on_delete=models.CASCADE)
    ok = models.BooleanField(default=False)
    detail = models.CharField(max_length=200, blank=True, default="")
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("campaign", "contact")


# ---------------------------------------------------------------------------
# Unsubscribe token — HMAC'd, not a bare id, so it can't be forged or walked.
# ---------------------------------------------------------------------------
def unsub_token(contact_id):
    key = (getattr(settings, "SECRET_KEY", "") or "").encode()
    return hmac.new(key, str(contact_id).encode(), hashlib.sha256).hexdigest()[:32]


def unsub_url(contact):
    base = (getattr(settings, "FRONTEND_API_URL", "") or getattr(settings, "BACKEND_URL", "") or "").rstrip("/")
    return f"{base}/api/economy/parcelprimate/unsubscribe/{contact.id}/{unsub_token(contact.id)}/"


# ---------------------------------------------------------------------------
# Cost / rate-limit helpers
# ---------------------------------------------------------------------------
def _rate_key(user):
    return f"parcelprimate:sends:{user.id}:{date.today().isoformat()}"


def sends_today(user):
    return int(cache.get(_rate_key(user), 0))


def send_cost(user, n_recipients):
    """SpinaZ cost for sending to n_recipients TODAY, given what this member
    has already sent today. Computed BEFORE anything is spent — the cost/gain
    rule's "up front", stated on the campaign screen beside Send."""
    already = sends_today(user)
    free_left = max(0, PARCEL_FREE_SENDS_DAILY - already)
    billable = max(0, n_recipients - free_left)
    return billable * PARCEL_SPINAZ_PER_SEND


def over_daily_cap(user, n_recipients):
    return sends_today(user) + n_recipients > PARCEL_MAX_SENDS_DAILY


def _record_sends(user, n_recipients):
    key = _rate_key(user)
    try:
        cache.incr(key, n_recipients)
    except ValueError:
        cache.set(key, n_recipients, timeout=36 * 60 * 60)


# ---------------------------------------------------------------------------
# SendGrid transport — one real call, no templating, plain per-recipient send.
# ---------------------------------------------------------------------------
def _send_one(to_email, to_name, subject, body_text, unsubscribe_link):
    """POSTs to SendGrid's v3 Mail Send API. Returns (ok, detail)."""
    import requests

    api_key = getattr(settings, "SENDGRID_API_KEY", "") or ""
    from_email = getattr(settings, "PARCEL_FROM_EMAIL", "") or getattr(settings, "DEFAULT_FROM_EMAIL", "") or "no-reply@musicconnectz.com"
    footer = f"\n\n---\nDon't want these? Unsubscribe: {unsubscribe_link}"
    payload = {
        "personalizations": [{
            "to": [{"email": to_email, **({"name": to_name} if to_name else {})}],
        }],
        "from": {"email": from_email},
        "subject": subject[:200],
        "content": [{"type": "text/plain", "value": (body_text or "") + footer}],
    }
    try:
        r = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=15,
        )
        if r.status_code in (200, 201, 202):
            return True, ""
        return False, f"sendgrid {r.status_code}: {r.text[:180]}"
    except Exception as e:
        logger.exception("Parcel Primate send failed to %s", to_email)
        return False, str(e)[:180]


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
def _list_dict(l, contact_count=None):
    return {
        "id": l.id,
        "name": l.name,
        "created_at": l.created_at.isoformat(),
        "contact_count": contact_count if contact_count is not None else l.contacts.count(),
    }


def _contact_dict(c):
    return {
        "id": c.id, "email": c.email, "name": c.name,
        "subscribed": c.subscribed, "added_at": c.added_at.isoformat(),
    }


def _campaign_dict(c):
    return {
        "id": c.id, "mail_list_id": c.mail_list_id, "subject": c.subject,
        "body": c.body, "status": c.status,
        "created_at": c.created_at.isoformat(),
        "sent_at": c.sent_at.isoformat() if c.sent_at else None,
        "sent_count": c.sent_count, "failed_count": c.failed_count,
    }


class ParcelPrimateStatusView(APIView):
    """Published before anything else — the screen reads this to decide
    whether the Send button can even be tried, same as WidgetZ's `may_refuse`
    and `links.scan_available()`."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "sending_available": sendgrid_available(),
            "unavailable_reason": None if sendgrid_available() else
                "Sending isn't configured yet (no SendGrid key) — you can still build lists and draft campaigns.",
            "free_sends_daily": PARCEL_FREE_SENDS_DAILY,
            "spinaz_per_send": PARCEL_SPINAZ_PER_SEND,
            "max_sends_daily": PARCEL_MAX_SENDS_DAILY,
            "sends_today": sends_today(request.user),
        })


class MailListsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        lists = MailList.objects.filter(owner=request.user)
        return Response({"lists": [_list_dict(l) for l in lists]})

    def post(self, request):
        name = str((request.data or {}).get("name", "")).strip()[:120]
        if not name:
            return Response({"detail": "name required"}, status=status.HTTP_400_BAD_REQUEST)
        l = MailList.objects.create(owner=request.user, name=name)
        return Response(_list_dict(l, 0), status=status.HTTP_201_CREATED)


class MailListDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_list(self, request, list_id):
        return MailList.objects.filter(id=list_id, owner=request.user).first()

    def get(self, request, list_id):
        l = self._get_list(request, list_id)
        if not l:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            **_list_dict(l),
            "contacts": [_contact_dict(c) for c in l.contacts.all()[:2000]],
        })

    def delete(self, request, list_id):
        l = self._get_list(request, list_id)
        if not l:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        l.delete()
        return Response({"deleted": True})


class MailContactsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, list_id):
        l = MailList.objects.filter(id=list_id, owner=request.user).first()
        if not l:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        email = str((request.data or {}).get("email", "")).strip().lower()[:254]
        name = str((request.data or {}).get("name", "")).strip()[:120]
        if not email or "@" not in email:
            return Response({"detail": "a real email is required"}, status=status.HTTP_400_BAD_REQUEST)
        c, created = MailContact.objects.get_or_create(
            mail_list=l, email=email, defaults={"name": name, "subscribed": True})
        if not created:
            return Response({"detail": "already on this list"}, status=status.HTTP_409_CONFLICT)
        return Response(_contact_dict(c), status=status.HTTP_201_CREATED)


class MailContactDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, list_id, contact_id):
        c = MailContact.objects.filter(id=contact_id, mail_list_id=list_id, mail_list__owner=request.user).first()
        if not c:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        c.delete()
        return Response({"deleted": True})


class MailCampaignsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        camps = MailCampaign.objects.filter(owner=request.user).select_related("mail_list")
        return Response({"campaigns": [_campaign_dict(c) for c in camps]})

    def post(self, request):
        d = request.data or {}
        list_id = d.get("mail_list_id")
        l = MailList.objects.filter(id=list_id, owner=request.user).first()
        if not l:
            return Response({"detail": "unknown list"}, status=status.HTTP_404_NOT_FOUND)
        subject = str(d.get("subject", "")).strip()[:200]
        body = str(d.get("body", "")).strip()
        if not subject or not body:
            return Response({"detail": "subject and body required"}, status=status.HTTP_400_BAD_REQUEST)
        c = MailCampaign.objects.create(owner=request.user, mail_list=l, subject=subject, body=body)
        return Response(_campaign_dict(c), status=status.HTTP_201_CREATED)


class MailCampaignQuoteView(APIView):
    """The price of Send, BEFORE Send — reads it, spends nothing."""
    permission_classes = [IsAuthenticated]

    def get(self, request, campaign_id):
        c = MailCampaign.objects.filter(id=campaign_id, owner=request.user).select_related("mail_list").first()
        if not c:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        n = c.mail_list.contacts.filter(subscribed=True).count()
        return Response({
            "recipients": n,
            "cost_spinaz": send_cost(request.user, n),
            "over_daily_cap": over_daily_cap(request.user, n),
            "max_sends_daily": PARCEL_MAX_SENDS_DAILY,
            "sending_available": sendgrid_available(),
        })


class MailCampaignSendView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, campaign_id):
        from .models import spend_spinaz

        if not sendgrid_available():
            return Response({
                "detail": "Sending isn't configured yet (no SendGrid key). Your draft is saved.",
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        c = MailCampaign.objects.filter(id=campaign_id, owner=request.user).select_related("mail_list").first()
        if not c:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        if c.status == MailCampaign.STATUS_SENT:
            return Response({"detail": "already sent"}, status=status.HTTP_409_CONFLICT)

        contacts = list(c.mail_list.contacts.filter(subscribed=True))
        if not contacts:
            return Response({"detail": "no subscribed contacts on this list"}, status=status.HTTP_400_BAD_REQUEST)

        if over_daily_cap(request.user, len(contacts)):
            return Response({
                "detail": f"That would put you over today's cap of {PARCEL_MAX_SENDS_DAILY} recipients/day.",
                "sends_today": sends_today(request.user),
                "max_sends_daily": PARCEL_MAX_SENDS_DAILY,
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)

        cost = send_cost(request.user, len(contacts))
        if cost:
            new_balance = spend_spinaz(
                request.user, cost, f"Parcel Primate — {c.subject}",
                app_key="parcelprimate", target=f"parcelprimate:campaign:{c.id}")
            if new_balance is None:
                return Response({
                    "detail": "Not enough SpinaZ for this send.", "cost_spinaz": cost,
                }, status=status.HTTP_402_PAYMENT_REQUIRED)

        c.status = MailCampaign.STATUS_SENDING
        c.save(update_fields=["status"])

        ok_count = 0
        fail_count = 0
        for contact in contacts:
            if MailSendLog.objects.filter(campaign=c, contact=contact).exists():
                continue  # already sent to this contact for this campaign — never twice
            ok, detail = _send_one(contact.email, contact.name, c.subject, c.body, unsub_url(contact))
            MailSendLog.objects.create(campaign=c, contact=contact, ok=ok, detail=detail)
            if ok:
                ok_count += 1
            else:
                fail_count += 1

        _record_sends(request.user, len(contacts))
        c.status = MailCampaign.STATUS_SENT
        c.sent_at = timezone.now()
        c.sent_count = ok_count
        c.failed_count = fail_count
        c.save(update_fields=["status", "sent_at", "sent_count", "failed_count"])

        return Response({
            **_campaign_dict(c),
            "cost_spinaz": cost,
        })


class ParcelUnsubscribeView(APIView):
    """Real, working, unauthenticated — a member reading their inbox has no
    session with us and must never need one to opt out."""
    permission_classes = [AllowAny]

    def get(self, request, contact_id, token):
        if not hmac.compare_digest(token, unsub_token(contact_id)):
            return Response({"detail": "bad or expired link"}, status=status.HTTP_400_BAD_REQUEST)
        c = MailContact.objects.filter(id=contact_id).first()
        if not c:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        if c.subscribed:
            c.subscribed = False
            c.unsubscribed_at = timezone.now()
            c.save(update_fields=["subscribed", "unsubscribed_at"])
        return Response({"unsubscribed": True, "email": c.email})
