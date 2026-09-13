"""The no-account trial door.

`score_take` is shared with the member coach so the RUBRIC cannot drift
between the trial and the product. These pin the things that drifted anyway:
the INPUTS, and whether a visitor can tell which "no" they just got.
"""
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

class RapZTrialParityTests(TestCase):
    """The trial door must be the same coach, not a thinner one.

    `score_take` is shared with the member coach so the RUBRIC cannot drift.
    The INPUTS drifted instead: RapZ has a style picker, the trial's GET never
    sent the list so the control never rendered, and the POST never forwarded
    an answer even if one arrived. A trial graded on different inputs than the
    product is the same lie as one graded on an easier rubric.
    """

    def setUp(self):
        self.client = APIClient()

    def test_the_rap_style_picker_has_something_to_render(self):
        d = self.client.get("/api/rapz/trial/").data
        self.assertTrue(d["style_label"])
        self.assertTrue(d["styles"])
        self.assertEqual(set(d["styles"][0]), {"key", "label"})

    def test_it_matches_the_shape_ranges_already_used(self):
        d = self.client.get("/api/rapz/trial/").data
        self.assertEqual(set(d["styles"][0]), set(d["ranges"][0]))

    def test_singz_has_no_styles_and_says_so(self):
        # Not every instrument has them; the client renders on style_label.
        d = self.client.get("/api/singz/trial/").data
        self.assertIsNone(d["style_label"])
        self.assertEqual(d["styles"], [])

    def test_the_chosen_style_reaches_the_coach(self):
        # The whole point: the picker's answer has to arrive at score_take.
        seen = {}

        def fake(app_key, f, content_type, **kw):
            seen.update(kw)
            return {"score": 7}, None

        with patch("apps.economy.trial.score_take", fake), \
             patch("apps.economy.trial._key", lambda: "k"):
            take = SimpleUploadedFile("t.m4a", b"x" * 64, content_type="audio/mp4")
            r = self.client.post("/api/rapz/trial/",
                                 {"take": take, "genre": "Drill", "style": "Drill 🔪"},
                                 format="multipart")
        self.assertIn(r.status_code, (200, 201), r.data)
        self.assertEqual(seen.get("style"), "Drill 🔪")


class TrialAvailabilityTests(TestCase):
    """`available: false` has three causes and they need opposite answers."""

    def setUp(self):
        self.client = APIClient()

    def test_the_get_says_which_no_it_is(self):
        d = self.client.get("/api/rapz/trial/").data
        for key in ("configured", "available", "already_used", "cap_reached"):
            self.assertIn(key, d)

    def test_a_full_day_reads_as_cap_reached_not_as_already_used(self):
        # A spent platform allowance and a spent personal one are different
        # sentences to a visitor, and one of them is not their fault.
        from apps.economy.models import TrialTake, trial_daily_cap
        for i in range(trial_daily_cap()):
            TrialTake.objects.create(token=f"t{i}", app_key="rapz", ip="9.9.9.9", result={})
        d = self.client.get("/api/rapz/trial/").data
        self.assertTrue(d["cap_reached"])
        self.assertFalse(d["available"])


class RealBrowserRecordingTests(TestCase):
    """Takes recorded by an actual browser, not bytes we made up.

    Every test of this path has posted synthetic content with a content type
    we chose, which cannot catch the thing that actually breaks it: browsers
    change what MediaRecorder produces. Chromium now supports `audio/mp4` and
    so takes it over WebM, and hands back `audio/mp4;codecs=opus` — an Opus
    stream in an MP4 container, which is not what MP4 usually carries and is
    not what this pipeline was built against.

    The fixtures in testdata_takes/ came out of headless Chromium with a fake
    mic and camera (see the note in RENAME_ICONS.sh's sibling tooling), so the
    container, the codec parameter and the byte layout are a browser's, not
    ours.
    """

    TAKES = {
        "chrome-audio-mp4.bin": "audio/mp4;codecs=opus",
        "chrome-audio-webm.bin": "audio/webm;codecs=opus",
        "chrome-video-webm.bin": "video/webm;codecs=vp8,opus",
    }

    def setUp(self):
        self.client = APIClient()

    def take(self, name):
        import pathlib
        data = (pathlib.Path(__file__).parent / "testdata_takes" / name).read_bytes()
        return data, SimpleUploadedFile(name, data, content_type=self.TAKES[name])

    def test_every_browser_container_maps_to_something_gemini_lists(self):
        # A content type the coach can't name is a 400 the member reads as
        # "my take was bad".
        from apps.economy.vocalcoach import _GEMINI_AUDIO, _GEMINI_VIDEO, gemini_mime
        for name, ctype in self.TAKES.items():
            mime = gemini_mime(ctype)
            self.assertIsNotNone(mime, f"{ctype} -> None")
            self.assertIn(mime, _GEMINI_AUDIO | _GEMINI_VIDEO, name)

    def test_the_codecs_parameter_never_reaches_the_model(self):
        # It rides through the Blob, the multipart upload and Django
        # untouched, and Gemini rejects the whole request over it.
        from apps.economy.vocalcoach import gemini_mime
        for ctype in self.TAKES.values():
            self.assertNotIn(";", gemini_mime(ctype) or "")

    def test_each_one_is_accepted_and_arrives_whole(self):
        # A distinct address per take: the door is one free take per IP, so
        # the loop would otherwise be testing the rate limiter.
        for n, (name, ctype) in enumerate(self.TAKES.items()):
            with self.subTest(name):
                raw, upload = self.take(name)
                seen = {}

                def fake(app_key, f, content_type, **kw):
                    seen["ctype"] = content_type
                    seen["size"] = len(f.read())
                    return {"score": 7}, None

                with patch("apps.economy.trial.score_take", fake), \
                     patch("apps.economy.trial._key", lambda: "k"):
                    r = self.client.post("/api/rapz/trial/", {"take": upload},
                                         format="multipart", REMOTE_ADDR=f"203.0.113.{n + 1}")

                self.assertIn(r.status_code, (200, 201), f"{name}: {r.data}")
                # Not one byte lost between the recorder and the coach.
                self.assertEqual(seen["size"], len(raw), name)
                # Django's multipart parser keeps only the base type on
                # UploadedFile.content_type and puts the parameters in
                # content_type_extra — so `;codecs=opus` is already gone by
                # the time the view sees it. gemini_mime splits on ";" anyway,
                # and should keep doing so: this is the only path where Django
                # does the stripping for us.
                self.assertEqual(seen["ctype"], ctype.split(";")[0], name)
