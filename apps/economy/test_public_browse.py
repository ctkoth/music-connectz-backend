import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import Post, profile_for


class BrowseTests(TestCase):
    def setUp(self):
        U = get_user_model()
        self.adult = U.objects.create_user("adult", password="pw-long-enough-1")
        self.teen = U.objects.create_user("teen", password="pw-long-enough-1")
        p = profile_for(self.teen); p.birthday = timezone.now().date() - datetime.timedelta(days=365 * 15); p.save()
        self.c = APIClient()

    def post(self, who, vis="public", title="t"):
        return Post.objects.create(author=who, title=title, visibility=vis)

    def test_a_visitor_sees_public_posts_only_and_never_a_minors(self):
        a = self.post(self.adult, title="mine")
        self.post(self.adult, vis="restricted"); self.post(self.adult, vis="private")
        self.post(self.teen, title="teen post")
        r = self.c.get("/api/economy/public/browse/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x["id"] for x in r.data["posts"]], [a.id])
        self.assertEqual(r.data["posts"][0]["open"], f"/p/{a.id}")

    def test_paging(self):
        ids = [self.post(self.adult).id for _ in range(30)]
        r = self.c.get("/api/economy/public/browse/")
        self.assertEqual(len(r.data["posts"]), 24)
        r2 = self.c.get(f"/api/economy/public/browse/?before={r.data['next']}")
        self.assertEqual(len(r2.data["posts"]), 6); self.assertIsNone(r2.data["next"])
        self.assertEqual(sorted(x["id"] for x in r.data["posts"] + r2.data["posts"]), sorted(ids))
