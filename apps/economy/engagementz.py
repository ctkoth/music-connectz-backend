"""API views for engagement features.

Endpoints:
- GET /api/economy/presence/ — Get online users
- POST /api/economy/presence/set-status/ — Set online status + activity
- GET /api/economy/activity-feed/ — Get user's activity events
- POST /api/economy/activity-feed/read/ — Mark activity as read
- GET /api/economy/messages/{id}/receipts/ — Get message delivery/read status
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone

from apps.economy.models import ActivityEvent, Message
from apps.economy import engagement
from apps.economy.serializers import ActivityEventSerializer


class PresenceViewSet(viewsets.ViewSet):
    """Online presence: status, current activity, online users list."""
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"])
    def online_users(self, request):
        """List currently online users."""
        users = engagement.get_online_users(limit=50)
        return Response({
            "online_count": engagement.get_online_count(),
            "users": [{"id": uid, "username": uname} for uid, uname in users],
        })

    @action(detail=False, methods=["post"])
    def set_status(self, request):
        """Update user's online status and current activity.

        POST body:
        {
            "status": "online" | "idle" | "away" | "offline",
            "activity": "listening" | "composing" | "recording" | "battling" | "collaborating" | null
        }
        """
        status_val = request.data.get("status", "online")
        activity = request.data.get("activity")

        if status_val not in ["online", "idle", "away", "offline"]:
            return Response(
                {"error": "Invalid status"},
                status=status.HTTP_400_BAD_REQUEST
            )

        engagement.set_online_status(request.user, status=status_val, activity=activity)

        return Response({
            "status": status_val,
            "activity": activity,
            "last_activity_at": request.user.membership.last_activity_at.isoformat(),
        })

    @action(detail=False, methods=["post"])
    def check_idle(self, request):
        """Admin: Auto-transition idle users (run periodically)."""
        if not request.user.is_staff:
            return Response({"error": "Admin only"}, status=status.HTTP_403_FORBIDDEN)

        minutes = request.data.get("minutes", 15)
        idled = engagement.set_idle_after_minutes(minutes=minutes)

        return Response({
            "idled_users": idled,
            "threshold_minutes": minutes,
        })

    @action(detail=False, methods=["post"])
    def check_offline(self, request):
        """Admin: Auto-transition offline users (run periodically)."""
        if not request.user.is_staff:
            return Response({"error": "Admin only"}, status=status.HTTP_403_FORBIDDEN)

        hours = request.data.get("hours", 24)
        offlined = engagement.set_offline_after_hours(hours=hours)

        return Response({
            "offlined_users": offlined,
            "threshold_hours": hours,
        })


class ActivityFeedViewSet(viewsets.ViewSet):
    """User activity timeline: followers, likes, ratings, collaborations, battles."""
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"])
    def my_feed(self, request):
        """Get authenticated user's activity feed."""
        kind = request.query_params.get("kind")
        offset = int(request.query_params.get("offset", 0))
        limit = int(request.query_params.get("limit", 50))

        events = engagement.get_activity_feed(request.user, kind=kind, limit=limit, offset=offset)
        unread = engagement.get_unread_activity_count(request.user)

        serializer = ActivityEventSerializer(events, many=True)
        return Response({
            "events": serializer.data,
            "unread_count": unread,
            "offset": offset,
            "limit": limit,
        })

    @action(detail=False, methods=["post"])
    def mark_read(self, request):
        """Mark activity events as read.

        POST body:
        {
            "event_id": null | 123  # null to mark all as read
        }
        """
        event_id = request.data.get("event_id")
        engagement.mark_activity_read(request.user, event_id=event_id)

        unread = engagement.get_unread_activity_count(request.user)
        return Response({"unread_count": unread})


class MessageReceiptsViewSet(viewsets.ViewSet):
    """Message read receipts and delivery status."""
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"], url_path="(?P<message_id>[0-9]+)/receipts")
    def message_receipts(self, request, message_id=None):
        """Get delivery and read status for a message."""
        try:
            message = Message.objects.get(id=message_id)
        except Message.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        # Only sender or recipient can see receipts
        if request.user not in [message.sender, message.recipient]:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        return Response({
            "id": message.id,
            "delivered_at": message.delivered_at.isoformat() if message.delivered_at else None,
            "read_at": message.read_at.isoformat() if message.read_at else None,
            "delivered": message.delivered_at is not None,
            "read": message.read,
        })

    @action(detail=False, methods=["post"], url_path="(?P<message_id>[0-9]+)/mark-delivered")
    def mark_delivered(self, request, message_id=None):
        """Mark message as delivered."""
        try:
            message = Message.objects.get(id=message_id)
        except Message.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        # Only recipient can mark as delivered
        if request.user != message.recipient:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        engagement.mark_message_delivered(message)
        return Response({"delivered_at": message.delivered_at.isoformat()})

    @action(detail=False, methods=["post"], url_path="(?P<message_id>[0-9]+)/mark-read")
    def mark_read(self, request, message_id=None):
        """Mark message as read."""
        try:
            message = Message.objects.get(id=message_id)
        except Message.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        # Only recipient can mark as read
        if request.user != message.recipient:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        engagement.mark_message_read(message)
        return Response({"read_at": message.read_at.isoformat()})
