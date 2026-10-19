"""Image ConnectZ's Gemini call must not put the API key where an exception can
carry it to the member.

`requests` names the full URL in every ConnectionError it raises, and the view
used to answer `f"Gemini error: {exc}"` — with the key in the query string, so a
dropped connection printed part of GEMINI_API_KEY on the member's screen.
"""
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.economy.models import GeneratedImage, Transaction, wallet_for

URL = "/api/economy/gemini/image/"
KEY = "AIzaSyTHE-SECRET-KEY-0123456789"


def conn_error():
    # The shape urllib3 gives: the whole request path, query string included.
    return requests.ConnectionError(
        f"HTTPSConnectionPool(host='generativelanguage.googleapis.com', port=443): Max retries exceeded "
        f"with url: /v1beta/models/m:generateContent?key={KEY} (Caused by NewConnectionError)")


@patch("apps.economy.gemini._key", return_value=KEY)
class ImageKeyTests(TestCase):
    def setUp(self):
        self.u = get_user_model().objects.create_user("painter", "p@e.com", "pw-Long-enough-1")
        w = wallet_for(self.u); w.money_cents = 1000; w.promptz = 100; w.save()
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def test_a_connection_error_never_puts_the_key_in_the_response(self, _):
        with patch("apps.economy.gemini.requests.post", side_effect=conn_error()):
            r = self.c.post(URL, {"prompt": "a neon cat"}, format="json")
        body = r.content.decode()
        self.assertEqual(r.status_code, 503)
        self.assertNotIn(KEY, body)
        self.assertNotIn("key=", body)
        self.assertNotIn("googleapis", body)
        self.assertEqual(r.json()["detail"], "The image service didn't answer — nothing was charged.")
        self.assertIsNone(r.json()["image"])

    def test_the_failure_is_logged_for_us_and_not_billed(self, _):
        before = Transaction.objects.count()
        w0 = wallet_for(self.u)
        with patch("apps.economy.gemini.requests.post", side_effect=conn_error()), \
                self.assertLogs("apps.economy.gemini", level="ERROR") as logs:
            self.c.post(URL, {"prompt": "a neon cat"}, format="json")
        self.assertTrue(any("Image ConnectZ" in line for line in logs.output))
        self.assertEqual(Transaction.objects.count(), before)
        w1 = wallet_for(self.u)
        self.assertEqual((w1.money_cents, w1.promptz), (w0.money_cents, w0.promptz))

    def test_the_key_goes_in_a_header_and_not_the_url(self, _):
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "image/png", "data": "QUJD"}}]}}]}
        with patch("apps.economy.gemini.requests.post", return_value=ok) as post:
            r = self.c.post(URL, {"prompt": "a neon cat"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertNotIn("key=", post.call_args.args[0])
        self.assertNotIn(KEY, post.call_args.args[0])
        self.assertNotIn("params", post.call_args.kwargs)
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], KEY)
        self.assertTrue(r.json()["image"].startswith("data:image/png;base64,"))

    def test_an_unreadable_reply_is_the_same_fixed_sentence(self, _):
        bad = MagicMock(status_code=200)
        bad.json.side_effect = ValueError(f"bad json from ...?key={KEY}")
        with patch("apps.economy.gemini.requests.post", return_value=bad):
            r = self.c.post(URL, {"prompt": "x"}, format="json")
        self.assertNotIn(KEY, r.content.decode())
        self.assertEqual(r.status_code, 503)

    def test_a_generated_image_is_kept_not_just_handed_back(self, _):
        # Corey's rule: a PromptZ spend leaves something tangible. Before
        # this, a billed image was a base64 string and nothing else — gone
        # the moment the tab closed unless the member saved it themselves.
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "image/png", "data": "QUJD"}}]}}]}
        before = GeneratedImage.objects.count()
        with patch("apps.economy.gemini.requests.post", return_value=ok):
            r = self.c.post(URL, {"prompt": "a neon cat"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(GeneratedImage.objects.count(), before + 1)
        work = r.json()["work"]
        self.assertIsNotNone(work)
        self.assertEqual(work["prompt"], "a neon cat")
        self.assertTrue(work["url"])

    def test_past_images_are_reopenable(self, _):
        ok = MagicMock(status_code=200)
        ok.json.return_value = {"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "image/png", "data": "QUJD"}}]}}]}
        with patch("apps.economy.gemini.requests.post", return_value=ok):
            self.c.post(URL, {"prompt": "a neon cat"}, format="json")
        r = self.c.get(URL)
        self.assertEqual(r.status_code, 200)
        images = r.json()["images"]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["prompt"], "a neon cat")

    def test_only_your_own_images_come_back(self, _):
        other = get_user_model().objects.create_user("other", "o@e.com", "pw-Long-enough-1")
        from apps.economy.models import Upload
        up = Upload.objects.create(user=other, name="x.png", content_type="image/png")
        GeneratedImage.objects.create(user=other, prompt="secret", upload=up)
        r = self.c.get(URL)
        self.assertEqual(r.json()["images"], [])

    def test_the_providers_own_error_text_is_not_forwarded(self, _):
        refused = MagicMock(status_code=429)
        refused.json.return_value = {"error": {"message": "Quota exceeded for project 123456789012"}}
        with patch("apps.economy.gemini.requests.post", return_value=refused):
            r = self.c.post(URL, {"prompt": "x"}, format="json")
        body = r.content.decode()
        self.assertNotIn("123456789012", body)
        self.assertNotIn("Quota", body)
        self.assertEqual(r.status_code, 503)
        self.assertIn("nothing was charged", r.json()["detail"].lower())
