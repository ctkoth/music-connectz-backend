"""DistributeZ transcoding, on whichever machine can do it.

This endpoint has been answering 503 in production since the day it shipped:
Render's Python image has no ffmpeg, `_has_ffmpeg()` returns False up there,
and the member gets "server transcoder not enabled yet" with nowhere to go.
The feature existed only on developer laptops.

Modal is the second backend. These pin the routing between the two, and pin
that the wrong one never runs — a host with ffmpeg shouldn't be paying Modal
per second to borrow somebody else's.

Nothing here needs a Modal account. The call is patched, because a test suite
that requires a paid third party is a test suite that gets skipped.
"""
import os
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from . import transcode
from .models import Upload, membership_for

User = get_user_model()

MP3 = b"ID3\x03\x00\x00\x00" + b"\x00" * 2048


def member(name, tier="free"):
    u = User.objects.create_user(username=name, password="transcode-pass-1")
    m = membership_for(u)
    m.tier = tier
    m.save(update_fields=["tier"])
    return u


class BackendSelectionTests(TestCase):
    """Which machine runs the job, and why."""

    def test_local_ffmpeg_wins_when_it_is_there(self):
        """Free and no network hop. Modal is the fallback, not the default."""
        with mock.patch.object(transcode, "has_local_ffmpeg", return_value=True), \
                mock.patch.object(transcode, "modal_configured", return_value=True), \
                mock.patch.object(transcode, "_to_mp3_local", return_value=MP3) as local, \
                mock.patch.object(transcode, "_to_mp3_modal") as remote:
            self.assertEqual(transcode.to_mp3("http://x/v.mp4"), MP3)
        local.assert_called_once()
        remote.assert_not_called()

    def test_modal_runs_when_the_host_has_no_ffmpeg(self):
        """The production case. Without this, DistributeZ stays a 503."""
        with mock.patch.object(transcode, "has_local_ffmpeg", return_value=False), \
                mock.patch.object(transcode, "modal_configured", return_value=True), \
                mock.patch.object(transcode, "_to_mp3_modal", return_value=MP3) as remote:
            self.assertEqual(transcode.to_mp3("http://x/v.mp4"), MP3)
        remote.assert_called_once()

    def test_neither_backend_is_an_unavailable_not_a_crash(self):
        with mock.patch.object(transcode, "has_local_ffmpeg", return_value=False), \
                mock.patch.object(transcode, "modal_configured", return_value=False):
            with self.assertRaises(transcode.TranscodeUnavailable):
                transcode.to_mp3("http://x/v.mp4")

    def test_an_empty_url_is_the_members_fault_not_the_servers(self):
        with self.assertRaises(transcode.TranscodeFailed):
            transcode.to_mp3("   ")

    def test_backend_names_what_would_run(self):
        with mock.patch.object(transcode, "has_local_ffmpeg", return_value=False), \
                mock.patch.object(transcode, "modal_configured", return_value=True):
            self.assertEqual(transcode.backend(), "modal")
        with mock.patch.object(transcode, "has_local_ffmpeg", return_value=False), \
                mock.patch.object(transcode, "modal_configured", return_value=False):
            self.assertEqual(transcode.backend(), "")


