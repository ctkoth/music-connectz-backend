"""Big takes reach the model by reference, not by being squeezed into a request.

The coach's ceiling was 14MB because the take was base64'd into the
`generateContent` body and that whole request caps at 20MB. A 29MB track posted
on this platform could not be coached on this platform.

Google's Files API takes 2GB a file, free, and generateContent reads it by URI.
So the transport stopped deciding what can be coached — and these pin the
switch, because the live API cannot be reached from CI and a protocol mistake
would otherwise only show up in front of a member.

The property that matters most is the LAST class: nothing here is allowed to
make a small take behave differently than it did before.
"""
from unittest.mock import Mock, patch

from django.test import TestCase

from apps.economy import gemini_files
from apps.economy.vocalcoach import INLINE_MAX_MB, MAX_MB, _media_part, _size_of


def a_file(size):
    """A stand-in take of `size` bytes that behaves like a real file object."""
    import io
    return io.BytesIO(b"0" * size)


def upload_ok(uri="files/abc123-uri", name="files/abc123", state="ACTIVE"):
    start = Mock(status_code=200, headers={"X-Goog-Upload-URL": "https://upload.example/one-time"})
    done = Mock(status_code=200)
    done.json.return_value = {"file": {"uri": uri, "name": name, "state": state}}
    return start, done


class WhichPathATakeTakesTests(TestCase):

    def test_a_small_take_still_goes_inline(self):
        """Untouched: one round trip, nothing to clean up, and the path with a
        year of production behind it."""
        part, cleanup, why = _media_part(a_file(1024), "audio/mpeg", 1024)
        self.assertIsNone(why)
        self.assertIn("inline_data", part)
        self.assertIsNone(cleanup, "an inline take has nothing to tidy afterwards")

    def test_a_take_at_the_inline_ceiling_is_still_inline(self):
        n = INLINE_MAX_MB * 1024 * 1024
        part, _c, why = _media_part(a_file(n), "audio/mpeg", n)
        self.assertIsNone(why)
        self.assertIn("inline_data", part)

    def test_one_byte_over_and_it_is_uploaded_instead(self):
        n = INLINE_MAX_MB * 1024 * 1024 + 1
        start, done = upload_ok()
        with patch.object(gemini_files.requests, "post", side_effect=[start, done]), \
             patch.object(gemini_files, "_key", return_value="k"):
            part, cleanup, why = _media_part(a_file(n), "audio/mpeg", n)
        self.assertIsNone(why)
        self.assertEqual(part["file_data"]["file_uri"], "files/abc123-uri")
        self.assertEqual(part["file_data"]["mime_type"], "audio/mpeg")
        self.assertIsNotNone(cleanup, "an uploaded take is ours to delete")

    def test_the_29mb_track_that_started_this(self):
        n = 29 * 1024 * 1024
        start, done = upload_ok()
        with patch.object(gemini_files.requests, "post", side_effect=[start, done]), \
             patch.object(gemini_files, "_key", return_value="k"):
            part, _c, why = _media_part(a_file(n), "audio/mpeg", n)
        self.assertIsNone(why, "29MB is what a real track weighs")
        self.assertIn("file_data", part)


class TheUploadProtocolTests(TestCase):

    def test_the_size_and_type_are_declared_before_the_bytes_are_sent(self):
        """Resumable in two legs: the first declares what's coming and answers
        with a one-time URL, the second sends it there."""
        start, done = upload_ok()
        with patch.object(gemini_files.requests, "post", side_effect=[start, done]) as post, \
             patch.object(gemini_files, "_key", return_value="k"):
            f, err = gemini_files.upload(a_file(99), "video/mp4", 99, "take")
        self.assertIsNone(err)
        first = post.call_args_list[0]
        self.assertIn("/upload/v1beta/files", first.args[0])
        h = first.kwargs["headers"]
        self.assertEqual(h["X-Goog-Upload-Protocol"], "resumable")
        self.assertEqual(h["X-Goog-Upload-Command"], "start")
        self.assertEqual(h["X-Goog-Upload-Header-Content-Length"], "99")
        self.assertEqual(h["X-Goog-Upload-Header-Content-Type"], "video/mp4")

        second = post.call_args_list[1]
        self.assertEqual(second.args[0], "https://upload.example/one-time",
                         "the bytes go to the one-time URL, not back to the endpoint")
        self.assertEqual(second.kwargs["headers"]["X-Goog-Upload-Command"], "upload, finalize")
        self.assertEqual(second.kwargs["headers"]["X-Goog-Upload-Offset"], "0")
        self.assertEqual(f["uri"], "files/abc123-uri")

    def test_a_start_with_no_upload_url_is_an_error_not_a_crash(self):
        start = Mock(status_code=200, headers={})
        with patch.object(gemini_files.requests, "post", return_value=start), \
             patch.object(gemini_files, "_key", return_value="k"):
            f, err = gemini_files.upload(a_file(9), "audio/mpeg", 9)
        self.assertIsNone(f)
        self.assertIn("didn't say where to send it", err)

    def test_a_refused_upload_is_an_error_not_a_crash(self):
        start, _ = upload_ok()
        bad = Mock(status_code=400, text="nope")
        with patch.object(gemini_files.requests, "post", side_effect=[start, bad]), \
             patch.object(gemini_files, "_key", return_value="k"):
            f, err = gemini_files.upload(a_file(9), "audio/mpeg", 9)
        self.assertIsNone(f)
        self.assertTrue(err)

    def test_an_unreachable_file_store_is_an_error_not_a_crash(self):
        import requests as rq
        with patch.object(gemini_files.requests, "post", side_effect=rq.RequestException("x")), \
             patch.object(gemini_files, "_key", return_value="k"):
            f, err = gemini_files.upload(a_file(9), "audio/mpeg", 9)
        self.assertIsNone(f)
        self.assertIn("couldn't reach", err)


