"""The gallery is the images in a member's PUBLIC posts, and nothing behind a wall."""
import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import Post, profile_for

User = get_user_model()


class GalleryTests(TestCase):
    def setUp(self):
        self.ana = User.objects.create_user("ana", "ana@e.com", "pw12345678")

    def post(self, vis="public", **kw):
        return Post.objects.create(author=self.ana, title=kw.pop("title", "t"), visibility=vis, **kw)

    def get(self, client=None, name="ana"):
        return (client or APIClient()).get(f"/api/economy/gallery/{name}/")

    def test_images_from_public_posts_only_newest_first(self):
        old = self.post(title="old", items=[{"type": "image", "url": "/a.png"}])
        new = self.post(title="new", media_type="image", media_url="/b.png",
                        items=[{"type": "image", "url": "/b.png"}, {"type": "audio", "url": "/s.mp3"}])
        Post.objects.filter(pk=old.pk).update(created_at=new.created_at - datetime.timedelta(days=1))
        self.post("restricted", items=[{"type": "image", "url": "/walled.png"}])
        self.post("private", items=[{"type": "image", "url": "/mine.png"}])
        r = self.get()
        self.assertEqual(r.status_code, 200)
        self.assertEqual([(i["url"], i["post_id"]) for i in r.data["images"]],
                         [("/b.png", new.id), ("/a.png", old.id)])

    def test_the_owner_sees_what_a_visitor_sees(self):
        self.post("private", items=[{"type": "image", "url": "/mine.png"}])
        c = APIClient(); c.force_authenticate(self.ana)
        self.assertEqual(self.get(c).data["images"], [])

    def test_a_minors_gallery_is_empty_logged_out_and_shown_inside(self):
        p = profile_for(self.ana); p.birthday = datetime.date.today().replace(year=datetime.date.today().year - 15); p.save()
        self.post(items=[{"type": "image", "url": "/a.png"}])
        self.assertEqual(self.get().data["images"], [])
        bob = User.objects.create_user("bob", "bob@e.com", "pw12345678")
        c = APIClient(); c.force_authenticate(bob)
        self.assertEqual(len(self.get(c).data["images"]), 1)

    def test_unknown_member_is_a_404(self):
        self.assertEqual(self.get(name="nobody").status_code, 404)
