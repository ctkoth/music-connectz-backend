"""Direct messages — persistent cross-user DMs.

Respects blocks, enforces the sender's tier character limit, and notifies the
recipient. GET lists conversations (or a thread with ?with=username).
"""
from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from datetime import timedelta

from django.utils import timezone

from .catalog import limits_for, edit_window_for
from .models import Message, blocked_user_ids, membership_for, notify

User = get_user_model()


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
    }


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
        return Response({"conversations": list(convos.values())})

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
            m.body = body[: limits_for(membership_for(me).tier)["char_limit"]]
            m.save(update_fields=["body"])
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
        m = Message.objects.create(sender=me, recipient=other, body=body, media_url=media_url, media_type=media_type)
        notify(other, "message", f"@{me.username} messaged you 💬", actor=me, item_id=f"dm:{me.username}")
        return Response(_msg(m, me), status=status.HTTP_201_CREATED)
