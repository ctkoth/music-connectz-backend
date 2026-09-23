"""Engagement features: presence tracking, activity feeds, read receipts.

Powers the platform's social signals:
- Online status (green dot)
- What users are doing (listening, composing, etc.)
- Activity timeline (who followed, rated, collaborated)
- Message read receipts
"""
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from apps.economy.models import ActivityEvent, Message

User = get_user_model()


def set_online_status(user, status="online", activity=None):
    """Update user's online status and optional current activity.

    Args:
        user: User object
        status: "online", "idle", "away", "offline"
        activity: Optional activity string ("listening", "composing", "recording", "battling", "collaborating")
    """
    membership = user.membership
    membership.online_status = status
    if activity:
        membership.current_activity = activity
    membership.last_activity_at = timezone.now()
    membership.last_seen = timezone.now()
    membership.save(update_fields=["online_status", "current_activity", "last_activity_at", "last_seen"])


def set_idle_after_minutes(minutes=15):
    """Auto-transition users to idle if inactive for N minutes."""
    threshold = timezone.now() - timedelta(minutes=minutes)
    from django.db.models import Q

    # Find users who are online and haven't had activity in the threshold
    users_to_idle = User.objects.filter(
        membership__online_status="online",
        membership__last_activity_at__lt=threshold,
    ).values_list("pk", flat=True)

    if users_to_idle:
        from apps.economy.models import Membership
        Membership.objects.filter(user_id__in=users_to_idle).update(
            online_status="idle"
        )
    return len(users_to_idle)


def set_offline_after_hours(hours=24):
    """Auto-transition users to offline if not seen in N hours."""
    threshold = timezone.now() - timedelta(hours=hours)
    from django.db.models import Q

    users_to_offline = User.objects.filter(
        membership__last_seen__lt=threshold,
    ).exclude(membership__online_status="offline").values_list("pk", flat=True)

    if users_to_offline:
        from apps.economy.models import Membership
        Membership.objects.filter(user_id__in=users_to_offline).update(
            online_status="offline",
            current_activity=""
        )
    return len(users_to_offline)


def record_activity_event(actor, subject, kind, app_key="", target=""):
    """Record a social activity event in the feed.

    Args:
        actor: User who performed the action
        subject: User who receives the notification
        kind: Event type (follow, like, rate, collab_invite, battle_enter, etc.)
        app_key: Origin app (singz, rapz, battlez, collab, etc.)
        target: Navigation link back to the action (e.g., "singz:post?id=123")

    Returns:
        ActivityEvent instance
    """
    if actor == subject:
        return None  # Don't notify user of their own actions

    event = ActivityEvent.objects.create(
        actor=actor,
        subject=subject,
        kind=kind,
        app_key=app_key,
        target=target,
    )
    return event


def mark_message_delivered(message, delivered_at=None):
    """Mark message as delivered (reached recipient's inbox)."""
    message.delivered_at = delivered_at or timezone.now()
    message.save(update_fields=["delivered_at"])


def mark_message_read(message, read_at=None):
    """Mark message as read with timestamp."""
    message.read = True
    message.read_at = read_at or timezone.now()
    message.save(update_fields=["read", "read_at"])


def get_activity_feed(user, kind=None, limit=50, offset=0):
    """Get a user's activity feed.

    Args:
        user: User whose feed to fetch
        kind: Optional filter by event kind (follow, like, rate, etc.)
        limit: Number of events to return
        offset: Pagination offset

    Returns:
        QuerySet of ActivityEvent ordered by recency
    """
    qs = ActivityEvent.objects.filter(subject=user)

    if kind:
        qs = qs.filter(kind=kind)

    return qs[offset : offset + limit]


def get_unread_activity_count(user):
    """Get count of unread activity events."""
    return ActivityEvent.objects.filter(subject=user, read=False).count()


def mark_activity_read(user, event_id=None):
    """Mark activity event(s) as read.

    Args:
        user: User marking as read
        event_id: Optional specific event to mark; if None, mark all
    """
    if event_id:
        ActivityEvent.objects.filter(subject=user, id=event_id).update(read=True)
    else:
        ActivityEvent.objects.filter(subject=user).update(read=True)


def get_online_count():
    """Get count of currently online users."""
    from apps.economy.models import Membership
    return Membership.objects.filter(online_status="online").count()


def get_online_users(limit=10):
    """Get list of currently online users."""
    from apps.economy.models import Membership
    return User.objects.filter(
        membership__online_status="online"
    ).values_list("id", "username")[:limit]


def user_is_online(user):
    """Check if user is currently online."""
    return user.membership.online_status == "online"


def get_unread_messages_count(user):
    """Get count of unread messages for user."""
    return Message.objects.filter(recipient=user, read=False).count()