class ModalConfigurationTests(TestCase):
    """Both halves of the token, checked before the member waits."""

    def test_half_a_token_is_not_configured(self):
        """An ID with no secret authenticates nothing. Finding that out inside
        a request means they waited through a download to hear no."""
        with mock.patch.dict(os.environ, {"MODAL_TOKEN_ID": "ak-1"}, clear=False):
            os.environ.pop("MODAL_TOKEN_SECRET", None)
            self.assertFalse(transcode.modal_configured())

    def test_both_halves_and_the_sdk_present_is_configured(self):
        with mock.patch.dict(os.environ, {"MODAL_TOKEN_ID": "ak-1",
                                          "MODAL_TOKEN_SECRET": "as-1"},
                             clear=False), \
                mock.patch.dict("sys.modules", {"modal": mock.MagicMock()}):
            self.assertTrue(transcode.modal_configured())

    def test_tokens_without_the_sdk_installed_is_not_configured(self):
        real_import = __import__

        def no_modal(name, *a, **kw):
            if name == "modal":
                raise ImportError("no modal")
            return real_import(name, *a, **kw)

        with mock.patch.dict(os.environ, {"MODAL_TOKEN_ID": "ak-1",
                                          "MODAL_TOKEN_SECRET": "as-1"},
                             clear=False), \
                mock.patch("builtins.__import__", side_effect=no_modal):
            self.assertFalse(transcode.modal_configured())


class ModalCallTests(TestCase):
    """Whose fault it was, translated from Modal's exceptions.

    A source with no audio track and a platform outage read identically to a
    member if you give them the same status, and only one is worth retrying.
    """

    def _modal(self, remote):
        fake = mock.MagicMock()
        fake.Function.from_name.return_value.remote = remote
        return mock.patch.dict("sys.modules", {"modal": fake})

    def test_bytes_come_straight_back(self):
        with self._modal(mock.Mock(return_value=MP3)):
            self.assertEqual(transcode._to_mp3_modal("http://x/v.mp4", "320k"), MP3)

    def test_the_url_and_bitrate_are_passed_through(self):
        remote = mock.Mock(return_value=MP3)
        with self._modal(remote):
            transcode._to_mp3_modal("http://x/v.mp4", "192k")
        remote.assert_called_once_with("http://x/v.mp4", "192k")

    def test_a_runtime_error_from_the_function_is_the_members_file(self):
        """The Modal function raises RuntimeError for a bad source — that's a
        422, not a 503."""
        with self._modal(mock.Mock(side_effect=RuntimeError("no audio track"))):
            with self.assertRaises(transcode.TranscodeFailed):
                transcode._to_mp3_modal("http://x/v.mp4", "320k")

    def test_anything_else_is_ours(self):
        with self._modal(mock.Mock(side_effect=ConnectionError("modal is down"))):
            with self.assertRaises(transcode.TranscodeUnavailable):
                transcode._to_mp3_modal("http://x/v.mp4", "320k")

    def test_an_empty_result_is_not_stored_as_a_track(self):
        """Zero bytes would otherwise become a 0-byte mp3 in their library."""
        with self._modal(mock.Mock(return_value=b"")):
            with self.assertRaises(transcode.TranscodeFailed):
                transcode._to_mp3_modal("http://x/v.mp4", "320k")

    def test_a_function_that_was_never_deployed_says_so(self):
        fake = mock.MagicMock()
        fake.Function.from_name.side_effect = Exception("not found")
        with mock.patch.dict("sys.modules", {"modal": fake}):
            with self.assertRaises(transcode.TranscodeUnavailable) as ctx:
                transcode._to_mp3_modal("http://x/v.mp4", "320k")
        self.assertIn("modal deploy", str(ctx.exception))


