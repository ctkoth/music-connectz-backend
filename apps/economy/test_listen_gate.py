"""You may judge it once you have heard some of it.

The rating window was the post's AGE — thirty seconds after it landed, anyone
could rate. That gates the first minute of a post's life and nothing after: a
post three days old had no gate at all, and a feed could be scrolled and fifty
tracks rated in fifty seconds without one of them being played. The rule
members were told was true and did almost nothing.

The tests that matter most here are the clamp ones. The client reports how
long it played, so it can lie — what it cannot do is make time pass.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import (LISTEN_MAX_STEP_SEC, LISTEN_REQUIRED_SEC, ListenProgress,
                     Post, record_listen)

User = get_user_model()


def _post(author, **kw):
    kw.setdefault("title", "A track")
    kw.setdefault("media_type", "audio")
    kw.setdefault("media_url", "/api/economy/media/1/take.wav")
    p = Post.objects.create(author=author, **kw)
    # Old enough that the age window is not what is being tested.
    Post.objects.filter(pk=p.pk).update(
        created_at=timezone.now() - timedelta(days=2))
    return Post.objects.get(pk=p.pk)


class TheClamp(TestCase):
    """What stops a script simply claiming it listened."""

    def setUp(self):
        self.user = User.objects.create_user(username="l1", password="pw")

    def test_a_first_heartbeat_is_capped(self):
        row = record_listen(self.user, "post:1", 9999)
        self.assertEqual(row.seconds, LISTEN_MAX_STEP_SEC)

    def test_the_cap_alone_cannot_unlock_rating(self):
        """One fabricated call must not clear the requirement."""
        self.assertLess(LISTEN_MAX_STEP_SEC, LISTEN_REQUIRED_SEC)

    def test_a_second_heartbeat_is_clamped_to_the_wall_clock(self):
        """Claiming ten more seconds immediately credits about none of it."""
        record_listen(self.user, "post:1", 10)
        row = record_listen(self.user, "post:1", 10)
        # ~0 seconds have really passed, so ~0 (plus 1s round-trip slack).
        self.assertLessEqual(row.seconds, LISTEN_MAX_STEP_SEC + 1)

    def test_time_actually_passing_is_credited(self):
        record_listen(self.user, "post:1", 10)
        ListenProgress.objects.filter(user=self.user, item_id="post:1").update(
            updated_at=timezone.now() - timedelta(seconds=30))
        row = record_listen(self.user, "post:1", 10)
        self.assertEqual(row.seconds, 20)

    def test_negative_and_junk_claims_credit_nothing(self):
        for claim in (-500, "nonsense", None):
            with self.subTest(claim=claim):
                row = record_listen(self.user, f"post:{claim}", claim)
                self.assertEqual(row.seconds, 0)

    def test_a_total_cannot_grow_without_bound(self):
        row = None
        for _ in range(5):
            ListenProgress.objects.filter(user=self.user, item_id="post:9").update(
                updated_at=timezone.now() - timedelta(hours=5))
            row = record_listen(self.user, "post:9", LISTEN_MAX_STEP_SEC)
        self.assertLessEqual(row.seconds, LISTEN_MAX_STEP_SEC * 5)


class TheGate(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(username="a1", password="pw")
        self.rater = User.objects.create_user(username="r1", password="pw")
        self.post = _post(self.author)
        self.item = f"post:{self.post.id}"
        self.client.force_login(self.rater)

    def _rate(self, score=8):
        return self.client.post("/api/economy/social/rate/",
                                {"item": self.item, "action": "rate", "score": score},
                                "application/json")

    def _heard(self, seconds):
        """Credit `seconds` without waiting for them."""
        record_listen(self.rater, self.item, LISTEN_MAX_STEP_SEC)
        ListenProgress.objects.filter(user=self.rater, item_id=self.item).update(
            seconds=seconds)

    def test_an_old_post_could_be_rated_without_listening(self):
        """The hole this exists to close — the age window has long passed.

        403, the same status the age window refuses with, because it is the
        same kind of refusal: you may do this, just not yet.
        """
        r = self._rate()
        self.assertEqual(r.status_code, 403)
        body = r.json()
        self.assertIn("listen", body["detail"].lower())
        # And it says how much more, so the client can count down rather than
        # guess.
        self.assertEqual(body["listen_required_sec"], LISTEN_REQUIRED_SEC)
        self.assertEqual(body["listened_sec"], 0)

    def test_listening_enough_opens_it(self):
        self._heard(LISTEN_REQUIRED_SEC)
        self.assertEqual(self._rate().status_code, 200)

    def test_one_second_short_is_still_short(self):
        self._heard(LISTEN_REQUIRED_SEC - 1)
        r = self._rate()
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["listened_sec"], LISTEN_REQUIRED_SEC - 1)

    def test_finishing_a_short_track_counts(self):
        """A twelve-second beat cannot yield twenty seconds of listening."""
        record_listen(self.rater, self.item, 3, finished=True)
        self.assertEqual(self._rate().status_code, 200)

    def test_lyrics_only_posts_are_not_gated(self):
        """A listening test on text is a wall in front of nothing."""
        words = _post(self.author, media_type="text", media_url="",
                      title="Just words")
        r = self.client.post("/api/economy/social/rate/",
                             {"item": f"post:{words.id}", "action": "rate", "score": 7},
                             "application/json")
        self.assertEqual(r.status_code, 200)

    def test_commenting_is_not_gated_on_listening(self):
        """"What's the sample?" needs no listen. Scoring it is the judgement."""
        r = self.client.post("/api/economy/social/comment/",
                             {"item": self.item, "body": "what's the sample?"},
                             "application/json")
        self.assertEqual(r.status_code, 200)

    def test_the_payload_says_how_far_through_you_are(self):
        """So the control can say "12s to go" instead of refusing when pressed."""
        self._heard(8)
        d = self.client.get(f"/api/economy/social/?item={self.item}").json()
        self.assertEqual(d["listened_sec"], 8)
        self.assertEqual(d["listen_required_sec"], LISTEN_REQUIRED_SEC)
        self.assertFalse(d["listen_finished"])

    def test_the_heartbeat_endpoint_credits_and_reports(self):
        r = self.client.post("/api/economy/social/listened/",
                             {"item": self.item, "seconds": 5}, "application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["listened_sec"], 5)

    def test_the_heartbeat_needs_an_item(self):
        self.assertEqual(self.client.post(
            "/api/economy/social/listened/", {"seconds": 5},
            "application/json").status_code, 400)
