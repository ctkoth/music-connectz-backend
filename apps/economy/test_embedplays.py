"""Plays on Music ConnectZ from the embedded SoundCloud player (embedplays.py)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from .embedplays import (EMBED_PLAY_MIN_SECONDS, EMBED_PLAY_PER_IP_POST, play_count)
from .models import EmbedPlay, Post

User = get_user_model()
PW = "hunter2hunter2"
SC = {"type": "soundcloud", "url": "https://w.soundcloud.com/player/?url=x", "sc_id": "1"}


def url(p):
    return f"/api/economy/postz/{p.pk}/embed-play/"


class EmbedPlayTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user("author", "a@x.test", PW)
        self.post = Post.objects.create(author=self.author, title="t", visibility="public",
                                        embeds=[SC, {"type": "youtube", "url": "https://y"}])

    def as_(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def listen(self, c, post=None, beats=4, step=10, **kw):
        """Heartbeats with the wall clock wound back each time so the clamp
        sees real elapsed time."""
        post = post or self.post
        r = None
        for _ in range(beats):
            r = c.post(url(post), {"index": 0, "seconds": step, **kw}, format="json",
                       REMOTE_ADDR="9.9.9.9")
            EmbedPlay.objects.filter(post=post).update(
                updated_at=timezone.now() - timedelta(seconds=step + 1))
        return r

    def test_thirty_seconds_counts_once(self):
        u = User.objects.create_user("fan", "f@x.test", PW)
        c = self.as_(u)
        r = self.listen(c, beats=2)
        self.assertFalse(r.data["counted"])
        self.assertEqual(r.data["plays"], 0)
        r = self.listen(c, beats=3)
        self.assertTrue(r.data["counted"])
        self.assertEqual(r.data["plays"], 1)
        self.listen(c, beats=5)
        self.assertEqual(play_count(self.post), 1)   # once per member per day

    def test_a_fresh_day_counts_again(self):
        u = User.objects.create_user("fan", "f@x.test", PW)
        c = self.as_(u)
        self.listen(c)
        EmbedPlay.objects.update(day=timezone.localdate() - timedelta(days=1))
        self.listen(c)
        self.assertEqual(play_count(self.post), 2)

    def test_the_wall_clock_clamps_a_burst(self):
        u = User.objects.create_user("fan", "f@x.test", PW)
        c = self.as_(u)
        for _ in range(10):      # ten instant heartbeats claiming 10s each
            r = c.post(url(self.post), {"index": 0, "seconds": 10}, format="json")
        self.assertFalse(r.data["counted"])
        self.assertLess(r.data["seconds"], EMBED_PLAY_MIN_SECONDS)

    def test_the_author_does_not_count(self):
        r = self.listen(self.as_(self.author), beats=6)
        self.assertFalse(r.data["counted"])
        self.assertEqual(r.data["reason"], "own")
        self.assertFalse(EmbedPlay.objects.exists())

    def test_a_non_soundcloud_embed_or_bad_index_is_refused(self):
        c = self.as_(User.objects.create_user("fan", "f@x.test", PW))
        for idx in (1, 7, -1, "x"):
            r = c.post(url(self.post), {"index": idx, "seconds": 5}, format="json")
            self.assertEqual(r.status_code, 400)

    def test_a_post_you_cannot_see_is_404(self):
        p = Post.objects.create(author=self.author, title="d", visibility="private", embeds=[SC])
        c = self.as_(User.objects.create_user("fan", "f@x.test", PW))
        self.assertEqual(c.post(url(p), {"index": 0, "seconds": 5}, format="json").status_code, 404)

    def test_one_browser_through_two_accounts_counts_once(self):
        a = User.objects.create_user("a1", "1@x.test", PW)
        b = User.objects.create_user("a2", "2@x.test", PW)
        self.listen(self.as_(a), anon_id="browser-1")
        r = self.listen(self.as_(b), anon_id="browser-1")
        self.assertFalse(r.data["counted"])
        self.assertEqual(r.data["reason"], "browser")
        self.assertEqual(play_count(self.post), 1)

    def test_one_address_is_a_ceiling_not_a_single_seat(self):
        for i in range(EMBED_PLAY_PER_IP_POST + 2):
            u = User.objects.create_user(f"u{i}", f"u{i}@x.test", PW)
            r = self.listen(self.as_(u), anon_id=f"b{i}")
        self.assertEqual(r.data["reason"], "address")
        self.assertEqual(play_count(self.post), EMBED_PLAY_PER_IP_POST)

    def test_pays_nothing(self):
        from .models import wallet_for
        u = User.objects.create_user("fan", "f@x.test", PW)
        before = (wallet_for(u).energy, wallet_for(u).spinaz)
        self.listen(self.as_(u))
        w = wallet_for(u)
        self.assertEqual(before, (w.energy, w.spinaz))


class FeedCarriesPlaysFlatTests(TestCase):
    def build(self, n):
        author = User.objects.create_user("author", "a@x.test", PW)
        fans = [User.objects.create_user(f"f{i}", f"f{i}@x.test", PW) for i in range(2)]
        for i in range(n):
            p = Post.objects.create(author=author, title=f"p{i}", visibility="public", embeds=[SC])
            for f in fans:
                EmbedPlay.objects.create(post=p, user=f, day=timezone.localdate(),
                                         seconds=30, counted=True)
        return author

    def cost(self, n):
        me = self.build(n)
        c = APIClient()
        c.force_authenticate(me)
        c.get("/api/economy/postz/")
        with CaptureQueriesContext(connection) as q:
            r = c.get("/api/economy/postz/")
        return len(q), r.data["posts"]

    def test_plays_ride_the_feed_without_scaling_it(self):
        small, posts = self.cost(1)
        self.assertEqual(posts[0]["mcz_plays"], 2)
        Post.objects.all().delete()
        User.objects.all().delete()
        big, posts = self.cost(30)
        self.assertEqual(small, big)
        self.assertTrue(all(p["mcz_plays"] == 2 for p in posts))

    def test_a_post_with_no_soundcloud_says_zero_and_costs_nothing(self):
        author = User.objects.create_user("x", "x@x.test", PW)
        Post.objects.create(author=author, title="t", visibility="public")
        c = APIClient()
        c.force_authenticate(author)
        self.assertEqual(c.get("/api/economy/postz/").data["posts"][0]["mcz_plays"], 0)
