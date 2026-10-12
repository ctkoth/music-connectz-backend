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
        # Asked first, and still not done: only then is it refunded.
        with patch("apps.economy.videoz.requests.get", return_value=resp(json={"done": False})):
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


DONE_JSON = {"done": True, "response": {"generateVideoResponse": {"generatedSamples": [
    {"video": {"uri": "https://generativelanguage.googleapis.com/v1beta/files/x:download?alt=media"}}]}}}


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), OWNER_USERNAMES=["koth"], OWNER_EMAILS=[])
@patch("apps.economy.videoz._key", return_value=KEY)
class RefundRunsOnceTests(TestCase):
    """`refund` used to guard on the CALLER'S in-memory `status`, and every GET
    reads the row fresh, so two requests holding a stale pending copy each saw
    "pending" and each paid the member back. Money minted by polling."""

    def setUp(self):
        self.owner = User.objects.create_user("koth", "o@e.com", "pw-Long-enough-1")
        self.u = User.objects.create_user("maker", "m@e.com", "pw-Long-enough-1")
        w = wallet_for(self.u); w.promptz = 150; w.money_cents = 1000; w.save()
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def start(self):
        with patch("apps.economy.videoz.requests.post", return_value=resp(json={"name": "operations/abc"})):
            self.c.post(URL, {"kind": "music", "prompt": "neon", "aspect": "9:16"}, format="json")
        return VideoWork.objects.get()

    def test_two_refunds_on_the_same_stale_instance_credit_once(self, _):
        from apps.economy.videoz import refund
        self.start()
        first, second = VideoWork.objects.get(), VideoWork.objects.get()     # both read "pending"
        refund(first, "it never finished")
        refund(second, "it never finished")
        w = wallet_for(self.u)
        self.assertEqual((w.promptz, w.money_cents), (150, 1000))            # not (300, 1250)
        self.assertEqual(VideoWork.objects.get().status, "failed")

    def test_the_refund_writes_one_ledger_row(self, _):
        from apps.economy.videoz import refund
        from apps.economy.models import Transaction
        self.start()
        first, second = VideoWork.objects.get(), VideoWork.objects.get()
        before = Transaction.objects.filter(user=self.u).count()
        refund(first, "x"); refund(second, "x")
        self.assertEqual(Transaction.objects.filter(user=self.u).count(), before + 1)

    def test_two_polls_past_the_give_up_time_refund_once(self, _):
        from apps.economy.videoz import poll
        self.start()
        VideoWork.objects.update(created_at=timezone.now() - timedelta(minutes=25))
        a, b = VideoWork.objects.get(), VideoWork.objects.get()
        # Still not done when asked — only THEN is it refunded, and once.
        with patch("apps.economy.videoz.requests.get", return_value=resp(json={"done": False})):
            poll(a); poll(b)
        w = wallet_for(self.u)
        self.assertEqual((w.promptz, w.money_cents), (150, 1000))

    def test_a_render_that_finished_while_the_member_was_away_is_delivered_not_refunded(self, _):
        """GIVE_UP_AFTER used to refund on the clock BEFORE asking the provider, so
        twenty-one minutes away lost a finished video: the member paid back for a
        render that existed, the owner unpaid, the file gone."""
        from apps.economy.videoz import poll
        self.start()
        VideoWork.objects.update(created_at=timezone.now() - timedelta(minutes=45))
        with patch("apps.economy.videoz.requests.get",
                   side_effect=[resp(json=DONE_JSON), resp(content=b"\x00\x00\x00 ftypmp4")]):
            poll(VideoWork.objects.get())
        self.assertEqual(VideoWork.objects.get().status, "done")
        w = wallet_for(self.u)
        self.assertEqual((w.promptz, w.money_cents), (0, 750))              # still spent: it was delivered
        self.assertEqual(wallet_for(self.owner).money_cents, 400)            # and paid for, once

    def test_an_unanswered_status_check_waits_instead_of_reading_as_failure(self, _):
        import requests as rq
        from apps.economy import videoz
        self.start()
        VideoWork.objects.update(created_at=timezone.now() - timedelta(minutes=45))
        with patch("apps.economy.videoz.requests.get", side_effect=rq.ConnectionError("down")):
            videoz.poll(VideoWork.objects.get())
        self.assertEqual(VideoWork.objects.get().status, "pending")          # an outage is not "never finished"
        VideoWork.objects.update(created_at=timezone.now() - videoz.HARD_GIVE_UP_AFTER - timedelta(minutes=1))
        with patch("apps.economy.videoz.requests.get", side_effect=rq.ConnectionError("down")):
            videoz.poll(VideoWork.objects.get())
        self.assertEqual(VideoWork.objects.get().status, "failed")           # but not forever
        w = wallet_for(self.u)
        self.assertEqual((w.promptz, w.money_cents), (150, 1000))

    def test_a_webp_face_is_sent_as_webp_not_jpeg(self, _):
        face = Face.objects.create(owner=self.u, image=SimpleUploadedFile(
            "f.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 ", content_type="image/webp"))
        with patch("apps.economy.videoz.requests.post", return_value=resp(json={"name": "operations/abc"})) as post:
            r = self.c.post(URL, {"kind": "music", "prompt": "neon", "aspect": "9:16", "face_id": face.id}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        sent = post.call_args.kwargs["json"]["instances"][0]["image"]
        self.assertEqual(sent["mimeType"], "image/webp")

    def test_a_refund_cannot_follow_a_delivered_video(self, _):
        """The stale copy still says pending after the video landed and was paid
        to the owner; refunding it too would pay for the same render twice."""
        from apps.economy.videoz import refund
        v = self.start()
        stale = VideoWork.objects.get()
        with patch("apps.economy.videoz.requests.get", side_effect=[resp(json=DONE_JSON), resp(content=b"\x00ftyp")]):
            self.c.get(f"{URL}{v.id}/")
        self.assertEqual(VideoWork.objects.get().status, "done")
        refund(stale, "it never finished")
        w = wallet_for(self.u)
        self.assertEqual((w.promptz, w.money_cents), (0, 750))              # still paid for, still held
        self.assertEqual(VideoWork.objects.get().status, "done")

    def test_the_stale_instance_is_updated_too(self, _):
        from apps.economy.videoz import refund
        self.start()
        w = VideoWork.objects.get()
        refund(w, "the render failed")
        self.assertEqual((w.status, w.error), ("failed", "the render failed"))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), OWNER_USERNAMES=["koth"], OWNER_EMAILS=[])
