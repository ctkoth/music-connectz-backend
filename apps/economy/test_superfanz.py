"""SuperfanZ 🫶: an artist's top fans, counted from what they did, paying nothing."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from . import superfanz as S
from .models import (Block, ItemRating, ListenProgress, Post, PostShare, SocialComment, Wallet,
                     profile_for, wallet_for)

User = get_user_model()


class Fixture(TestCase):
    def setUp(self):
        cache.clear()
        self.artist = User.objects.create_user("artist", password="pw")
        self.post = Post.objects.create(author=self.artist, title="Track", visibility="public")
        self.item = f"post:{self.post.id}"

    def fan(self, name, *, rate=False, comment=False, share=False, listen=False):
        u = User.objects.create_user(name, password="pw")
        if listen:
            ListenProgress.objects.create(user=u, item_id=self.item, seconds=200, finished=True)
        if rate:
            ItemRating.objects.create(user=u, item_id=self.item, score=8)
        if comment:
            SocialComment.objects.create(user=u, item_id=self.item, body="this one")
        if share:
            PostShare.objects.create(post=self.post, user=u)
        cache.clear()
        return u

    def client_for(self, u):
        c = APIClient()
        c.force_authenticate(u)
        return c


class CountedFromWhatTheyDid(Fixture):
    def test_points_and_the_floor(self):
        big = self.fan("big", rate=True, comment=True, share=True, listen=True)   # 2+2+3+1 = 8
        self.fan("once", rate=True)                                               # 2 — under the floor
        d = self.client_for(self.artist).get("/api/economy/superfanz/").data
        self.assertEqual([r["username"] for r in d["top"]], ["big"])
        self.assertEqual(d["top"][0]["points"], 8)
        self.assertEqual(d["top"][0]["share"], 1)
        self.assertTrue(d["mine"])
        self.assertIn("pays nothing", d["rule"])
        self.assertEqual(wallet_for(big).spinaz, 0)

    def test_only_the_top_three(self):
        for i, name in enumerate(["a", "b", "c", "d"]):
            u = self.fan(name, rate=True, comment=True, share=True)
            if i == 3:
                ListenProgress.objects.create(user=u, item_id=self.item, seconds=99, finished=True)
        cache.clear()
        top = [r["username"] for r in self.client_for(self.artist).get("/api/economy/superfanz/").data["top"]]
        self.assertEqual(top, ["d", "a", "b"])

    def test_the_artist_is_never_their_own_fan(self):
        ItemRating.objects.create(user=self.artist, item_id=self.item, score=10)
        SocialComment.objects.create(user=self.artist, item_id=self.item, body="me")
        PostShare.objects.create(post=self.post, user=self.artist)
        self.assertEqual(S.ranked(self.artist.id, self.artist), [])

    def test_where_you_stand(self):
        me = self.fan("me", rate=True)
        d = self.client_for(me).get("/api/economy/superfanz/?username=artist").data
        self.assertEqual(d["you"], {"points": 2, "superfan": False, "to_top": 3})


class WhoMayBeShown(Fixture):
    def test_a_fan_can_leave_every_list_and_still_see_their_standing(self):
        shy = self.fan("shy", rate=True, comment=True, share=True)
        p = profile_for(shy)
        p.visibility = {"superfan": ["private"]}
        p.save()
        d = self.client_for(self.artist).get("/api/economy/superfanz/").data
        self.assertEqual(d["top"], [])
        mine = self.client_for(shy).get("/api/economy/superfanz/?username=artist").data
        self.assertEqual(mine["you"]["points"], 7)
        self.assertEqual(mine["your_listing"], ["private"])

    def test_blocks_hold(self):
        f = self.fan("f", rate=True, comment=True, share=True)
        Block.objects.create(blocker=self.artist, blocked=f)
        self.assertEqual(S.ranked(self.artist.id, self.artist), [])


class TheirCommentsPinFirst(Fixture):
    def test_a_superfans_comment_leads_the_thread(self):
        SocialComment.objects.create(user=self.fan("early", rate=True), item_id=self.item, body="first!")
        big = self.fan("big", rate=True, share=True, listen=True)
        SocialComment.objects.create(user=big, item_id=self.item, body="late but devoted")
        cache.clear()
        d = self.client_for(self.artist).get(f"/api/economy/social/?item={self.item}").data
        self.assertEqual(d["comments"][0]["user"], "big")
        self.assertTrue(d["comments"][0]["superfan"])
        self.assertFalse(d["comments"][1]["superfan"])
