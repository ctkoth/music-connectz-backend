"""Video ConnectZ: price held at start and returned in full on any failure,
the file stored as the member's own upload, and the API key never shown."""
import tempfile
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.economy.models import Face, Upload, VideoWork, wallet_for

User = get_user_model()
URL = "/api/economy/videoz/"
KEY = "SECRET-KEY-123"


def resp(code=200, json=None, content=b""):
    r = MagicMock(status_code=code, text=str(json), content=content)
    r.json.return_value = json or {}
    r.raise_for_status = MagicMock()
    return r


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), OWNER_USERNAMES=["koth"], OWNER_EMAILS=[])
@patch("apps.economy.videoz._key", return_value=KEY)
class VideoTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("koth", "o@e.com", "pw-Long-enough-1")
        self.u = User.objects.create_user("maker", "m@e.com", "pw-Long-enough-1")
        w = wallet_for(self.u); w.promptz = 150; w.money_cents = 1000; w.save()
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def start(self, **kw):
        body = {"kind": "music", "prompt": "neon rooftop, rain", "aspect": "9:16", **kw}
        with patch("apps.economy.videoz.requests.post", return_value=resp(json={"name": "operations/abc"})) as post:
            r = self.c.post(URL, body, format="json")
        return r, post

    def test_the_price_is_published_first(self, _):
        d = self.c.get(URL).json()
        self.assertEqual(d["price_cents"], 400)
        self.assertTrue(d["can_afford"])
        self.assertEqual(len(d["kinds"]), 3)

    def test_starting_holds_promptz_first_then_cash(self, _):
        r, _post = self.start()
        self.assertEqual(r.status_code, 201, r.content)
        w = wallet_for(self.u)
        self.assertEqual((w.promptz, w.money_cents), (0, 750))
        v = VideoWork.objects.get()
        self.assertEqual((v.held_promptz, v.held_cash, v.status), (150, 250, "pending"))

    def test_cannot_afford_holds_nothing(self, _):
        w = wallet_for(self.u); w.promptz = 0; w.money_cents = 10; w.save()
        r, post = self.start()
        self.assertEqual(r.status_code, 402)
        post.assert_not_called()
        self.assertEqual(wallet_for(self.u).money_cents, 10)

    def test_a_refused_start_is_refunded_in_full(self, _):
        with patch("apps.economy.videoz.requests.post", return_value=resp(400, {"error": {"message": "x"}})):
            r = self.c.post(URL, {"kind": "promo", "prompt": "x"}, format="json")
        self.assertEqual(r.status_code, 502)
        w = wallet_for(self.u)
        self.assertEqual((w.promptz, w.money_cents), (150, 1000))
        self.assertEqual(VideoWork.objects.get().status, "failed")

    def test_a_finished_render_is_stored_and_billed_and_the_key_never_leaves(self, _):
        self.start()
        v = VideoWork.objects.get()
        done = resp(json={"done": True, "response": {"generateVideoResponse": {"generatedSamples": [
            {"video": {"uri": "https://generativelanguage.googleapis.com/v1beta/files/x:download?alt=media"}}]}}})
        with patch("apps.economy.videoz.requests.get", side_effect=[done, resp(content=b"\x00\x00\x00 ftypmp4")]):
            r = self.c.get(f"{URL}{v.id}/")
        d = r.json()
        self.assertEqual(d["status"], "done")
        self.assertIn("/api/economy/media/", d["video_url"])
        self.assertNotIn(KEY, r.content.decode())
        self.assertTrue(Upload.objects.filter(user=self.u, content_type="video/mp4").exists())
        self.assertEqual(wallet_for(self.owner).money_cents, 400)

    def test_a_failed_render_is_refunded_in_full(self, _):
        self.start()
        v = VideoWork.objects.get()
        with patch("apps.economy.videoz.requests.get", return_value=resp(json={"done": True, "error": {"message": "filtered"}})):
            d = self.c.get(f"{URL}{v.id}/").json()
        self.assertEqual(d["status"], "failed")
        w = wallet_for(self.u)
        self.assertEqual((w.promptz, w.money_cents), (150, 1000))
        self.assertEqual(wallet_for(self.owner).money_cents, 0)

    def test_a_render_that_never_arrives_is_refunded(self, _):
        self.start()
        VideoWork.objects.update(created_at=timezone.now() - timedelta(minutes=25))
        v = VideoWork.objects.get()
        self.assertEqual(self.c.get(f"{URL}{v.id}/").json()["status"], "failed")
        self.assertEqual(wallet_for(self.u).money_cents, 1000)

    def test_only_your_own_face(self, _):
        other = User.objects.create_user("o2", "o2@e.com", "pw-Long-enough-1")
        f = Face.objects.create(owner=other, image=SimpleUploadedFile("f.jpg", b"\xff\xd8\xff", content_type="image/jpeg"))
        r, post = self.start(face_id=f.id)
        self.assertEqual(r.status_code, 400)
        post.assert_not_called()

    def test_your_face_is_sent_as_the_first_frame(self, _):
        f = Face.objects.create(owner=self.u, image=SimpleUploadedFile("f.jpg", b"\xff\xd8\xffJPEG", content_type="image/jpeg"))
        r, post = self.start(face_id=f.id)
        self.assertEqual(r.status_code, 201, r.content)
        inst = post.call_args.kwargs["json"]["instances"][0]
        self.assertEqual(inst["image"]["mimeType"], "image/jpeg")
        self.assertEqual(post.call_args.kwargs["json"]["parameters"]["aspectRatio"], "9:16")

    def test_a_used_video_pays_the_flat_royalty(self, _):
        v = VideoWork.objects.create(user=self.u, kind="music", prompt="p", status="done")
        from apps.economy.models import Release
        rel = Release.objects.create(user=self.u, title="Single")
        r = self.c.post("/api/economy/intelligence/uses/", {"source": "video", "source_id": v.id,
                                                            "target_kind": "release", "target_id": rel.id}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["royalty_pct"], 10.0)


@patch("apps.economy.videoz._key", return_value=KEY)
class VideoPromptTierCapTests(TestCase):
    def test_the_prompt_answers_to_the_tier_char_limit(self, _):
        u = User.objects.create_user("free1", "f@e.com", "pw-Long-enough-1")
        c = APIClient(); c.force_authenticate(u)
        r = c.post(URL, {"kind": "music", "prompt": "x" * 401, "aspect": "16:9"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["char_limit"], 400)
        self.assertFalse(VideoWork.objects.exists())
