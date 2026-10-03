from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.social import clean_profile_field


class CleanTests(TestCase):
    def test_caps_and_dedupes(self):
        self.assertEqual(len(clean_profile_field("headline", "x" * 300)), 100)
        self.assertEqual(clean_profile_field("genres", ["Trap", "trap", "Drill"]), ["Trap", "Drill"])
        self.assertEqual(len(clean_profile_field("genres", [f"g{i}" for i in range(30)])), 8)

    def test_cover_must_be_our_media(self):
        self.assertEqual(clean_profile_field("cover_url", "https://evil.example/x.png"), "")
        self.assertEqual(clean_profile_field("cover_url", "/api/economy/media/3/a.png"), "/api/economy/media/3/a.png")
        # The upload endpoint hands out an absolute URL; the path is kept.
        self.assertEqual(clean_profile_field("cover_url", "https://api.x/api/economy/media/3/a.png"), "/api/economy/media/3/a.png")
        self.assertEqual(clean_profile_field("cover_url", "javascript:/api/economy/media/1/a"), "")

    def test_timezone_shape(self):
        self.assertEqual(clean_profile_field("timezone", "America/Denver"), "America/Denver")
        self.assertEqual(clean_profile_field("timezone", "<script>"), "")


class WritersTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("pf", password="pw12345!x")
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def test_both_writers_clean(self):
        r = self.c.patch("/api/auth/me/", {"headline": "Producer", "cover_url": "javascript:x"}, format="json")
        self.assertIn(r.status_code, (200, 201))
        from apps.economy.models import Profile
        p = Profile.objects.get(user=self.u)
        self.assertEqual((p.headline, p.cover_url), ("Producer", ""))
        self.c.post("/api/economy/profile/", {"genres": ["Lo-fi", "lo-fi"], "pronouns": "they/them"}, format="json")
        p.refresh_from_db()
        self.assertEqual((p.genres, p.pronouns), (["Lo-fi"], "they/them"))


class PinnedTests(TestCase):
    def test_pinned_shows_only_own_public_post(self):
        from apps.economy.models import Post, Profile
        u = User.objects.create_user("pin", password="pw12345!x")
        other = User.objects.create_user("oth", password="pw12345!x")
        mine = Post.objects.create(author=u, title="Best", visibility="public")
        theirs = Post.objects.create(author=other, title="Not mine", visibility="public")
        p, _ = Profile.objects.get_or_create(user=u)
        c = APIClient()
        p.pinned_post_id = theirs.id; p.save()
        self.assertIsNone(c.get("/api/economy/public/members/pin/").json()["pinned_post"])
        p.pinned_post_id = mine.id; p.save()
        self.assertEqual(c.get("/api/economy/public/members/pin/").json()["pinned_post"]["title"], "Best")
        mine.visibility = "private"; mine.save()
        self.assertIsNone(c.get("/api/economy/public/members/pin/").json()["pinned_post"])
