"""Tests for Parcel Primate — Mailchimp-style campaigns."""
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase, APIClient
from rest_framework import status

from apps.economy.models import Follow, Block, Message, Post

User = get_user_model()


class ParcelCampaignGetTests(APITestCase):
    """Test GET endpoint for audience sizes and email readiness."""

    def setUp(self):
        self.client = APIClient()
        self.creator = User.objects.create_user(
            username="creator",
            email="creator@example.com",
            password="pw12345!"
        )

        # Create followers
        self.follower1 = User.objects.create_user(
            username="follower1",
            email="follower1@example.com",
            password="pw12345!"
        )
        self.follower2 = User.objects.create_user(
            username="follower2",
            email="follower2@example.com",
            password="pw12345!"
        )

        # Create friend (mutual follow)
        self.friend = User.objects.create_user(
            username="friend",
            email="friend@example.com",
            password="pw12345!"
        )

        # Create someone creator follows but doesn't follow back (not a fan)
        self.following = User.objects.create_user(
            username="following",
            email="following@example.com",
            password="pw12345!"
        )

        # Create follower relationships
        Follow.objects.create(follower=self.follower1, following=self.creator)
        Follow.objects.create(follower=self.follower2, following=self.creator)
        Follow.objects.create(follower=self.friend, following=self.creator)
        Follow.objects.create(follower=self.creator, following=self.friend)
        Follow.objects.create(follower=self.creator, following=self.following)

    def test_get_audience_sizes(self):
        """GET returns correct audience sizes."""
        self.client.force_authenticate(user=self.creator)
        response = self.client.get("/api/economy/parcel/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.data
        self.assertIn("audiences", data)
        self.assertIn("followers", data["audiences"])
        self.assertIn("fans", data["audiences"])
        self.assertIn("friends", data["audiences"])

        # Followers: follower1, follower2, friend = 3
        self.assertEqual(data["audiences"]["followers"], 3)
        # Fans: follower1, follower2 (follow but not followed back) = 2
        self.assertEqual(data["audiences"]["fans"], 2)
        # Friends: friend (mutual) = 1
        self.assertEqual(data["audiences"]["friends"], 1)

    def test_get_includes_email_readiness(self):
        """GET response includes email_ready flag."""
        self.client.force_authenticate(user=self.creator)
        response = self.client.get("/api/economy/parcel/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("email_ready", response.data)
        self.assertIn("max_recipients", response.data)
        self.assertEqual(response.data["max_recipients"], 5000)

    def test_blocked_users_excluded_from_count(self):
        """Blocked users are excluded from audience counts."""
        # Block one follower
        Block.objects.create(blocker=self.follower1, blocked=self.creator)

        self.client.force_authenticate(user=self.creator)
        response = self.client.get("/api/economy/parcel/")

        # Followers should now be 2 (excluded the blocker)
        self.assertEqual(response.data["audiences"]["followers"], 2)
        # Fans should be 1 (follower2 only)
        self.assertEqual(response.data["audiences"]["fans"], 1)

    def test_unauthenticated_cannot_get_audiences(self):
        """Unauthenticated users cannot view audiences."""
        response = self.client.get("/api/economy/parcel/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ParcelCampaignPostTests(APITestCase):
    """Test POST endpoint for sending campaigns."""

    def setUp(self):
        self.client = APIClient()
        self.creator = User.objects.create_user(
            username="creator",
            email="creator@example.com",
            password="pw12345!"
        )

        # Create audience
        self.recipient1 = User.objects.create_user(
            username="recipient1",
            email="recipient1@example.com",
            password="pw12345!"
        )
        self.recipient2 = User.objects.create_user(
            username="recipient2",
            email="recipient2@example.com",
            password="pw12345!"
        )

        # Create follower relationships
        Follow.objects.create(follower=self.recipient1, following=self.creator)
        Follow.objects.create(follower=self.recipient2, following=self.creator)

    def test_send_campaign_with_post_channel(self):
        """Send campaign with post channel creates a PostZ."""
        self.client.force_authenticate(user=self.creator)
        data = {
            "subject": "New release available",
            "body": "Check out my latest track",
            "audience": "followers",
            "channels": ["post"]
        }
        response = self.client.post("/api/economy/parcel/", data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify response
        self.assertEqual(response.data["recipients"], 2)
        self.assertEqual(response.data["posted"], 1)
        self.assertEqual(response.data["messaged"], 0)

        # Verify post was created
        post = Post.objects.filter(author=self.creator, title="New release available").first()
        self.assertIsNotNone(post)
        self.assertEqual(post.description, "Check out my latest track")
        self.assertEqual(post.media_type, "campaign")
        self.assertEqual(post.visibility, "public")

    def test_send_campaign_with_message_channel(self):
        """Send campaign with message channel creates DMs and notifications."""
        self.client.force_authenticate(user=self.creator)
        data = {
            "subject": "Important update",
            "body": "Read this",
            "audience": "followers",
            "channels": ["message"]
        }
        response = self.client.post("/api/economy/parcel/", data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify response
        self.assertEqual(response.data["messaged"], 2)
        self.assertEqual(response.data["posted"], 0)

        # Verify messages were created
        messages = Message.objects.filter(sender=self.creator)
        self.assertEqual(messages.count(), 2)

        for msg in messages:
            self.assertIn("📣 Important update", msg.body)
            self.assertIn("Read this", msg.body)

    def test_send_campaign_with_multiple_channels(self):
        """Send campaign with post and message channels."""
        self.client.force_authenticate(user=self.creator)
        data = {
            "subject": "Multi-channel",
            "body": "Test content",
            "audience": "followers",
            "channels": ["post", "message"]
        }
        response = self.client.post("/api/economy/parcel/", data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify both channels were used
        self.assertEqual(response.data["posted"], 1)
        self.assertEqual(response.data["messaged"], 2)

    def test_subject_truncated_to_160_chars(self):
        """Subject is truncated to 160 characters."""
        self.client.force_authenticate(user=self.creator)
        long_subject = "a" * 200
        data = {
            "subject": long_subject,
            "body": "Test",
            "audience": "followers",
            "channels": ["post"]
        }
        response = self.client.post("/api/economy/parcel/", data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify subject was truncated
        post = Post.objects.filter(author=self.creator).first()
        self.assertEqual(len(post.title), 160)

    def test_missing_subject_returns_error(self):
        """POST without subject returns 400."""
        self.client.force_authenticate(user=self.creator)
        data = {
            "body": "No subject",
            "audience": "followers",
            "channels": ["post"]
        }
        response = self.client.post("/api/economy/parcel/", data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("subject required", response.data["detail"])

    def test_invalid_audience_returns_error(self):
        """POST with invalid audience returns 400."""
        self.client.force_authenticate(user=self.creator)
        data = {
            "subject": "Test",
            "body": "Content",
            "audience": "everyone",
            "channels": ["post"]
        }
        response = self.client.post("/api/economy/parcel/", data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("audience must be one of", response.data["detail"])

    def test_no_channels_uses_default(self):
        """POST with empty channels list uses default ['post']."""
        self.client.force_authenticate(user=self.creator)
        data = {
            "subject": "Test",
            "body": "Content",
            "audience": "followers",
            "channels": []
        }
        response = self.client.post("/api/economy/parcel/", data, format='json')
        # Empty channels defaults to ["post"], not an error
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["posted"], 1)

    def test_invalid_channels_ignored(self):
        """Invalid channel names are filtered out, valid ones used."""
        self.client.force_authenticate(user=self.creator)
        data = {
            "subject": "Test",
            "body": "Content",
            "audience": "followers",
            "channels": ["post", "invalid", "message", "unknown"]
        }
        response = self.client.post("/api/economy/parcel/", data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Only post and message should work
        self.assertEqual(response.data["posted"], 1)
        self.assertEqual(response.data["messaged"], 2)

    def test_unauthenticated_cannot_send_campaign(self):
        """Unauthenticated users cannot send campaigns."""
        data = {
            "subject": "Test",
            "body": "Content",
            "audience": "followers",
            "channels": ["post"]
        }
        response = self.client.post("/api/economy/parcel/", data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ParcelAudienceTypeTests(APITestCase):
    """Test different audience types (followers, fans, friends)."""

    def setUp(self):
        self.client = APIClient()
        self.creator = User.objects.create_user(
            username="creator",
            email="creator@example.com",
            password="pw12345!"
        )

        # Create users for different audience types
        self.follower_only = User.objects.create_user(
            username="follower_only",
            email="follower_only@example.com",
            password="pw12345!"
        )
        self.friend = User.objects.create_user(
            username="friend",
            email="friend@example.com",
            password="pw12345!"
        )

        # follower_only follows creator
        Follow.objects.create(follower=self.follower_only, following=self.creator)

        # friend and creator follow each other
        Follow.objects.create(follower=self.friend, following=self.creator)
        Follow.objects.create(follower=self.creator, following=self.friend)

    def test_followers_audience(self):
        """'followers' audience includes all who follow the creator."""
        self.client.force_authenticate(user=self.creator)
        data = {
            "subject": "Test",
            "body": "Content",
            "audience": "followers",
            "channels": ["message"]
        }
        response = self.client.post("/api/economy/parcel/", data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Should message both follower_only and friend
        self.assertEqual(response.data["messaged"], 2)

    def test_fans_audience(self):
        """'fans' audience includes followers creator doesn't follow back."""
        self.client.force_authenticate(user=self.creator)
        data = {
            "subject": "Test",
            "body": "Content",
            "audience": "fans",
            "channels": ["message"]
        }
        response = self.client.post("/api/economy/parcel/", data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Should only message follower_only (not friend, since creator follows them back)
        self.assertEqual(response.data["messaged"], 1)

    def test_friends_audience(self):
        """'friends' audience includes mutual follows only."""
        self.client.force_authenticate(user=self.creator)
        data = {
            "subject": "Test",
            "body": "Content",
            "audience": "friends",
            "channels": ["message"]
        }
        response = self.client.post("/api/economy/parcel/", data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Should only message friend
        self.assertEqual(response.data["messaged"], 1)


class ParcelBlockingTests(APITestCase):
    """Test that blocked users are excluded from campaigns."""

    def setUp(self):
        self.client = APIClient()
        self.creator = User.objects.create_user(
            username="creator",
            email="creator@example.com",
            password="pw12345!"
        )

        self.recipient1 = User.objects.create_user(
            username="recipient1",
            email="recipient1@example.com",
            password="pw12345!"
        )
        self.recipient2 = User.objects.create_user(
            username="recipient2",
            email="recipient2@example.com",
            password="pw12345!"
        )

        # Both follow creator
        Follow.objects.create(follower=self.recipient1, following=self.creator)
        Follow.objects.create(follower=self.recipient2, following=self.creator)

    def test_blocked_users_excluded_from_campaign(self):
        """Users who blocked the creator are excluded from campaigns."""
        # Block the creator
        Block.objects.create(blocker=self.recipient1, blocked=self.creator)

        self.client.force_authenticate(user=self.creator)
        data = {
            "subject": "Campaign",
            "body": "Content",
            "audience": "followers",
            "channels": ["message"]
        }
        response = self.client.post("/api/economy/parcel/", data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Only recipient2 should receive the message
        self.assertEqual(response.data["recipients"], 1)
        self.assertEqual(response.data["messaged"], 1)

        messages = Message.objects.all()
        self.assertEqual(messages.count(), 1)
        self.assertEqual(messages[0].recipient, self.recipient2)

    def test_multiple_blocked_users_excluded(self):
        """Multiple blocked users are all excluded."""
        Block.objects.create(blocker=self.recipient1, blocked=self.creator)
        Block.objects.create(blocker=self.recipient2, blocked=self.creator)

        self.client.force_authenticate(user=self.creator)
        data = {
            "subject": "Campaign",
            "body": "Content",
            "audience": "followers",
            "channels": ["message"]
        }
        response = self.client.post("/api/economy/parcel/", data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Neither should receive
        self.assertEqual(response.data["messaged"], 0)


class ParcelDefaultsTests(APITestCase):
    """Test default values for campaign parameters."""

    def setUp(self):
        self.client = APIClient()
        self.creator = User.objects.create_user(
            username="creator",
            email="creator@example.com",
            password="pw12345!"
        )

        self.recipient = User.objects.create_user(
            username="recipient",
            email="recipient@example.com",
            password="pw12345!"
        )

        Follow.objects.create(follower=self.recipient, following=self.creator)

    def test_default_audience_is_followers(self):
        """If audience not specified, defaults to 'followers'."""
        self.client.force_authenticate(user=self.creator)
        data = {
            "subject": "Test",
            "body": "Content",
            "channels": ["message"]
        }
        response = self.client.post("/api/economy/parcel/", data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["messaged"], 1)

    def test_default_channel_is_post(self):
        """If channels not specified, defaults to ['post']."""
        self.client.force_authenticate(user=self.creator)
        data = {
            "subject": "Test",
            "body": "Content",
            "audience": "followers"
        }
        response = self.client.post("/api/economy/parcel/", data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["posted"], 1)
        self.assertEqual(response.data["messaged"], 0)


@override_settings(EMAIL_HOST=None)
class ParcelEmailNotConfiguredTests(APITestCase):
    """Test email behavior when EMAIL_HOST is not configured."""

    def setUp(self):
        self.client = APIClient()
        self.creator = User.objects.create_user(
            username="creator",
            email="creator@example.com",
            password="pw12345!"
        )

        self.recipient = User.objects.create_user(
            username="recipient",
            email="recipient@example.com",
            password="pw12345!"
        )

        Follow.objects.create(follower=self.recipient, following=self.creator)

    def test_email_channel_no_ops_when_not_configured(self):
        """Email channel no-ops when EMAIL_HOST not set."""
        self.client.force_authenticate(user=self.creator)
        data = {
            "subject": "Test",
            "body": "Content",
            "audience": "followers",
            "channels": ["email"]
        }
        response = self.client.post("/api/economy/parcel/", data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Email should be 0 and note should be present
        self.assertEqual(response.data["emailed"], 0)
        self.assertIn("email_note", response.data)
        self.assertIn("switched on", response.data["email_note"])

    def test_other_channels_still_work_without_email(self):
        """Other channels work even if email is not configured."""
        self.client.force_authenticate(user=self.creator)
        data = {
            "subject": "Test",
            "body": "Content",
            "audience": "followers",
            "channels": ["post", "message", "email"]
        }
        response = self.client.post("/api/economy/parcel/", data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Post and message should work
        self.assertEqual(response.data["posted"], 1)
        self.assertEqual(response.data["messaged"], 1)
        # Email should fail gracefully
        self.assertEqual(response.data["emailed"], 0)

    def test_get_shows_email_not_ready(self):
        """GET endpoint shows email_ready as false when not configured."""
        self.client.force_authenticate(user=self.creator)
        response = self.client.get("/api/economy/parcel/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["email_ready"])


from django.core import mail as _mail
from django.test import TestCase as _TC, override_settings as _ovr
from apps.economy.models import (
    Block as _Block, Follow as _Follow, Membership as _M, ParcelCampaign as _PC,
    UserPreferences as _Prefs, TIER_FREE as _FREE, TIER_PREMIUM as _PREM,
)


@_ovr(EMAIL_HOST="smtp.example.com", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class CampaignEmailIsOptInTests(_TC):
    """Following somebody is consent to their posts, not to their mail."""

    def setUp(self):
        self.me = User.objects.create_user("creator_p", "c@e.com", "pw12345!")
        _M.objects.create(user=self.me, tier=_PREM)
        self.yes = User.objects.create_user("wants_p", "yes@e.com", "pw12345!")
        self.no = User.objects.create_user("silent_p", "no@e.com", "pw12345!")
        for u in (self.yes, self.no):
            _Follow.objects.create(follower=u, following=self.me)
        _Prefs.objects.create(user=self.yes, campaign_email=True)
        self.c = APIClient(); self.c.force_authenticate(self.me)
        _mail.outbox = []

    def send(self, **kw):
        return self.c.post("/api/economy/parcel/", {"subject": "New single", "body": "out friday",
                                                     "channels": ["email"], **kw}, format="json")

    def test_only_the_follower_who_asked_gets_email(self):
        r = self.send()
        self.assertEqual(r.data["emailed"], 1)
        self.assertEqual([m.to for m in _mail.outbox], [["yes@e.com"]])

    def test_the_count_is_stated_before_sending(self):
        reach = self.c.get("/api/economy/parcel/").data["reach"]["followers"]
        self.assertEqual((reach["people"], reach["email"]), (2, 1))

    def test_every_email_carries_a_way_out(self):
        self.send()
        m = _mail.outbox[0]
        self.assertIn("/api/economy/parcel/unsubscribe/?t=", m.body)
        self.assertIn("List-Unsubscribe", m.extra_headers)

    def test_notifications_off_means_no_campaign_email_either(self):
        p = _Prefs.objects.get(user=self.yes); p.notifications_enabled = False; p.save()
        self.assertEqual(self.send().data["emailed"], 0)


class UnsubscribeTests(_TC):
    def setUp(self):
        from apps.economy.parcel import unsubscribe_token
        self.u = User.objects.create_user("reader_p", "r@e.com", "pw12345!")
        _Prefs.objects.create(user=self.u, campaign_email=True)
        self.url = f"/api/economy/parcel/unsubscribe/?t={unsubscribe_token(self.u)}"

    def test_opening_the_link_changes_nothing(self):
        # Mail scanners open links; a GET that unsubscribed would act for them.
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(_Prefs.objects.get(user=self.u).campaign_email)

    def test_the_button_turns_it_off_without_signing_in(self):
        r = self.client.post(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(_Prefs.objects.get(user=self.u).campaign_email)

    def test_a_forged_token_does_nothing(self):
        r = self.client.post("/api/economy/parcel/unsubscribe/?t=forged")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(_Prefs.objects.get(user=self.u).campaign_email)

    def test_a_member_can_switch_it_themselves(self):
        c = APIClient(); c.force_authenticate(self.u)
        self.assertFalse(c.post("/api/economy/parcel/email-pref/", {"campaign_email": False}, format="json").data["campaign_email"])
        self.assertTrue(c.post("/api/economy/parcel/email-pref/", {"campaign_email": True}, format="json").data["campaign_email"])


class HowOftenIsALadderTests(_TC):
    def setUp(self):
        self.me = User.objects.create_user("free_p", "f@e.com", "pw12345!")
        _M.objects.create(user=self.me, tier=_FREE)
        self.c = APIClient(); self.c.force_authenticate(self.me)

    def send(self, body="hi"):
        return self.c.post("/api/economy/parcel/", {"subject": "s", "body": body}, format="json")

    def test_free_sends_one_a_week_and_is_told_when_the_next_opens(self):
        self.assertEqual(self.send().status_code, 201)
        r = self.send()
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.data["quota"]["left"], 0)
        self.assertIsNotNone(r.data["quota"]["next_at"])

    def test_the_weekly_count_is_served_before_the_button(self):
        q = self.c.get("/api/economy/parcel/").data["quota"]
        self.assertEqual((q["per_week"], q["left"]), (1, 1))

    def test_the_body_answers_to_the_tier_character_limit(self):
        r = self.send(body="x" * 5000)
        self.assertEqual(r.status_code, 400)
        self.assertFalse(_PC.objects.exists())

    def test_a_send_is_kept_with_a_link_to_its_post(self):
        r = self.send()
        h = self.c.get("/api/economy/parcel/").data["history"]
        self.assertEqual(h[0]["post"]["url"], r.data["post"]["url"])


class SenderBlocksAreRespectedTests(_TC):
    def test_somebody_the_sender_blocked_is_not_reached(self):
        me = User.objects.create_user("blocker_p", "b@e.com", "pw12345!")
        _M.objects.create(user=me, tier=_PREM)
        them = User.objects.create_user("blocked_p", "x@e.com", "pw12345!")
        _Follow.objects.create(follower=them, following=me)
        _Block.objects.create(blocker=me, blocked=them)
        c = APIClient(); c.force_authenticate(me)
        r = c.post("/api/economy/parcel/", {"subject": "s", "channels": ["message"]}, format="json")
        self.assertEqual(r.data["recipients"], 0)
