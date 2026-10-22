"""FileZ: a file already uploaded can become the profile picture, and the list says
which post a file lives in (that post is where its likes, ratings and comments are)."""
import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from apps.economy.models import Post, profile_for

User = get_user_model()


def png():
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (0, 200, 255)).save(buf, "PNG")
    return buf.getvalue()


@override_settings(MEDIA_ROOT="/tmp/mcz-test-media")
class FileZTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user("me", "me@e.com", "pw12345678")
        self.c = APIClient(); self.c.force_authenticate(self.me)

    def upload(self, client, name, data, ctype):
        r = client.post("/api/economy/uploads/", {"file": SimpleUploadedFile(name, data, content_type=ctype)},
                        format="multipart")
        self.assertIn(r.status_code, (200, 201), r.data)
        return r.data["upload"]

    def test_my_image_becomes_my_profile_picture(self):
        up = self.upload(self.c, "me.png", png(), "image/png")
        r = self.c.post("/api/economy/profile/avatar/", {"upload_id": up["id"]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(profile_for(self.me).avatar)

    def test_not_an_image_and_not_mine_are_refused(self):
        doc = self.upload(self.c, "song.mp3", b"ID3" + b"x" * 200, "audio/mpeg")
        self.assertEqual(self.c.post("/api/economy/profile/avatar/", {"upload_id": doc["id"]}, format="json").status_code, 400)
        other = User.objects.create_user("them", "t@e.com", "pw12345678")
        oc = APIClient(); oc.force_authenticate(other)
        theirs = self.upload(oc, "them.png", png(), "image/png")
        self.assertEqual(self.c.post("/api/economy/profile/avatar/", {"upload_id": theirs["id"]}, format="json").status_code, 404)
        self.assertFalse(profile_for(self.me).avatar)

    def test_the_list_names_the_post_a_file_lives_in(self):
        up = self.upload(self.c, "beat.mp3", b"ID3" + b"x" * 200, "audio/mpeg")
        loose = self.upload(self.c, "other.mp3", b"ID3" + b"y" * 200, "audio/mpeg")
        post = Post.objects.create(author=self.me, title="Beat", media_url=up["url"], visibility="members")
        rows = {r["id"]: r for r in self.c.get("/api/economy/uploads/").data["uploads"]}
        self.assertEqual(rows[up["id"]]["post"], {"id": post.id, "visibility": "members"})
        self.assertIsNone(rows[loose["id"]]["post"])
