"""In-app notifications: list, unread count, mark-read."""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification


def _dict(n):
    return {
        "id": n.id,
        "kind": n.kind,
        "actor": n.actor.username if n.actor else None,
        "text": n.text,
        "item_id": n.item_id,
        "read": n.read,
        "created_at": n.created_at.isoformat(),
    }


class NotificationsView(APIView):
    """GET recent notifications + unread count; POST marks read
    ({id} for one, or {all: true} for all)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Notification.objects.filter(user=request.user).select_related("actor")[:50]
        unread = Notification.objects.filter(user=request.user, read=False).count()
        return Response({"notifications": [_dict(n) for n in qs], "unread": unread})

    def post(self, request):
        if request.data.get("all"):
            Notification.objects.filter(user=request.user, read=False).update(read=True)
        else:
            nid = request.data.get("id")
            if nid is None:
                return Response({"detail": "id or all required"}, status=status.HTTP_400_BAD_REQUEST)
            Notification.objects.filter(user=request.user, id=nid).update(read=True)
        unread = Notification.objects.filter(user=request.user, read=False).count()
        return Response({"unread": unread})
