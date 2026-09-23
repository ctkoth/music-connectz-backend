"""Tests for engagement features: presence, activity feed, message receipts."""
from datetime import timedelta
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from rest_framework import status

from .models import Membership, ActivityEvent, Message, membership_for
from . import engagement

User = get_user_model()


class EngagementHelperTests(TestCase):
    """Test engagement helper functions."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pw")
        membership_for(self.user)
        self.other_user = User.objects.create_user(username="otheruser", password="pw")
        membership_for(self.other_user)

    def test_set_online_status(self):
        """set_online_status updates membership fields."""
        engagement.set_online_status(self.user, status="online", activity="listening")
        membership = self.user.membership
        self.assertEqual(membership.online_status, "online")
        self.assertEqual(membership.current_activity, "listening")
        self.assertIsNotNone(membership.last_activity_at)
        self.assertIsNotNone(membership.last_seen)

    def test_set_idle_after_minutes(self):
        """set_idle_after_minutes transitions online users to idle."""
        # Create an online user with old last_activity_at
        self.user.membership.online_status = "online"
        self.user.membership.last_activity_at = timezone.now() - timedelta(minutes=20)
        self.user.membership.save()

        # Should transition to idle
        idled = engagement.set_idle_after_minutes(minutes=15)
        self.assertEqual(idled, 1)

        self.user.membership.refresh_from_db()
        self.assertEqual(self.user.membership.online_status, "idle")

    def test_set_offline_after_hours(self):
        """set_offline_after_hours transitions users to offline."""
        # Create a user with old last_seen
        self.user.membership.last_seen = timezone.now() - timedelta(hours=25)
        self.user.membership.online_status = "online"
        self.user.membership.save()

        # Should transition to offline
        offlined = engagement.set_offline_after_hours(hours=24)
        self.assertEqual(offlined, 1)

        self.user.membership.refresh_from_db()
        self.assertEqual(self.user.membership.online_status, "offline")

    def test_record_activity_event(self):
        """record_activity_event creates timeline entries."""
        event = engagement.record_activity_event(
            actor=self.user,
            subject=self.other_user,
            kind="follow",
            app_key="social",
            target="social:profile?id=1"
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.actor, self.user)
        self.assertEqual(event.subject, self.other_user)
        self.assertEqual(event.kind, "follow")
        self.assertEqual(event.app_key, "social")
        self.assertFalse(event.read)

    def test_record_activity_event_same_user_returns_none(self):
        """record_activity_event returns None when actor == subject."""
        event = engagement.record_activity_event(
            actor=self.user,
            subject=self.user,
            kind="follow"
        )
        self.assertIsNone(event)

    def test_mark_message_delivered(self):
        """mark_message_delivered sets delivered_at timestamp."""
        message = Message.objects.create(
            sender=self.user,
            recipient=self.other_user,
            body="Hello"
        )

        engagement.mark_message_delivered(message)
        message.refresh_from_db()
        self.assertIsNotNone(message.delivered_at)

    def test_mark_message_read(self):
        """mark_message_read sets read_at and read flag."""
        message = Message.objects.create(
            sender=self.user,
            recipient=self.other_user,
            body="Hello"
        )

        engagement.mark_message_read(message)
        message.refresh_from_db()
        self.assertTrue(message.read)
        self.assertIsNotNone(message.read_at)

    def test_get_activity_feed(self):
        """get_activity_feed retrieves paginated events."""
        for i in range(5):
            ActivityEvent.objects.create(
                actor=self.user,
                subject=self.other_user,
                kind="like"
            )

        events = engagement.get_activity_feed(self.other_user, limit=3, offset=0)
        self.assertEqual(len(list(events)), 3)

    def test_get_unread_activity_count(self):
        """get_unread_activity_count returns unread events."""
        ActivityEvent.objects.create(
            actor=self.user,
            subject=self.other_user,
            kind="like",
            read=False
        )
        ActivityEvent.objects.create(
            actor=self.user,
            subject=self.other_user,
            kind="like",
            read=True
        )

        count = engagement.get_unread_activity_count(self.other_user)
        self.assertEqual(count, 1)

    def test_mark_activity_read(self):
        """mark_activity_read marks events as read."""
        event1 = ActivityEvent.objects.create(
            actor=self.user,
            subject=self.other_user,
            kind="like",
            read=False
        )
        event2 = ActivityEvent.objects.create(
            actor=self.user,
            subject=self.other_user,
            kind="like",
            read=False
        )

        # Mark specific event
        engagement.mark_activity_read(self.other_user, event_id=event1.id)
        event1.refresh_from_db()
        event2.refresh_from_db()
        self.assertTrue(event1.read)
        self.assertFalse(event2.read)

    def test_mark_activity_read_all(self):
        """mark_activity_read with event_id=None marks all as read."""
        ActivityEvent.objects.create(
            actor=self.user,
            subject=self.other_user,
            kind="like",
            read=False
        )
        ActivityEvent.objects.create(
            actor=self.user,
            subject=self.other_user,
            kind="like",
            read=False
        )

        engagement.mark_activity_read(self.other_user, event_id=None)
        count = engagement.get_unread_activity_count(self.other_user)
        self.assertEqual(count, 0)

    def test_get_online_count(self):
        """get_online_count returns count of online users."""
        self.user.membership.online_status = "online"
        self.user.membership.save()

        count = engagement.get_online_count()
        self.assertEqual(count, 1)

    def test_get_online_users(self):
        """get_online_users returns list of online users."""
        self.user.membership.online_status = "online"
        self.user.membership.save()

        users = engagement.get_online_users(limit=10)
        users_list = list(users)
        self.assertEqual(len(users_list), 1)
        self.assertEqual(users_list[0][0], self.user.id)
        self.assertEqual(users_list[0][1], self.user.username)

    def test_user_is_online(self):
        """user_is_online checks online status."""
        self.user.membership.online_status = "online"
        self.user.membership.save()

        self.assertTrue(engagement.user_is_online(self.user))

        self.user.membership.online_status = "offline"
        self.user.membership.save()
        self.assertFalse(engagement.user_is_online(self.user))

    def test_get_unread_messages_count(self):
        """get_unread_messages_count returns unread messages."""
        Message.objects.create(
            sender=self.user,
            recipient=self.other_user,
            body="Hi",
            read=False
        )
        Message.objects.create(
            sender=self.user,
            recipient=self.other_user,
            body="Hi2",
            read=True
        )

        count = engagement.get_unread_messages_count(self.other_user)
        self.assertEqual(count, 1)


class PresenceViewSetTests(APITestCase):
    """Test presence tracking endpoints."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pw")
        membership_for(self.user)
        self.other_user = User.objects.create_user(username="otheruser", password="pw")
        membership_for(self.other_user)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_online_users(self):
        """GET /api/economy/presence/online_users/ returns online users."""
        self.other_user.membership.online_status = "online"
        self.other_user.membership.save()

        response = self.client.get("/api/economy/presence/online_users/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("online_count", response.data)
        self.assertIn("users", response.data)

    def test_set_status(self):
        """POST /api/economy/presence/set_status/ updates status."""
        response = self.client.post("/api/economy/presence/set_status/", {
            "status": "online",
            "activity": "listening"
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "online")
        self.assertEqual(response.data["activity"], "listening")

    def test_set_status_invalid(self):
        """POST with invalid status returns 400."""
        response = self.client.post("/api/economy/presence/set_status/", {
            "status": "invalid"
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ActivityFeedViewSetTests(APITestCase):
    """Test activity feed endpoints."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pw")
        membership_for(self.user)
        self.other_user = User.objects.create_user(username="otheruser", password="pw")
        membership_for(self.other_user)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_my_feed(self):
        """GET /api/economy/activity-feed/my_feed/ returns user's feed."""
        ActivityEvent.objects.create(
            actor=self.other_user,
            subject=self.user,
            kind="follow"
        )

        response = self.client.get("/api/economy/activity-feed/my_feed/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("events", response.data)
        self.assertIn("unread_count", response.data)

    def test_my_feed_with_filter(self):
        """GET /api/economy/activity-feed/my_feed/?kind=follow filters events."""
        ActivityEvent.objects.create(
            actor=self.other_user,
            subject=self.user,
            kind="follow"
        )
        ActivityEvent.objects.create(
            actor=self.other_user,
            subject=self.user,
            kind="like"
        )

        response = self.client.get("/api/economy/activity-feed/my_feed/?kind=follow")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["events"]), 1)

    def test_mark_read(self):
        """POST /api/economy/activity-feed/mark_read/ marks events as read."""
        event = ActivityEvent.objects.create(
            actor=self.other_user,
            subject=self.user,
            kind="follow",
            read=False
        )

        response = self.client.post("/api/economy/activity-feed/mark_read/", {
            "event_id": event.id
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        event.refresh_from_db()
        self.assertTrue(event.read)


class MessageReceiptsViewSetTests(APITestCase):
    """Test message read receipts."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pw")
        membership_for(self.user)
        self.other_user = User.objects.create_user(username="otheruser", password="pw")
        membership_for(self.other_user)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_message_receipts(self):
        """GET /api/economy/messages/{id}/receipts/ returns receipt info."""
        message = Message.objects.create(
            sender=self.user,
            recipient=self.other_user,
            body="Hi"
        )

        response = self.client.get(f"/api/economy/messages/{message.id}/receipts/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("delivered", response.data)
        self.assertIn("read", response.data)

    def test_message_receipts_not_found(self):
        """GET with invalid message_id returns 404."""
        response = self.client.get("/api/economy/messages/99999/receipts/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_message_receipts_forbidden(self):
        """GET by non-sender/recipient returns 403."""
        third_user = User.objects.create_user(username="thirduser", password="pw")
        membership_for(third_user)
        message = Message.objects.create(
            sender=self.user,
            recipient=self.other_user,
            body="Hi"
        )

        self.client.force_authenticate(user=third_user)
        response = self.client.get(f"/api/economy/messages/{message.id}/receipts/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_mark_delivered(self):
        """POST /api/economy/messages/{id}/mark-delivered/ marks as delivered."""
        message = Message.objects.create(
            sender=self.user,
            recipient=self.other_user,
            body="Hi"
        )

        self.client.force_authenticate(user=self.other_user)
        response = self.client.post(f"/api/economy/messages/{message.id}/mark-delivered/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        message.refresh_from_db()
        self.assertIsNotNone(message.delivered_at)

    def test_mark_read(self):
        """POST /api/economy/messages/{id}/mark-read/ marks as read."""
        message = Message.objects.create(
            sender=self.user,
            recipient=self.other_user,
            body="Hi"
        )

        self.client.force_authenticate(user=self.other_user)
        response = self.client.post(f"/api/economy/messages/{message.id}/mark-read/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        message.refresh_from_db()
        self.assertTrue(message.read)
        self.assertIsNotNone(message.read_at)
