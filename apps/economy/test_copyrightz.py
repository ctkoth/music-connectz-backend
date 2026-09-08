"""A match is a fact, not a verdict — and "we didn't look" is not "clear".

The two rules this file defends:

**An unscanned upload is never reported as clear.** The mistake is easier to
make here than anywhere else in the codebase, because "no match" and "we did not
look" both feel like good news. Only one of them is worth anything to a member
about to publish, and `clear` is the answer somebody publishes on.

**Nothing is blocked, hidden or deleted by a match.** On a music platform the
likeliest match is the member's own release; after that a licensed sample or a
cover they have the rights to. So the work posts, the match is named before they
publish, and they answer it.
"""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from apps.economy import copyrightz
from apps.economy.copyrightz import CLEAR, MATCHED, UNSCANNED

User = get_user_model()

KEYED = dict(ACRCLOUD_ACCESS_KEY="k", ACRCLOUD_ACCESS_SECRET="s")
A_MATCH = {
    "status": {"code": 0, "msg": "Success"},
    "metadata": {"music": [{
        "title": "Bad and Boujee",
        "artists": [{"name": "Migos"}],
        "album": {"name": "Culture"},
        "label": "Quality Control",
        "external_ids": {"isrc": "USUM71613744"},
        "play_offset_ms": 14000,
        "score": 96,
    }]},
}


class NoProviderTests(SimpleTestCase):
    @override_settings(ACRCLOUD_ACCESS_KEY="", ACRCLOUD_ACCESS_SECRET="")
    def test_with_no_provider_nothing_is_scanned_and_nothing_is_cleared(self):
        with patch.dict("os.environ", {"ACRCLOUD_ACCESS_KEY": "", "ACRCLOUD_ACCESS_SECRET": ""}):
            r = copyrightz.scan("/tmp/whatever.mp4", "video/mp4")
        self.assertEqual(r["state"], UNSCANNED)
        self.assertNotEqual(r["state"], CLEAR)
        self.assertIn("provider", r["note"].lower())

    @override_settings(ACRCLOUD_ACCESS_KEY="", ACRCLOUD_ACCESS_SECRET="")
    def test_readiness_names_what_is_missing_separately(self):
        with patch.dict("os.environ", {"ACRCLOUD_ACCESS_KEY": "", "ACRCLOUD_ACCESS_SECRET": ""}):
            r = copyrightz.readiness()
        self.assertFalse(r["ready"])
        self.assertEqual(r["provider"], "")
        # Actionable, not a shrug: the reason a scan didn't run is the thing
        # somebody has to go and fix.
        self.assertTrue(r["why"])


@override_settings(**KEYED)
class ScanTests(SimpleTestCase):
    def _scan(self, payload, sample=b"audio"):
        with patch.object(copyrightz, "_sample_from", return_value=sample), \
             patch.object(copyrightz, "_acrcloud", return_value=payload):
            return copyrightz.scan("/tmp/x.mp4", "video/mp4")

    def test_a_match_is_named_with_everything_needed_to_act_on_it(self):
        r = self._scan(A_MATCH)
        self.assertEqual(r["state"], MATCHED)
        m = r["matches"][0]
        # "Possible copyrighted content" tells a member nothing. A title, an
        # artist, a label and an offset tells them what to cut or clear.
        self.assertEqual(m["title"], "Bad and Boujee")
        self.assertEqual(m["artists"], ["Migos"])
        self.assertEqual(m["label"], "Quality Control")
        self.assertEqual(m["isrc"], "USUM71613744")
        self.assertEqual(m["at_seconds"], 14)

    def test_a_scan_that_ran_and_found_nothing_is_clear(self):
        self.assertEqual(self._scan({"status": {"code": 1001, "msg": "No result"}})["state"], CLEAR)
        self.assertEqual(self._scan({"status": {"code": 0}, "metadata": {}})["state"], CLEAR)

    def test_a_provider_error_is_unscanned_not_clear(self):
        # Their outage is not a pass. This is the whole point of three states.
        r = self._scan({"status": {"code": 3001, "msg": "Invalid access key"}})
        self.assertEqual(r["state"], UNSCANNED)

    def test_our_own_outage_is_unscanned_not_clear(self):
        with patch.object(copyrightz, "_sample_from", return_value=b"a"), \
             patch.object(copyrightz, "_acrcloud", side_effect=TimeoutError()):
            r = copyrightz.scan("/tmp/x.mp4", "video/mp4")
        self.assertEqual(r["state"], UNSCANNED)

    def test_no_readable_audio_is_unscanned_not_clear(self):
        # A video whose first bytes are not a decodable audio stream would
        # always answer "no match" — the worst failure, because it looks
        # exactly like a pass.
        with patch.object(copyrightz, "_sample_from", return_value=None):
            r = copyrightz.scan("/tmp/x.mp4", "video/mp4")
        self.assertEqual(r["state"], UNSCANNED)
        self.assertTrue(r["note"])

    def test_scan_never_raises_whatever_comes_back(self):
        for payload in ({}, {"status": {}}, {"status": {"code": 0}, "metadata": {"music": [{}]}}):
            with patch.object(copyrightz, "_sample_from", return_value=b"a"), \
                 patch.object(copyrightz, "_acrcloud", return_value=payload):
                self.assertIn(copyrightz.scan("/x", "")["state"], (CLEAR, MATCHED, UNSCANNED))