@override_settings(DEFAULT_FILE_STORAGE="django.core.files.storage.InMemoryStorage")
class TranscodeEndpointTests(TestCase):
    def setUp(self):
        self.u = member("transcoder")
        self.client = APIClient()
        self.client.force_authenticate(self.u)
        self.url = reverse("economy-distributez-transcode")

    def post(self, url="http://example.test/video.mp4"):
        return self.client.post(self.url, {"url": url}, format="json")

    def test_a_successful_run_stores_a_real_upload(self):
        with mock.patch.object(transcode, "available", return_value=True), \
                mock.patch.object(transcode, "to_mp3", return_value=MP3):
            r = self.post()
        self.assertEqual(r.status_code, 201, r.content)
        u = Upload.objects.get(user=self.u)
        self.assertEqual(u.content_type, "audio/mpeg")
        self.assertEqual(u.size_bytes, len(MP3))

    def test_it_says_which_backend_ran(self):
        with mock.patch.object(transcode, "available", return_value=True), \
                mock.patch.object(transcode, "to_mp3", return_value=MP3), \
                mock.patch.object(transcode, "backend", return_value="modal"):
            r = self.post()
        self.assertEqual(r.json()["backend"], "modal")

    def test_no_url_is_a_400(self):
        r = self.client.post(self.url, {}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_nowhere_to_run_it_is_a_503_with_a_route(self):
        """The old body was a bare code and a full stop. A member who can't
        transcode can still upload the audio — say so."""
        with mock.patch.object(transcode, "available", return_value=False):
            r = self.post()
        self.assertEqual(r.status_code, 503)
        body = r.json()
        self.assertIn("next", body)
        self.assertTrue(body["next"]["action"])
        self.assertEqual(body["code"], "transcode_unavailable")

    def test_a_bad_source_is_a_422(self):
        with mock.patch.object(transcode, "available", return_value=True), \
                mock.patch.object(transcode, "to_mp3",
                                  side_effect=transcode.TranscodeFailed("no audio track")):
            r = self.post()
        self.assertEqual(r.status_code, 422)
        self.assertIn("no audio track", r.json()["detail"])

    def test_a_backend_outage_is_a_503_with_a_route(self):
        with mock.patch.object(transcode, "available", return_value=True), \
                mock.patch.object(transcode, "to_mp3",
                                  side_effect=transcode.TranscodeUnavailable("Modal is down")):
            r = self.post()
        self.assertEqual(r.status_code, 503)
        self.assertIn("next", r.json())

    def test_nothing_is_stored_when_the_transcode_fails(self):
        with mock.patch.object(transcode, "available", return_value=True), \
                mock.patch.object(transcode, "to_mp3",
                                  side_effect=transcode.TranscodeFailed("nope")):
            self.post()
        self.assertEqual(Upload.objects.count(), 0)

    def test_anonymous_members_cannot_burn_compute(self):
        """Modal bills per second. An open endpoint is an open invoice."""
        c = APIClient()
        r = c.post(self.url, {"url": "http://example.test/v.mp4"}, format="json")
        self.assertIn(r.status_code, (401, 403))


@override_settings(DEFAULT_FILE_STORAGE="django.core.files.storage.InMemoryStorage")
class QuotasStillApplyTests(TestCase):
    """Moving the work to Modal must not move the limits off it.

    Quotas are checked on the RESULT, not the source: a 2GB video can carry
    three minutes of audio, and refusing on the input size turns a legal
    upload into a paywall.
    """

    def setUp(self):
        self.u = member("quota_transcoder")
        self.client = APIClient()
        self.client.force_authenticate(self.u)
        self.url = reverse("economy-distributez-transcode")

    def test_output_over_the_per_upload_limit_is_refused(self):
        from .catalog import limits_for

        big = b"\x00" * (limits_for("free")["upload_mb"] * 1024 * 1024 + 1)
        with mock.patch.object(transcode, "available", return_value=True), \
                mock.patch.object(transcode, "to_mp3", return_value=big):
            r = self.client.post(self.url, {"url": "http://x/v.mp4"}, format="json")
        self.assertEqual(r.status_code, 413)
        self.assertEqual(Upload.objects.count(), 0)

    def test_output_over_the_storage_quota_is_refused(self):
        from .catalog import limits_for

        lim = limits_for("free")
        Upload.objects.create(user=self.u, name="old.mp3",
                              size_bytes=lim["storage_mb"] * 1024 * 1024,
                              content_type="audio/mpeg")
        with mock.patch.object(transcode, "available", return_value=True), \
                mock.patch.object(transcode, "to_mp3", return_value=MP3):
            r = self.client.post(self.url, {"url": "http://x/v.mp4"}, format="json")
        self.assertEqual(r.status_code, 409)
