"""Which scanner answers, and the setting that meant none of them ever did.

The bug this file exists for: `SAFE_BROWSING_API_KEY` was read with a
`getattr(settings, ..., "")` default and never defined in `settings.py`, so the
lookup returned "" on every deploy however the dashboard was configured. Every
member link went unscanned, silently, and there was nothing to notice — an
unscanned link and a clean one both come back safe.

So the first test here is that the setting EXISTS. It is the least interesting
assertion in the suite and it is the one that would have caught it.
"""
import json
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from apps.economy import links


class _Resp:
    """A stand-in for what urlopen's context manager yields."""

    def __init__(self, body):
        self._body = json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen(body):
    return patch.object(links.urllib.request, "urlopen", return_value=_Resp(body))


class TheSettingsExistTests(SimpleTestCase):
    def test_both_keys_are_real_settings_read_from_the_environment(self):
        # Not `assertTrue(getattr(...))` — the point is that the NAME resolves.
        # A getattr default hid the absence of exactly these two for the whole
        # life of the scan.
        self.assertIsNotNone(getattr(settings, "WEB_RISK_API_KEY", None))
        self.assertIsNotNone(getattr(settings, "SAFE_BROWSING_API_KEY", None))


@override_settings(WEB_RISK_API_KEY="", SAFE_BROWSING_API_KEY="")
class NoScannerTests(SimpleTestCase):
    def test_no_key_means_no_scanner_and_no_network_call(self):
        self.assertEqual(links.scanner(), "")
        self.assertFalse(links.scan_available())
        with patch.object(links.urllib.request, "urlopen") as u:
            self.assertEqual(links.safe_browsing_check("https://example.com"), (True, ""))
        u.assert_not_called()

    def test_whitespace_is_not_a_key(self):
        # A pasted-with-a-newline key in a dashboard is the classic way to
        # believe scanning is on when it is off.
        with override_settings(WEB_RISK_API_KEY="   "):
            self.assertFalse(links.scan_available())


@override_settings(WEB_RISK_API_KEY="wr-key", SAFE_BROWSING_API_KEY="sb-key")
class WebRiskWinsTests(SimpleTestCase):
    """Web Risk is the licensed product here, so it answers when it is set."""

    def test_web_risk_is_chosen_over_safe_browsing(self):
        self.assertEqual(links.scanner(), "webrisk")

    def test_a_clean_url_comes_back_clean(self):
        with _urlopen({}) as u:
            self.assertEqual(links.safe_browsing_check("https://example.com"), (True, ""))
        called = u.call_args[0][0].full_url
        self.assertIn("webrisk.googleapis.com", called)
        self.assertIn("uri=https", called)
        self.assertIn("threatTypes=MALWARE", called)

    def test_a_flagged_url_names_the_threat(self):
        with _urlopen({"threat": {"threatTypes": ["SOCIAL_ENGINEERING"]}}):
            self.assertEqual(links.safe_browsing_check("https://bad.example"),
                             (False, "SOCIAL_ENGINEERING"))

    def test_it_is_a_GET_with_no_body(self):
        # uris:search is a GET. Posting a v4-shaped body to it is a 400, and a
        # 400 comes back from this function as "safe" — which is how a broken
        # scanner turns into a silently unscanned platform.
        with _urlopen({}) as u:
            links.safe_browsing_check("https://example.com")
        self.assertIsNone(u.call_args[0][0].data)


@override_settings(WEB_RISK_API_KEY="", SAFE_BROWSING_API_KEY="sb-key")
class SafeBrowsingFallbackTests(SimpleTestCase):
    """Still supported: a non-commercial deployment of this code may use v4."""

    def test_safe_browsing_answers_when_it_is_the_only_key(self):
        self.assertEqual(links.scanner(), "safebrowsing")
        with _urlopen({}) as u:
            self.assertEqual(links.safe_browsing_check("https://example.com"), (True, ""))
        self.assertIn("safebrowsing.googleapis.com", u.call_args[0][0].full_url)

    def test_a_match_is_a_threat(self):
        with _urlopen({"matches": [{"threatType": "MALWARE"}]}):
            self.assertEqual(links.safe_browsing_check("https://bad.example"),
                             (False, "MALWARE"))

    def test_v4_still_asks_for_the_android_verdict_web_risk_does_not_have(self):
        with _urlopen({}) as u:
            links.safe_browsing_check("https://example.com")
        body = json.loads(u.call_args[0][0].data.decode())
        self.assertIn("POTENTIALLY_HARMFUL_APPLICATION", body["threatInfo"]["threatTypes"])
        self.assertNotIn("POTENTIALLY_HARMFUL_APPLICATION", links.THREAT_TYPES)


@override_settings(WEB_RISK_API_KEY="wr-key")
class OutageTests(SimpleTestCase):
    """Our outage is never the member's problem — but it is never a clearance."""

    def test_a_failed_scan_reads_as_safe_rather_than_blocking_a_click(self):
        for boom in (links.urllib.error.URLError("down"), TimeoutError(), OSError()):
            with patch.object(links.urllib.request, "urlopen", side_effect=boom):
                self.assertEqual(links.safe_browsing_check("https://example.com"), (True, ""))

    def test_but_a_failed_scan_is_not_recorded_as_a_scan(self):
        # `safe_browsing_check` returning True is not the same fact as "we
        # looked" — which is why WidgetZ asks `scan_available()` and the
        # `scanned` column instead of reading a verdict as a permission.
        # Callers that conflate the two are the bug this separation prevents.
        with patch.object(links.urllib.request, "urlopen",
                          side_effect=links.urllib.error.URLError("down")):
            safe, threat = links.safe_browsing_check("https://example.com")
        self.assertTrue(safe)
        self.assertEqual(threat, "")
        self.assertTrue(links.scan_available(), "a key is still configured")
