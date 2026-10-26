"""Image ConnectZ by kind: the server frames the picture for its use, a likeness is
only ever the member's own, and the frame shape survives a model that refuses it."""
import tempfile
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.economy import imagez
from apps.economy.models import GeneratedImage, wallet_for

URL = "/api/economy/gemini/image/"
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
SELFIE = "data:image/png;base64," + PNG


def picture():
    r = MagicMock(status_code=200)
    r.json.return_value = {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": PNG}}]}}]}
    return r


def nothing():
    r = MagicMock(status_code=400)
    r.json.return_value = {"error": {"message": "Unknown name imageConfig"}}
    return r


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class KindTests(TestCase):
    def setUp(self):
        k = patch("apps.economy.gemini._key", return_value="k"); k.start(); self.addCleanup(k.stop)
        self.u = get_user_model().objects.create_user("painter", "p@e.com", "pw-Long-enough-1")
        w = wallet_for(self.u); w.money_cents = 1000; w.promptz = 100; w.save()
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def test_get_publishes_every_kind_with_its_shape_and_use(self):
        d = self.c.get(URL).data
        kinds = {k["key"]: k for k in d["kinds"]}
        self.assertEqual(kinds["wallpaper_phone"]["aspect"], "9:16")
        self.assertEqual(kinds["header"]["aspect"], "21:9")
        self.assertTrue(kinds["profile_pic"]["likeness"])
        self.assertFalse(kinds["logo"]["likeness"])
        self.assertNotIn("brief", kinds["song_cover"])          # the model's brief is ours, not the screen's
        self.assertFalse(d["free_today"])                        # a picture is never covered by the allowance
        self.assertTrue(d["styles"] and d["moods"])

    @patch("apps.economy.gemini.requests.post")
    def test_a_kind_frames_the_prompt_sends_the_shape_and_is_kept(self, post):
        post.return_value = picture()
        r = self.c.post(URL, {"kind": "song_cover", "prompt": "a lighthouse in a storm", "style": "oil",
                              "mood": "epic", "text": "Night Shift"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        body = post.call_args.kwargs["json"]
        text = body["contents"][0]["parts"][0]["text"]
        self.assertIn("cover art for a single", text)
        self.assertIn("Oil painting", text)
        self.assertIn('"Night Shift"', text)
        self.assertTrue(text.endswith("a lighthouse in a storm"))     # the member's words come last
        self.assertEqual(body["generationConfig"]["imageConfig"], {"aspectRatio": "1:1"})
        w = GeneratedImage.objects.get()
        self.assertEqual(w.kind, "song_cover")
        self.assertEqual(r.data["work"]["kind"], "song_cover")
        self.assertIsNotNone(r.data["work"]["upload_id"])

    @patch("apps.economy.gemini.requests.post")
    def test_a_model_that_refuses_the_shape_is_asked_again_without_it(self, post):
        post.side_effect = [nothing(), picture()]
        r = self.c.post(URL, {"kind": "wallpaper_phone", "prompt": "rain"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(post.call_count, 2)
        self.assertNotIn("imageConfig", post.call_args.kwargs["json"]["generationConfig"])

    @patch("apps.economy.gemini.requests.post")
    def test_words_only_ride_on_kinds_that_take_them(self, post):
        post.return_value = picture()
        self.c.post(URL, {"kind": "wallpaper_desktop", "prompt": "hills", "text": "BUY NOW"}, format="json")
        text = post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
        self.assertNotIn("BUY NOW", text)
        self.assertIn("No words", text)

    @patch("apps.economy.gemini.requests.post")
    def test_a_likeness_needs_a_kind_about_you_and_a_confirmation(self, post):
        post.return_value = picture()
        r = self.c.post(URL, {"kind": "logo", "reference_mode": "me", "reference": SELFIE, "confirm_self": "true"},
                        format="json")
        self.assertEqual(r.status_code, 400)
        r = self.c.post(URL, {"kind": "profile_pic", "reference_mode": "me", "reference": SELFIE}, format="json")
        self.assertEqual(r.status_code, 400)
        post.assert_not_called()
        r = self.c.post(URL, {"kind": "profile_pic", "reference_mode": "me", "reference": SELFIE,
                              "confirm_self": "true"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        text = post.call_args.kwargs["json"]["contents"][0]["parts"][1]["text"]
        self.assertIn("their own likeness", text)
        self.assertNotIn("INSPIRATION ONLY", text)

    def test_nothing_to_go_on_is_refused(self):
        self.assertEqual(self.c.post(URL, {}, format="json").status_code, 400)

    def test_unknown_options_become_blank(self):
        self.assertEqual(imagez.clean_options({"kind": "x", "style": "y", "mood": "z"})[:3], ("", "", ""))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class FaceLikenessTests(TestCase):
    def setUp(self):
        import base64
        from django.core.files.base import ContentFile
        from apps.economy.models import Face
        k = patch("apps.economy.gemini._key", return_value="k"); k.start(); self.addCleanup(k.stop)
        User = get_user_model()
        self.u = User.objects.create_user("painter", "p@e.com", "pw-Long-enough-1")
        self.friend = User.objects.create_user("friend", "f@e.com", "pw-Long-enough-1")
        w = wallet_for(self.u); w.money_cents = 1000; w.promptz = 100; w.save()
        self.c = APIClient(); self.c.force_authenticate(self.u)
        self.mine = Face(owner=self.u, name="me"); self.mine.image.save("me.png", ContentFile(base64.b64decode(PNG)))
        self.theirs = Face(owner=self.u, name="pal", tagged=self.friend)
        self.theirs.image.save("pal.png", ContentFile(base64.b64decode(PNG)))

    def test_only_untagged_own_faces_are_offered(self):
        ids = [f["id"] for f in self.c.get(URL).data["faces"]]
        self.assertEqual(ids, [self.mine.id])

    @patch("apps.economy.gemini.requests.post")
    def test_a_saved_face_becomes_the_likeness(self, post):
        post.return_value = picture()
        r = self.c.post(URL, {"kind": "promo", "reference_mode": "me", "face_id": self.mine.id,
                              "confirm_self": "true"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        parts = post.call_args.kwargs["json"]["contents"][0]["parts"]
        self.assertEqual(parts[0]["inlineData"]["mimeType"], "image/png")
        self.assertIn("their own likeness", parts[1]["text"])

    @patch("apps.economy.gemini.requests.post")
    def test_a_face_tagged_as_somebody_else_is_refused(self, post):
        r = self.c.post(URL, {"kind": "promo", "reference_mode": "me", "face_id": self.theirs.id,
                              "confirm_self": "true"}, format="json")
        self.assertEqual(r.status_code, 400)
        post.assert_not_called()
