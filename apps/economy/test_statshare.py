"""Stats snapshots become posts: written by the server, ranged and audienced by the sharer."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import FunnelEvent, Post, ViewSession

User = get_user_model()


class ViewShareTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("ana", "a@e.com", "pw12345678")
        self.c = APIClient(); self.c.force_authenticate(self.me)
        self.post = Post.objects.create(author=self.me, title="Night Drive", visibility="public")
        now = timezone.now()
        for i, ago in enumerate((1, 2, 20)):  # two inside a week, one outside
            v = ViewSession.objects.create(target=f"post:{self.post.id}", anon_id=f"v{i}", ended_at=now)
            # started_at is auto_now_add, so it is set after create.
            ViewSession.objects.filter(pk=v.pk).update(
                started_at=now - timedelta(days=ago),
                ended_at=now - timedelta(days=ago) + timedelta(seconds=40))

    def test_the_range_is_what_is_counted_and_the_preview_is_the_post(self):
        week = self.c.get(f"/api/economy/views/post/{self.post.id}/share/?days=7").data
        month = self.c.get(f"/api/economy/views/post/{self.post.id}/share/?days=30").data
        self.assertEqual(week["numbers"]["views"], 2)
        self.assertEqual(month["numbers"]["views"], 3)
        r = self.c.post(f"/api/economy/views/post/{self.post.id}/share/",
                        {"days": 7, "visibility": "private", "description": "I typed 9999 views"},
                        format="json")
        self.assertEqual(r.status_code, 201, r.data)
        made = Post.objects.get(pk=r.data["post"]["id"])
        self.assertEqual(made.visibility, "private")
        self.assertEqual(made.description, week["text"])  # the server's text, not the request's

    def test_only_your_own_post(self):
        other = User.objects.create_user("bo", "b@e.com", "pw12345678")
        c = APIClient(); c.force_authenticate(other)
        self.assertEqual(c.get(f"/api/economy/views/post/{self.post.id}/share/").status_code, 404)

    def test_an_odd_range_falls_back_rather_than_refusing(self):
        self.assertEqual(self.c.get(f"/api/economy/views/post/{self.post.id}/share/?days=5000").data["days"], 7)


class FunnelShareTests(TestCase):
    def test_owner_only_and_members_only_when_asked(self):
        u = User.objects.create_user("bo", "b@e.com", "pw12345678")
        c = APIClient(); c.force_authenticate(u)
        self.assertEqual(c.get("/api/economy/funnel/share/").status_code, 403)
        boss = User.objects.create_user("boss", "o@e.com", "pw12345678", is_staff=True)
        c.force_authenticate(boss)
        FunnelEvent.objects.create(kind="landing_view", anon_id="x1")
        plain = c.get("/api/economy/funnel/share/?days=30").data["text"]
        self.assertNotIn("members —", plain)
        self.assertIn("members —", c.get("/api/economy/funnel/share/?days=30&members=1").data["text"])
        r = c.post("/api/economy/funnel/share/", {"days": 30, "visibility": "public"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