@patch("apps.economy.videoz._key", return_value=KEY)
class OnlyOneRequestFetchesTheBytesTests(TestCase):
    """Overlapping polls each saw "done" and each downloaded the whole video,
    keeping one. The row is claimed BEFORE the download now."""

    def setUp(self):
        self.owner = User.objects.create_user("koth", "o@e.com", "pw-Long-enough-1")
        self.u = User.objects.create_user("maker", "m@e.com", "pw-Long-enough-1")
        w = wallet_for(self.u); w.promptz = 150; w.money_cents = 1000; w.save()
        self.work = VideoWork.objects.create(user=self.u, kind="music", prompt="p", operation="operations/abc",
                                             held_promptz=150, held_cash=250)

    def test_an_overlapping_poll_does_not_download_again(self, _):
        from apps.economy.videoz import poll
        other = VideoWork.objects.get()
        downloads = []

        def fake_get(url, **kw):
            if "operations" in url:
                return resp(json=DONE_JSON)
            downloads.append(url)
            if len(downloads) == 1:
                poll(other)          # a second request arrives while the first is mid-download
            return resp(content=b"\x00\x00\x00 ftypmp4")

        with patch("apps.economy.videoz.requests.get", side_effect=fake_get):
            poll(VideoWork.objects.get())
        self.assertEqual(len(downloads), 1)
        self.assertEqual(VideoWork.objects.get().status, "done")
        self.assertEqual(Upload.objects.filter(user=self.u).count(), 1)
        self.assertEqual(wallet_for(self.owner).money_cents, 400)           # paid once

    def test_a_failed_download_releases_the_claim_so_the_next_poll_retries(self, _):
        import requests as rq
        from apps.economy.videoz import poll
        calls = []

        def flaky(url, **kw):
            if "operations" in url:
                return resp(json=DONE_JSON)
            calls.append(url)
            if len(calls) == 1:
                raise rq.ConnectionError("dropped")
            return resp(content=b"\x00\x00\x00 ftypmp4")

        with patch("apps.economy.videoz.requests.get", side_effect=flaky):
            poll(VideoWork.objects.get())
            self.assertEqual(VideoWork.objects.get().status, "pending")
            poll(VideoWork.objects.get())
        self.assertEqual(len(calls), 2)
        self.assertEqual(VideoWork.objects.get().status, "done")

    def test_a_claim_left_by_a_dead_request_is_taken_over(self, _):
        from apps.economy import videoz
        from apps.economy.videoz import poll
        import time as _t
        VideoWork.objects.update(error=f"{videoz.FETCH_CLAIM}{int(_t.time()) - 10_000}")
        with patch("apps.economy.videoz.requests.get", side_effect=[resp(json=DONE_JSON), resp(content=b"\x00ftyp")]):
            poll(VideoWork.objects.get())
        self.assertEqual(VideoWork.objects.get().status, "done")

    def test_a_fresh_claim_is_left_alone(self, _):
        from apps.economy import videoz
        from apps.economy.videoz import poll
        import time as _t
        VideoWork.objects.update(error=f"{videoz.FETCH_CLAIM}{int(_t.time())}")
        gets = []

        def fake_get(url, **kw):
            gets.append(url)
            return resp(json=DONE_JSON)

        with patch("apps.economy.videoz.requests.get", side_effect=fake_get):
            poll(VideoWork.objects.get())
        self.assertEqual(len(gets), 1)                                       # the status ask, no download
        self.assertEqual(VideoWork.objects.get().status, "pending")

    def test_the_claim_marker_is_never_shown_to_the_member(self, _):
        from apps.economy import videoz
        import time as _t
        VideoWork.objects.update(error=f"{videoz.FETCH_CLAIM}{int(_t.time())}")
        c = APIClient(); c.force_authenticate(self.u)
        with patch("apps.economy.videoz.requests.get", return_value=resp(json={"done": False})):
            d = c.get(f"{URL}{self.work.id}/").json()
        self.assertEqual(d["error"], "")
        self.assertEqual(c.get(URL).json()["works"][0]["error"], "")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), OWNER_USERNAMES=["koth"], OWNER_EMAILS=[])