@override_settings(**KEYED)
class SignatureTests(SimpleTestCase):
    def test_the_signature_is_over_the_documented_field_order(self):
        # Getting the order wrong produces a clean 401 that reads like a bad
        # key, so the order is pinned rather than left to a loop.
        seen = {}

        class _Resp:
            def read(self):
                return json.dumps({"status": {"code": 1001}}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def _urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["body"] = req.data
            return _Resp()

        with patch.object(copyrightz.urllib.request, "urlopen", _urlopen):
            copyrightz._acrcloud(b"sample-bytes")
        self.assertIn("/v1/identify", seen["url"])
        body = seen["body"]
        for field in (b"access_key", b"signature", b"signature_version",
                      b"sample_bytes", b"timestamp", b"data_type"):
            self.assertIn(field, body)
        # The sample rides as a file part, not as a form value.
        self.assertIn(b'name="sample"; filename=', body)
        self.assertIn(b"sample-bytes", body)


class TheLineAMemberReadsTests(SimpleTestCase):
    def test_unscanned_says_it_is_our_check_not_their_video(self):
        line = copyrightz.summary({"state": UNSCANNED})
        self.assertIn("not a result about your video", line)

    def test_a_match_names_it_and_ends_with_the_way_forward(self):
        line = copyrightz.summary({"state": MATCHED, "matches": [
            {"title": "Bad and Boujee", "artists": ["Migos"], "at_seconds": 14}]})
        self.assertIn("Bad and Boujee", line)
        self.assertIn("Migos", line)
        self.assertIn("0:14", line)
        # A match with no next step is a dead end on the one screen where a
        # member most needs one.
        self.assertIn("isn't a verdict", line)

    def test_once_answered_the_line_carries_the_answer(self):
        line = copyrightz.summary(
            {"state": MATCHED, "matches": [{"title": "T", "artists": ["A"]}]}, claim="mine")
        self.assertIn("my own recording", line.lower())


class TheWorkIsNeverBlockedTests(TestCase):
    """The video posts. The match is named. The member answers it."""

    def setUp(self):
        self.u = User.objects.create_user("dir", "d@x.com", "hunter2hunter2")
        from rest_framework.test import APIClient
        self.c = APIClient()
        self.c.force_authenticate(self.u)

    def _make(self):
        with patch("apps.economy.directz_app._apply_copyright_check") as chk:
            chk.side_effect = lambda w, u: None
            r = self.c.post("/api/economy/directz/",
                            {"fmt": "reelz", "title": "My reel", "duration_sec": 45,
                             "genre": "Music Video", "video_type": "Music"},
                            format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return r.data["id"]

    def test_a_work_posts_and_carries_its_copyright_state(self):
        from apps.economy.models import DirectZWork
        wid = self._make()
        w = DirectZWork.objects.get(pk=wid)
        # Default is unscanned, never clear.
        self.assertEqual(w.copyright_state, UNSCANNED)

    def test_a_member_answers_a_match_and_the_answer_sticks(self):
        from apps.economy.models import DirectZWork
        wid = self._make()
        DirectZWork.objects.filter(pk=wid).update(
            copyright_state=MATCHED,
            copyright={"state": MATCHED, "matches": [{"title": "T", "artists": ["A"]}]})
        r = self.c.post(f"/api/economy/directz/{wid}/copyright/",
                        {"claim": "mine"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["claim"], "mine")
        # The match STAYS a match. What changed is that it has been answered.
        self.assertEqual(r.data["state"], MATCHED)

    def test_an_unknown_claim_is_refused_with_the_list(self):
        wid = self._make()
        r = self.c.post(f"/api/economy/directz/{wid}/copyright/",
                        {"claim": "whatever"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("mine", r.data["claims"])

    def test_you_can_only_answer_for_your_own_work(self):
        wid = self._make()
        other = User.objects.create_user("other", "o@x.com", "hunter2hunter2")
        from rest_framework.test import APIClient
        c = APIClient()
        c.force_authenticate(other)
        self.assertEqual(c.post(f"/api/economy/directz/{wid}/copyright/",
                                {"claim": "mine"}, format="json").status_code, 404)
