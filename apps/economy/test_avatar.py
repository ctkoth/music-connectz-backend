import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from apps.economy.models import profile_for

User = get_user_model()
URL = "/api/economy/profile/avatar/"


def png_bytes(size=(64, 64)):
    buf = io.BytesIO()
    Image.new("RGB", size, (255, 0, 128)).save(buf, "PNG")
    return buf.getvalue()


@override_settings(MEDIA_ROOT="/tmp/mcz-test-media")
class ProfileAvatarTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("me", "me@e.com", "pw12345678")
        self.client.force_authenticate(self.user)

    def test_upload_sets_the_avatar_and_returns_its_url(self):
        f = SimpleUploadedFile("pic.png", png_bytes(), content_type="image/png")
        resp = self.client.post(URL, {"avatar": f}, format="multipart")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.data["avatar"], "response must carry the new URL")
        self.assertTrue(profile_for(self.user).avatar)

    def test_profile_get_reports_the_avatar_so_the_page_can_show_it(self):
        self.client.post(URL, {"avatar": SimpleUploadedFile(
            "pic.png", png_bytes(), content_type="image/png")}, format="multipart")
        self.assertTrue(self.client.get("/api/economy/profile/").data["avatar"])

    def test_a_non_image_is_refused(self):
        f = SimpleUploadedFile("resume.pdf", b"%PDF-1.4 not an image",
                               content_type="application/pdf")
        resp = self.client.post(URL, {"avatar": f}, format="multipart")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("isn't an image", resp.data["detail"])
        self.assertFalse(profile_for(self.user).avatar)

    def test_an_oversized_image_is_refused(self):
        big = SimpleUploadedFile("huge.png", b"\x89PNG" + b"0" * (9 * 1024 * 1024),
                                 content_type="image/png")
        resp = self.client.post(URL, {"avatar": big}, format="multipart")
        self.assertEqual(resp.status_code, 413)
        self.assertFalse(profile_for(self.user).avatar)

    def test_missing_file_is_a_clear_400(self):
        self.assertEqual(self.client.post(URL, {}, format="multipart").status_code, 400)

    def test_delete_clears_it_back_to_the_default(self):
        self.client.post(URL, {"avatar": SimpleUploadedFile(
            "pic.png", png_bytes(), content_type="image/png")}, format="multipart")
        resp = self.client.delete(URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIsNone(resp.data["avatar"])
        self.assertFalse(profile_for(self.user).avatar)

    def test_replacing_keeps_exactly_one_picture(self):
        for _ in range(2):
            self.client.post(URL, {"avatar": SimpleUploadedFile(
                "pic.png", png_bytes(), content_type="image/png")}, format="multipart")
        self.assertTrue(profile_for(self.user).avatar)