class VideoIsNotReadableTheInstantItLandsTests(TestCase):
    """Video is transcoded after upload. Referencing it too early fails the
    generate call, so the upload waits for it — and bounds the wait, because a
    member is sitting in front of this."""

    def test_an_active_file_needs_no_polling_at_all(self):
        with patch.object(gemini_files.requests, "get") as get:
            ok, why = gemini_files.wait_active({"name": "files/x", "state": "ACTIVE"})
        self.assertTrue(ok)
        self.assertIsNone(why)
        get.assert_not_called()

    def test_it_waits_for_processing_to_finish(self):
        processing = Mock(status_code=200)
        processing.json.return_value = {"state": "PROCESSING"}
        active = Mock(status_code=200)
        active.json.return_value = {"state": "ACTIVE"}
        with patch.object(gemini_files.requests, "get", side_effect=[processing, active]), \
             patch.object(gemini_files, "_key", return_value="k"), \
             patch.object(gemini_files.time, "sleep"):
            ok, why = gemini_files.wait_active({"name": "files/x", "state": "PROCESSING"})
        self.assertTrue(ok)

    def test_a_failed_file_gives_up_immediately_rather_than_polling_out(self):
        failed = Mock(status_code=200)
        failed.json.return_value = {"state": "FAILED"}
        with patch.object(gemini_files.requests, "get", return_value=failed), \
             patch.object(gemini_files, "_key", return_value="k"), \
             patch.object(gemini_files.time, "sleep"):
            ok, why = gemini_files.wait_active({"name": "files/x", "state": "PROCESSING"})
        self.assertFalse(ok)
        self.assertIn("couldn't process", why)

    def test_a_file_that_never_becomes_ready_says_what_to_do(self):
        stuck = Mock(status_code=200)
        stuck.json.return_value = {"state": "PROCESSING"}
        with patch.object(gemini_files.requests, "get", return_value=stuck), \
             patch.object(gemini_files, "_key", return_value="k"), \
             patch.object(gemini_files.time, "sleep"):
            ok, why = gemini_files.wait_active({"name": "files/x", "state": "PROCESSING"})
        self.assertFalse(ok)
        self.assertIn("shorter section", why)

    def test_a_take_that_never_processes_is_deleted_rather_than_left_behind(self):
        n = INLINE_MAX_MB * 1024 * 1024 + 1
        start, done = upload_ok(state="PROCESSING")
        with patch.object(gemini_files.requests, "post", side_effect=[start, done]), \
             patch.object(gemini_files, "_key", return_value="k"), \
             patch.object(gemini_files, "wait_active", return_value=(False, "too slow")), \
             patch.object(gemini_files, "delete") as delete:
            part, cleanup, why = _media_part(a_file(n), "video/mp4", n)
        self.assertIsNone(part)
        self.assertEqual(why, "too slow")
        delete.assert_called_once()


class NothingAboutSmallTakesChangedTests(TestCase):
    """The property that makes this shippable without touching the live API.

    This module is new and cannot be exercised against Google from CI. So the
    switch is built to leave the old path exactly as it was: if every line of
    the Files API code is wrong, a take that used to work still works.
    """

    def test_the_inline_part_is_byte_for_byte_what_it_always_was(self):
        import base64
        raw = b"a real little take"
        import io
        part, _c, _w = _media_part(io.BytesIO(raw), "audio/mpeg", len(raw))
        self.assertEqual(part["inline_data"]["mime_type"], "audio/mpeg")
        self.assertEqual(part["inline_data"]["data"], base64.b64encode(raw).decode())

    def test_a_small_take_never_touches_the_file_store(self):
        with patch.object(gemini_files.requests, "post") as post:
            _media_part(a_file(500), "audio/mpeg", 500)
        post.assert_not_called()

    def test_the_size_is_read_without_asking_storage(self):
        """`FieldFile.size` is a storage call that raises on a missing file —
        the 500 that reached a member. Seeking asks the stream itself."""
        f = a_file(4242)
        self.assertEqual(_size_of(f), 4242)
        self.assertEqual(f.tell(), 0, "and it leaves the take where it found it")

    def test_the_advertised_ceiling_actually_rose(self):
        self.assertGreater(MAX_MB, 14, "this whole change is that 14 is gone")
