"""Wallpaper is a Premium/StatZ perk; a profile shows comments and honours the attractiveness opt-in."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import (AttractivenessRating, Membership, Post, SocialComment, membership_for)

User = get_user_model()
PW = "hunter2hunter2"
COVER = "/api/economy/media/1/wall.jpg"


class WallpaperTierTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user(username="wp", password=PW)
        membership_for(self.u)
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def test_free_member_is_refused_a_wallpaper_but_keeps_the_picture(self):
        r = self.c.post("/api/economy/profile/", {"cover_url": COVER}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(self.c.get("/api/economy/profile/").json()["wallpaper_allowed"])

    def test_premium_may_set_and_anyone_may_remove(self):
        Membership.objects.filter(user=self.u).update(tier="premium")
        self.assertEqual(self.c.post("/api/economy/profile/", {"cover_url": COVER}, format="json").status_code, 200)
        Membership.objects.filter(user=self.u).update(tier="free")
        self.assertEqual(self.c.post("/api/economy/profile/", {"cover_url": COVER}, format="json").status_code, 200)
        self.assertEqual(self.c.post("/api/economy/profile/", {"cover_url": ""}, format="json").status_code, 200)


class ShowcaseTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(username="aa", password=PW)
        self.b = User.objects.create_user(username="bb", password=PW)
        for u in (self.a, self.b):
            membership_for(u)
        post = Post.objects.create(author=self.a, title="T", visibility="public")
        SocialComment.objects.create(user=self.b, item_id=f"post:{post.id}", body="nice")
        AttractivenessRating.objects.create(rater=self.b, target=self.a, score=8)
        self.c = APIClient(); self.c.force_authenticate(self.b)

    def test_comments_and_optin_attractiveness(self):
        d = self.c.get("/api/economy/ratez/?username=aa").json()
        self.assertEqual(d["comments"][0]["body"], "nice")
        self.assertEqual(d["attractiveness"]["median"], 8)
        Membership.objects.filter(user=self.a).update(attractiveness_public=False)
        d = self.c.get("/api/economy/ratez/?username=aa").json()
        self.assertIsNone(d["attractiveness"]["median"])
