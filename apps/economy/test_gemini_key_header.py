"""The Gemini API key travels in a header, never in the URL.

`requests` copies the request line into the message of the exceptions it raises,
so a key in `?key=` ends up in logs and in any response that echoes the
exception. Every call that talks to Google on the shared path is pinned here.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from . import gemini, gemini_files

KEY = "AIzaSyTESTKEY-0123456789"


def _ok(payload=None):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = payload or {}
    r.text = "{}"
    r.headers = {"x-goog-upload-url": "https://upload.example/session"}
    return r


@override_settings(GEMINI_API_KEY=KEY)
class KeyIsAHeaderTests(SimpleTestCase):
    def _no_key_in_url(self, call):
        args, kwargs = call.args, call.kwargs
        url = args[0] if args else kwargs.get("url", "")
        self.assertNotIn("key=", url)
        self.assertNotIn("key", (kwargs.get("params") or {}))
        self.assertEqual((kwargs.get("headers") or {}).get("x-goog-api-key"), KEY)

    def test_generate_content(self):
        with patch.object(gemini, "model_chain", return_value=["gemini-2.5-flash"]), \
                patch("apps.economy.gemini.requests.post", return_value=_ok()) as post:
            gemini.generate_content("text", {"contents": []}, key=KEY, timeout=5)
        self._no_key_in_url(post.call_args)

    def test_model_catalogue_lookup(self):
        gemini._catalogue = None
        try:
            with patch("apps.economy.gemini.requests.get", return_value=_ok({"models": []})) as get:
                gemini._catalogue_for("text", KEY)
            self._no_key_in_url(get.call_args)
        finally:
            gemini._catalogue = None

    def test_files_api_start_status_and_delete(self):
        with patch("apps.economy.gemini_files.requests.post", return_value=_ok()) as post:
            gemini_files.upload(MagicMock(), "audio/mpeg", 10, "take")
        self._no_key_in_url(post.call_args_list[0])
        with patch("apps.economy.gemini_files.requests.get", return_value=_ok({"state": "ACTIVE"})) as get:
            gemini_files.wait_active({"name": "files/abc", "state": "PROCESSING"})
        self._no_key_in_url(get.call_args)
        with patch("apps.economy.gemini_files.requests.delete") as delete:
            gemini_files.delete({"name": "files/abc"})
        self._no_key_in_url(delete.call_args)
