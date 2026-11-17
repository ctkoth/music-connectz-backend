import base64
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

PIC = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 20).decode()
URL = "/api/economy/gemini/image/"


class ImageEditTests(TestCase):
    def setUp(self):
        self.c = APIClient()
        self.c.force_authenticate(get_user_model().objects.create_user("ed", password="pw12345!x"))

    def test_an_edit_needs_words_a_picture_and_the_rights(self):
        with patch("apps.economy.gemini._key", return_value="k"):
            self.assertEqual(self.c.post(URL, {"edit": 1, "reference": PIC, "confirm_own": 1}, format="json").status_code, 400)
            self.assertEqual(self.c.post(URL, {"edit": 1, "prompt": "add a hat", "confirm_own": 1}, format="json").status_code, 400)
            r = self.c.post(URL, {"edit": 1, "prompt": "add a hat", "reference": PIC}, format="json")
            self.assertEqual(r.status_code, 400)
            self.assertIn("yours", r.data["detail"])
            r = self.c.post(URL, {"edit": 1, "prompt": "x", "reference": PIC, "reference2": "data:text/html;base64,PGI+", "confirm_own": 1}, format="json")
            self.assertEqual(r.status_code, 400)

    @patch("apps.economy.gemini.can_afford_ai", return_value=True)
    @patch("apps.economy.gemini._bill", return_value=0)
    @patch("apps.economy.gemini._key", return_value="k")
    @patch("apps.economy.gemini.requests.post")
    def test_the_picture_goes_first_and_the_request_says_edit(self, post, _k, _b, _a):
        out = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
        post.return_value = MagicMock(status_code=200, json=lambda: {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": out}}]}}]})
        r = self.c.post(URL, {"edit": 1, "prompt": "make the sky purple", "reference": PIC, "reference2": PIC, "confirm_own": 1}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        parts = post.call_args.kwargs["json"]["contents"][0]["parts"]
        self.assertIn("inlineData", parts[0])
        self.assertIn("inlineData", parts[1])
        self.assertIn("Edit the FIRST attached image", parts[2]["text"])
        self.assertIn("make the sky purple", parts[2]["text"])
        self.assertIn("SECOND attached image", parts[2]["text"])
        self.assertEqual(len(parts), 3)
        self.assertNotIn("imageConfig", post.call_args.kwargs["json"]["generationConfig"])
