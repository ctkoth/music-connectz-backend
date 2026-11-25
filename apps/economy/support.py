"""Support — a member asks the owner for help, inside the app.

Why this exists as its own thing: BugZ's queue is PUBLIC on purpose (so nobody files the same bug
twice), the report buttons are about other people's content, and "email somebody" is not an in-app
path. A member who is locked out of a feature, charged wrongly or confused needs a private way to
say so, and the store listing's privacy label says Customer Support data is collected — which was not
true until this existed.

Rules, and what each one costs:

* **Private.** A member sees only their own tickets; the owner (superuser or staff) sees the queue.
  Nothing here is public, joined to a rating, or read by any other module.
* **Free and rate-limited.** `PER_DAY` tickets a day. A reply to an existing ticket is not counted,
  so a conversation is never cut off — the limit stops a flood, not a follow-up.
* **No card numbers.** A message with a card-like number is refused with why (`has_card_number`),
  because a support inbox is the place people paste the wrong thing, and the cost of storing a card
  number is much higher than the cost of one more sentence.
* **A reply is a notification**, with the ticket as its target, so the member is told.
* **Deleted with the account**, like every row hanging off a member.
"""
import re

from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import SupportMessage, SupportTicket, notify

PER_DAY = 5
MAX_BODY = 2000
MAX_SUBJECT = 120
MAX_MESSAGES = 60
QUEUE_LIMIT = 100

NOTE = ("Free. Only you and the person who runs Music ConnectZ can read this. Don't send a password or a card "
        "number — nobody needs them to help you.")


def _is_owner(user):
    return bool(user and (user.is_superuser or user.is_staff))


def has_card_number(text):
    """A run of 13-19 digits (spaces and dashes allowed) that passes the Luhn check."""
    for m in re.finditer(r"(?:\d[ -]?){13,19}", text or ""):
        digits = re.sub(r"\D", "", m.group(0))
        if not 13 <= len(digits) <= 19:
            continue
        total, alt = 0, False
        for ch in reversed(digits):
            d = int(ch)
            if alt:
                d *= 2
                if d > 9:
                    d -= 9
            total += d
            alt = not alt
        if total % 10 == 0:
            return True
    return False


def _msg(m):
    return {"id": m.id, "from_owner": m.from_owner, "body": m.body, "at": m.created_at.isoformat()}


def _ticket(t, *, with_user=False):
    d = {"id": t.id, "subject": t.subject, "status": t.status,
         "created_at": t.created_at.isoformat(), "updated_at": t.updated_at.isoformat(),
         "messages": [_msg(m) for m in t.messages.all()]}
    if with_user:
        d["username"] = t.user.username
    return d


def _clean_body(data):
    body = str((data or {}).get("message", (data or {}).get("body", "")) or "").strip()
    if not body:
        return None, Response({"detail": "Write what's wrong, in your own words."}, status=status.HTTP_400_BAD_REQUEST)
    if len(body) > MAX_BODY:
        return None, Response({"detail": f"That's over {MAX_BODY} characters — shorten it, or send the rest as a reply."},
                              status=status.HTTP_400_BAD_REQUEST)
    if has_card_number(body):
        return None, Response({"detail": "That looks like a card number. Please take it out — nobody needs it to help you. "
                                         "Nothing was sent."}, status=status.HTTP_400_BAD_REQUEST)
    return body, None


class SupportView(APIView):
    """GET your tickets · POST {subject, message} opens one."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = SupportTicket.objects.filter(user=request.user).prefetch_related("messages")[:50]
        return Response({"tickets": [_ticket(t) for t in rows], "note": NOTE, "is_owner": _is_owner(request.user),
                         "per_day": PER_DAY})

    def post(self, request):
        subject = str((request.data or {}).get("subject", "")).strip()[:MAX_SUBJECT]
        if not subject:
            return Response({"detail": "Give it a short subject."}, status=status.HTTP_400_BAD_REQUEST)
        body, bad = _clean_body(request.data)
        if bad:
            return bad
        since = timezone.now() - timedelta(hours=24)
        if SupportTicket.objects.filter(user=request.user, created_at__gte=since).count() >= PER_DAY:
            return Response({"detail": f"That's {PER_DAY} requests in a day. Reply to one you already have open — "
                                       "nothing was lost."}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        t = SupportTicket.objects.create(user=request.user, subject=subject)
        SupportMessage.objects.create(ticket=t, from_owner=False, body=body)
        return Response(_ticket(t), status=status.HTTP_201_CREATED)


class SupportReplyView(APIView):
    """POST {message} — a member adds to their own ticket (reopening it)."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        t = SupportTicket.objects.filter(pk=pk, user=request.user).first()
        if not t:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        body, bad = _clean_body(request.data)
        if bad:
            return bad
        if t.messages.count() >= MAX_MESSAGES:
            return Response({"detail": "This conversation is long — open a new request."},
                            status=status.HTTP_400_BAD_REQUEST)
        SupportMessage.objects.create(ticket=t, from_owner=False, body=body)
        t.status = SupportTicket.STATUS_OPEN
        t.save(update_fields=["status", "updated_at"])
        return Response(_ticket(t))


class SupportQueueView(APIView):
    """OWNER ONLY. GET the open and answered tickets, newest activity first."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _is_owner(request.user):
            return Response({"detail": "owner only"}, status=status.HTTP_403_FORBIDDEN)
        rows = (SupportTicket.objects.exclude(status=SupportTicket.STATUS_CLOSED)
                .select_related("user").prefetch_related("messages")[:QUEUE_LIMIT])
        return Response({"tickets": [_ticket(t, with_user=True) for t in rows]})


class SupportAnswerView(APIView):
    """OWNER ONLY. POST {message, close?} — answer a ticket; the member is told."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _is_owner(request.user):
            return Response({"detail": "owner only"}, status=status.HTTP_403_FORBIDDEN)
        t = SupportTicket.objects.filter(pk=pk).select_related("user").first()
        if not t:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        close = bool((request.data or {}).get("close"))
        raw = (request.data or {}).get("message", (request.data or {}).get("body", ""))
        if str(raw or "").strip():
            body, bad = _clean_body(request.data)
            if bad:
                return bad
            SupportMessage.objects.create(ticket=t, from_owner=True, body=body)
            notify(t.user, "system", f"Support replied: {t.subject}", item_id=f"support:{t.id}")
        elif not close:
            return Response({"detail": "Write a reply, or close it."}, status=status.HTTP_400_BAD_REQUEST)
        t.status = SupportTicket.STATUS_CLOSED if close else SupportTicket.STATUS_ANSWERED
        t.save(update_fields=["status", "updated_at"])
        return Response(_ticket(t, with_user=True))
