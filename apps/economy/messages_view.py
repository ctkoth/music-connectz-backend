"""Direct messages — persistent cross-user DMs.

Respects blocks, enforces the sender's tier character limit, and notifies the
recipient. GET lists conversations (or a thread with ?with=username).
"""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from datetime import timedelta

from django.utils import timezone

from .catalog import limits_for, edit_window_for
from .models import (
    Message, Notification, blocked_user_ids, membership_for, notify,
)

User = get_user_model()
logger = logging.getLogger(__name__)


def _msg(m, me):
    return {
        "id": m.id,
        "from": m.sender.username,
        "to": m.recipient.username,
        "mine": m.sender_id == me.id,
        "body": m.body,
        "media_url": m.media_url,
        "media_type": m.media_type,
        "read": m.read,
        "at": m.created_at.isoformat(),
        "edited_at": m.edited_at.isoformat() if m.edited_at else None,
        "edit_history": m.edit_history or [],
    }


def _email_new_message(recipient, sender, body):
    """Tell them by email as well as in-app — once, and never at the message's
    expense.

    `notify()` writes a Notification row and stops there, which is only any use
    to somebody who happens to open the app. A direct message is the one thing
    here that is *waiting on a person*, so it is worth reaching them where they
    are.

    Three refusals, in the order they actually come up:

      * **No address.** Every account made through a provider that hands one
        over has `''` — Twitter gives none at all. Nothing to send to.
      * **Opted out.** A member who turned notifications off meant it.
      * **Already told and not read.** Ten messages in a row is ONE email. A
        second is worth nothing to somebody who has not opened the first, and
        it is exactly how a product teaches people to filter it to spam.

    Wrapped whole and never re-raised: the message is already saved and the
    notification already written. A mail server having a bad day must not turn
    a delivered message into a 500.
    """
    to = (getattr(recipient, "email", "") or "").strip()
    if not to:
        return False
    try:
        prefs = getattr(recipient, "onboarding_preferences", None)
        if prefs is not None and not prefs.notifications_enabled:
            return False
        # Counted BEFORE this message's own notification is written, so the row
        # we just made can never be the one that suppresses its own email.
        if Notification.objects.filter(
            user=recipient, actor=sender, kind="message", read=False
        ).exists():
            return False

        preview = (body or "").strip().replace("\r", "")
        if len(preview) > 300:
            preview = preview[:297] + "..."

        send_mail(
            subject=f"@{sender.username} messaged you on Music ConnectZ",
            message=(
                f"Hi {recipient.username},\n\n"
                f"@{sender.username} sent you a message:\n\n"
                f"{preview}\n\n"
                f"Reply here: {getattr(settings, 'FRONTEND_URL', '').rstrip('/')}/message\n\n"
                "You're getting this because someone messaged you directly. "
                "Turn these off in your preferences any time.\n\n"
                "— Music ConnectZ"
            ),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[to],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception("Could not email @%s about a message", recipient.username)
        return False


class MessagesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        me = request.user
        peer = (request.query_params.get("with") or "").strip()
        if peer:
            other = User.objects.filter(username=peer).first()
            if not other:
                return Response({"detail": "unknown user"}, status=status.HTTP_404_NOT_FOUND)
            thread = Message.objects.filter(
                Q(sender=me, recipient=other) | Q(sender=other, recipient=me)
            ).select_related("sender", "recipient")[:200]
            # Mark their messages to me as read.
            Message.objects.filter(sender=other, recipient=me, read=False).update(read=True)
            return Response({"with": other.username, "messages": [_msg(m, me) for m in thread]})

        # Conversation list: latest message per peer + unread count.
        msgs = Message.objects.filter(Q(sender=me) | Q(recipient=me)).select_related("sender", "recipient").order_by("-created_at")[:500]
        convos = {}
        for m in msgs:
            other = m.recipient if m.sender_id == me.id else m.sender
            if other.id not in convos:
                convos[other.id] = {"user": other.username, "last": m.body[:80], "at": m.created_at.isoformat(), "unread": 0}
            if m.recipient_id == me.id and not m.read:
                convos[other.id]["unread"] += 1

        # inbox/sent are the flat split the MessageZ screen renders. They come
        # off the same 500 rows already fetched above — no extra queries — and
        # sit alongside `conversations` so a threaded view can use that instead
        # without another endpoint.
        inbox = [_msg(m, me) for m in msgs if m.recipient_id == me.id]
        sent = [_msg(m, me) for m in msgs if m.sender_id == me.id]
        return Response({
            "conversations": list(convos.values()),
            "inbox": inbox,
            "sent": sent,
            # DMs cost nothing here today. Reported so the client states the
            # real price instead of assuming one.
            "dm_cost_energy": 0,
        })

    def post(self, request):
        me = request.user
        body = str((request.data or {}).get("body", "")).strip()
        # Edit an existing message (sender only, within the tier's edit window).
        edit_id = (request.data or {}).get("edit_id")
        if edit_id is not None:
            m = Message.objects.filter(pk=edit_id, sender=me).first()
            if not m:
                return Response({"detail": "message not found"}, status=status.HTTP_404_NOT_FOUND)
            window = edit_window_for(membership_for(me).tier)
            if timezone.now() > m.created_at + timedelta(seconds=window):
                return Response({"detail": "edit_window_passed", "window_seconds": window}, status=status.HTTP_403_FORBIDDEN)
            if not body:
                return Response({"detail": "body required"}, status=status.HTTP_400_BAD_REQUEST)
            # Record the prior version, then apply the edit.
            m.edit_history = (m.edit_history or []) + [{"body": m.body, "at": timezone.now().isoformat()}]
            m.body = body[: limits_for(membership_for(me).tier)["char_limit"]]
            m.edited_at = timezone.now()
            m.save(update_fields=["body", "edit_history", "edited_at"])
            return Response(_msg(m, me))

        to = str((request.data or {}).get("to", "")).strip()
        media_url = str((request.data or {}).get("media_url", "")).strip()[:500]
        media_type = str((request.data or {}).get("media_type", "")).strip()[:60]
        if not to or not (body or media_url):
            return Response({"detail": "to and body (or media) required"}, status=status.HTTP_400_BAD_REQUEST)
        other = User.objects.filter(username=to).first()
        if not other:
            return Response({"detail": "unknown user"}, status=status.HTTP_404_NOT_FOUND)
        if other.id == me.id:
            return Response({"detail": "can't message yourself"}, status=status.HTTP_400_BAD_REQUEST)
        if other.id in blocked_user_ids(me):
            return Response({"detail": "You've blocked this user (or they blocked you)."}, status=status.HTTP_403_FORBIDDEN)
        cap = limits_for(membership_for(me).tier)["char_limit"]
        if len(body) > cap:
            return Response({"detail": f"Message exceeds your {cap}-character limit — upgrade for more."}, status=status.HTTP_400_BAD_REQUEST)
        # ZodiacZ — the Rooster speaks first. Both facts have to be read
        # BEFORE the row exists: afterwards this conversation is never new and
        # the distinct-recipient count is always one higher than the truth.
        first_to_them = not Message.objects.filter(sender=me, recipient=other).exists()
        spoken_to = (Message.objects.filter(sender=me)
                     .values_list("recipient_id", flat=True).distinct().count())

        m = Message.objects.create(sender=me, recipient=other, body=body, media_url=media_url, media_type=media_type)
        if first_to_them:
            from .signbonus import try_award
            try_award(me, "first_message", stretch=spoken_to + 1 >= 3)
        # Email BEFORE the notification is written: the "already told them"
        # check reads unread notifications, and this message's own row would
        # otherwise suppress its own email.
        _email_new_message(other, me, body)
        notify(other, "message", f"@{me.username} messaged you 💬", actor=me, item_id=f"dm:{me.username}")
        return Response(_msg(m, me), status=status.HTTP_201_CREATED)