@patch("apps.economy.videoz._key", return_value=KEY)
class StartFailureSaysWhoseFaultTests(TestCase):
    """Every start failure used to say "try rewording it", including when OUR
    key or quota was the problem — which sent the member to rewrite a
    perfectly good description."""

    def setUp(self):
        User.objects.create_user("koth", "o@e.com", "pw-Long-enough-1")
        self.u = User.objects.create_user("maker", "m@e.com", "pw-Long-enough-1")
        w = wallet_for(self.u); w.promptz = 150; w.money_cents = 1000; w.save()
        self.c = APIClient(); self.c.force_authenticate(self.u)

    def fail_with(self, code, message="x", **kw):
        with patch("apps.economy.videoz.requests.post",
                   return_value=resp(code, {"error": {"message": message}})):
            r = self.c.post(URL, {"kind": "promo", "prompt": "x", **kw}, format="json")
        w = wallet_for(self.u)
        self.assertEqual((w.promptz, w.money_cents), (150, 1000), "every failed start is refunded in full")
        self.assertEqual(VideoWork.objects.get().status, "failed")
        return r

    def test_our_key_or_quota_is_never_blamed_on_the_wording(self, _):
        for code in (429, 403, 401, 500, 503):
            VideoWork.objects.all().delete()
            r = self.fail_with(code)
            d = r.json()
            self.assertEqual(r.status_code, 502, code)
            self.assertNotIn("reword", d["detail"].lower(), code)
            self.assertIn("our end", d["detail"], code)
            self.assertIn("nothing was charged", d["detail"].lower(), code)
            self.assertEqual(d["reason"], "unavailable", code)

    def test_an_unreachable_service_is_ours_too(self, _):
        import requests as rq
        with patch("apps.economy.videoz.requests.post", side_effect=rq.ConnectionError("down")):
            r = self.c.post(URL, {"kind": "promo", "prompt": "x"}, format="json")
        d = r.json()
        self.assertEqual(d["reason"], "unavailable")
        self.assertNotIn("reword", d["detail"].lower())
        self.assertEqual(wallet_for(self.u).money_cents, 1000)

    def test_an_invalid_key_that_arrives_as_a_400_is_still_ours(self, _):
        r = self.fail_with(400, "API key not valid. Please pass a valid API key.")
        self.assertEqual(r.json()["reason"], "unavailable")
        self.assertNotIn("reword", r.json()["detail"].lower())

    def test_a_400_about_the_image_points_at_the_photo(self, _):
        r = self.fail_with(400, "Unable to process input image. Please retry or report in "
                                "https://developers.generativeai.google/guide/troubleshooting")
        d = r.json()
        self.assertEqual(d["reason"], "photo")
        self.assertIn("photo", d["detail"].lower())
        self.assertNotIn("reword", d["detail"].lower())

    def test_only_a_safety_or_prompt_refusal_says_reword(self, _):
        r = self.fail_with(400, "The prompt could not be submitted. This prompt contains sensitive words "
                                "that violate Google's Responsible AI practices.")
        d = r.json()
        self.assertEqual(d["reason"], "wording")
        self.assertIn("reword", d["detail"].lower())

    def test_an_unclassified_400_does_not_pretend_to_know(self, _):
        r = self.fail_with(400, "something odd")
        d = r.json()
        self.assertEqual(d["reason"], "unknown")
        self.assertIn("Nothing was charged", d["detail"])

    def test_the_failed_row_records_a_reason_the_screen_can_show(self, _):
        self.fail_with(429)
        err = VideoWork.objects.get().error
        self.assertTrue(err)
        self.assertNotIn("reword", err.lower())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), OWNER_USERNAMES=["koth"], OWNER_EMAILS=[])
