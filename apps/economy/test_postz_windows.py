"""The two numbers the composer has always printed, now actually enforced.

"Rating unlocks 30s after posting (other users only) · comments unlock 60s
after posting" has been on the PostZ composer since it shipped. Nothing checked
either one, and nothing stopped an author rating their own post — so the whole
premise of ChartZ, that a score is what other people think, rested on the
client politely not sending the request.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import (
    POST_COMMENT_UNLOCK_SEC,
    POST_RATE_UNLOCK_SEC,
    ItemRating,
    Post,
    SocialComment,
    wallet_for,
)

User = get_user_model()
PW = "hunter2hunter2"


def age(post, seconds):
    Post.objects.filter(pk=post.pk).update(
        created_at=timezone.now() - timedelta(seconds=seconds))


class RateWindowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.author = User.objects.create_user("author", "a@e.com", PW)
        self.other = User.objects.create_user("other", "o@e.com", PW)
        self.post = Post.objects.create(author=self.author, title="Track", visibility="public")
        self.client.force_authenticate(self.other)

    def rate(self, score=8):
        return self.client.post("/api/economy/social/rate/",
                                {"item": f"post:{self.post.pk}", "action": "rate", "score": score},
                                format="json")

    def test_a_fresh_post_cannot_be_rated_yet(self):
        resp = self.rate()
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.data["unlock_seconds"], POST_RATE_UNLOCK_SEC)
        self.assertGreater(resp.data["seconds_left"], 0)
        self.assertFalse(ItemRating.objects.exists())

    def test_once_the_window_passes_it_can(self):
        age(self.post, POST_RATE_UNLOCK_SEC + 1)
        self.assertEqual(self.rate().status_code, 200)
        self.assertTrue(ItemRating.objects.exists())

    def test_an_author_can_never_rate_their_own_post(self):
        # Not "not yet" — never. A score is what OTHER people think.
        age(self.post, 3600)
        self.client.force_authenticate(self.author)
        resp = self.rate()
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertIn("your own post", resp.data["detail"])
        self.assertFalse(ItemRating.objects.exists())

    def test_a_blocked_rating_pays_no_energy(self):
        self.rate()
        self.assertEqual(wallet_for(self.other).energy, 0)

    def test_clearing_a_rating_is_not_blocked_by_the_window(self):
        # score=0 removes your rating. Refusing that would strand somebody who
        # rated and then changed their mind about having rated at all.
        age(self.post, POST_RATE_UNLOCK_SEC + 1)
        self.rate()
        self.assertEqual(self.rate(score=0).status_code, 200)
        self.assertFalse(ItemRating.objects.exists())

    def test_the_window_only_applies_to_posts(self):
        # Playlists, faces and works have no author and no unlock timer.
        resp = self.client.post("/api/economy/social/rate/",
                                {"item": "playlist:99", "action": "rate", "score": 7},
                                format="json")
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_an_item_pointing_at_no_post_does_not_500(self):
        resp = self.client.post("/api/economy/social/rate/",
                                {"item": "post:999999", "action": "rate", "score": 7},
                                format="json")
        self.assertEqual(resp.status_code, 200, resp.content)


class CommentWindowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.author = User.objects.create_user("author", "a@e.com", PW)
        self.other = User.objects.create_user("other", "o@e.com", PW)
        self.post = Post.objects.create(author=self.author, title="Track", visibility="public")
        self.client.force_authenticate(self.other)

    def comment(self, body="nice"):
        return self.client.post("/api/economy/social/comment/",
                                {"item": f"post:{self.post.pk}", "body": body}, format="json")

    def test_a_fresh_post_cannot_be_commented_on_yet(self):
        resp = self.comment()
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.data["unlock_seconds"], POST_COMMENT_UNLOCK_SEC)
        self.assertFalse(SocialComment.objects.exists())

    def test_once_the_window_passes_it_can(self):
        age(self.post, POST_COMMENT_UNLOCK_SEC + 1)
        self.assertEqual(self.comment().status_code, 200)
        self.assertTrue(SocialComment.objects.exists())

    def test_the_author_may_comment_on_their_own_post(self):
        # Unlike rating. Answering your own thread is normal; scoring yourself
        # is not.
        age(self.post, POST_COMMENT_UNLOCK_SEC + 1)
        self.client.force_authenticate(self.author)
        self.assertEqual(self.comment().status_code, 200)

    def test_comments_open_later_than_ratings(self):
        age(self.post, POST_RATE_UNLOCK_SEC + 1)
        self.assertEqual(self.comment().status_code, 403)
        self.assertEqual(
            self.client.post("/api/economy/social/rate/",
                             {"item": f"post:{self.post.pk}", "action": "rate", "score": 8},
                             format="json").status_code, 200)


class PostPayloadTests(TestCase):
    """The client cannot count down correctly from a clock the server doesn't
    give it — a device an hour fast would show a post as rateable immediately."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("k", "k@e.com", PW)
        self.client.force_authenticate(self.user)

    def create(self, **over):
        return self.client.post("/api/economy/postz/",
                                {"title": "Track", "genre": "Trap", **over}, format="json")

    def test_the_genre_picker_finally_stores_something(self):
        resp = self.create()
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["genre"], "Trap")
        self.assertEqual(Post.objects.get().genre, "Trap")

    def test_the_feed_carries_server_age_and_both_unlocks(self):
        self.create()
        row = self.client.get("/api/economy/postz/").data["posts"][0]
        self.assertIn("age_sec", row)
        self.assertLess(row["age_sec"], 5)
        self.assertEqual(row["rate_unlock_sec"], POST_RATE_UNLOCK_SEC)
        self.assertEqual(row["comment_unlock_sec"], POST_COMMENT_UNLOCK_SEC)
        self.assertEqual(row["genre"], "Trap")

    def test_age_is_measured_from_the_server_not_the_device(self):
        post = Post.objects.create(author=self.user, title="Old", visibility="public")
        age(post, 500)
        rows = {p["title"]: p for p in self.client.get("/api/economy/postz/").data["posts"]}
        self.assertGreaterEqual(rows["Old"]["age_sec"], 499)

    def test_a_genreless_post_is_still_fine(self):
        resp = self.client.post("/api/economy/postz/", {"title": "Track"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["genre"], "")