@patch("apps.economy.videoz._key", return_value=KEY)
class WhatThePriceBuysTests(TestCase):
    def test_get_states_what_the_price_buys_before_the_button(self, _):
        u = User.objects.create_user("maker", "m@e.com", "pw-Long-enough-1")
        c = APIClient(); c.force_authenticate(u)
        d = c.get(URL).json()
        line = d["what_you_get"]
        self.assertIn(f"{d['clip_seconds']} seconds", line)
        self.assertIn("not your track", line)           # the sound is generated, never the member's music
        self.assertIn("refund", line.lower())            # and a failed render costs nothing


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(), OWNER_USERNAMES=["koth"], OWNER_EMAILS=[])
@patch("apps.economy.videoz._key", return_value=KEY)
class TheKeyStaysOutOfTheUrlTests(TestCase):
    """A key in the query string is part of every URL `requests` puts in an
    exception message, and `logger.exception` writes those to the log."""

    def test_every_call_to_the_provider_sends_the_key_as_a_header(self, _):
        User.objects.create_user("koth", "o@e.com", "pw-Long-enough-1")
        u = User.objects.create_user("maker", "m@e.com", "pw-Long-enough-1")
        w = wallet_for(u); w.promptz = 150; w.money_cents = 1000; w.save()
        c = APIClient(); c.force_authenticate(u)
        with patch("apps.economy.videoz.requests.post", return_value=resp(json={"name": "operations/abc"})) as post:
            c.post(URL, {"kind": "music", "prompt": "neon"}, format="json")
        self.assertNotIn("params", post.call_args.kwargs)
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], KEY)
        v = VideoWork.objects.get()
        with patch("apps.economy.videoz.requests.get", side_effect=[resp(json=DONE_JSON), resp(content=b"\x00ftyp")]) as get:
            c.get(f"{URL}{v.id}/")
        for call in get.call_args_list:
            self.assertNotIn("params", call.kwargs)
            self.assertEqual(call.kwargs["headers"]["x-goog-api-key"], KEY)
            self.assertNotIn(KEY, call.args[0])
