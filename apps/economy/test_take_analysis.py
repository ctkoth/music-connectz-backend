"""What the take analyser must never do again.

Every assertion here corresponds to a bug that shipped on the branch this
file was added to, and each one was invisible from the app:

- A `post_save` receiver read `instance.app_key`, which `Upload` does not
  have. `Upload` is the row behind every avatar, cover, video and game asset
  on the platform, not only takes — so the AttributeError meant EVERY upload
  raised. The suite went green anyway, because nothing asserted that saving
  an Upload works.
- `analyze_take_audio` read `upload.url`, also not a field. The
  AttributeError landed in a bare `except` and was written to the row, so
  every analysis "ran" and none produced a number.
- The view filtered on `upload__post__user` — there is no `post` relation on
  Upload — so the endpoint raised FieldError on every call.

The lesson the file exists to hold: three fatal bugs in one feature, none of
which broke a test, because the tests asserted the feature's happy path and
nothing asserted the surrounding platform still worked.
"""
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from . import take_analyzer
from .models import TakeAnalysis, Upload

User = get_user_model()


def _upload(user, name="take.wav", content_type="audio/wav", body=b"RIFFfake"):
    return Upload.objects.create(
        user=user, file=ContentFile(body, name=name), name=name,
        size_bytes=len(body), content_type=content_type)


class UploadStillWorks(TestCase):
    """The platform-wide regression: saving an Upload must never raise."""

    def setUp(self):
        self.user = User.objects.create_user(username="u1", password="pw")

    def test_audio_upload_saves(self):
        self.assertTrue(_upload(self.user).pk)

    def test_non_take_uploads_save(self):
        # An avatar and a game asset go through the same model. The receiver
        # that broke this did not care what kind of upload it was.
        for name, ctype in (("avatar.png", "image/png"),
                            ("clip.mp4", "video/mp4"),
                            ("level.json", "application/json"),
                            ("nothing", "")):
            with self.subTest(name=name):
                self.assertTrue(_upload(self.user, name, ctype).pk)

    def test_saving_an_upload_does_not_analyse_it(self):
        """Analysis is lazy. A write path must not run seconds of DSP."""
        up = _upload(self.user)
        self.assertFalse(TakeAnalysis.objects.filter(upload=up).exists())


class Analyzable(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u2", password="pw")

    def test_only_recordings(self):
        self.assertTrue(take_analyzer.analyzable(_upload(self.user)))
        self.assertTrue(take_analyzer.analyzable(
            _upload(self.user, "a.mp4", "video/mp4")))
        self.assertFalse(take_analyzer.analyzable(
            _upload(self.user, "a.png", "image/png")))
        self.assertFalse(take_analyzer.analyzable(
            _upload(self.user, "a", "")))


class ReadsRealFields(TestCase):
    """The analyser may only touch attributes Upload actually has."""

    def setUp(self):
        self.user = User.objects.create_user(username="u3", password="pw")

    def test_upload_has_no_url_or_app_key(self):
        up = _upload(self.user)
        self.assertFalse(hasattr(up, "url"))
        self.assertFalse(hasattr(up, "app_key"))

    def test_the_upload_signal_module_is_gone(self):
        """Pinned by import, because a receiver within reach gets re-wired.

        Introspecting the connected receivers is tempting and brittle — the
        signal internals differ between Django versions. What actually has to
        stay true is that the module does not exist to be imported back into
        apps.py by the next person who wants analysis to feel automatic.
        """
        import importlib
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("apps.economy.signals_take_analysis")

    def test_missing_file_is_reported_not_guessed(self):
        from django.utils import timezone
        up = _upload(self.user)
        up.missing_since = timezone.now()
        up.save(update_fields=["missing_since"])

        row = take_analyzer.analyze_take_audio(up.id)
        self.assertEqual(row.analysis_status, "failed")
        self.assertIn("server", row.error_message)

    def test_unreadable_audio_fails_the_row_not_the_request(self):
        """Junk bytes are a failed analysis, never an exception.

        And the failure has to SAY something. audioread's NoBackendError —
        which is precisely what a truncated or undecodable file raises — has
        an empty str(), so this once stored "" and the client rendered
        "Analysis unavailable:" with nothing after the colon.
        """
        up = _upload(self.user, body=b"not audio at all")
        row = take_analyzer.analyze_take_audio(up.id)
        self.assertIsNotNone(row)
        self.assertEqual(row.analysis_status, "failed")
        self.assertTrue(row.error_message, "a failure with no reason is a blank screen")
        self.assertGreater(len(row.error_message), 10)


class PitchMath(TestCase):
    def test_known_notes(self):
        if not take_analyzer.HAS_LIBROSA:
            self.skipTest("librosa not installed")
        for freq, expected in ((440.0, "A4"), (261.63, "C4"),
                               (246.94, "B3"), (880.0, "A5")):
            note, cents = take_analyzer.freq_to_note(freq)
            self.assertEqual(note, expected)
            self.assertLessEqual(abs(cents), 2)

    def test_accuracy_is_none_when_nothing_was_sung(self):
        """Silence has no accuracy. 0% would be a verdict we never earned."""
        self.assertIsNone(take_analyzer.calculate_pitch_accuracy([]))

    def test_accuracy_counts_only_in_tune_frames(self):
        rows = [{"cents_off": 0}, {"cents_off": 1},
                {"cents_off": 40}, {"cents_off": -60}]
        self.assertEqual(take_analyzer.calculate_pitch_accuracy(rows), 50)

    def test_weak_notes_need_repetition(self):
        """Two bad stabs at a note are not a weakness."""
        twice = [{"note": "E4", "freq": 330.0, "cents_off": -40}] * 2
        self.assertEqual(take_analyzer.identify_weak_notes(twice), [])

        thrice = [{"note": "E4", "freq": 330.0, "cents_off": -40}] * 3
        weak = take_analyzer.identify_weak_notes(thrice)
        self.assertEqual(len(weak), 1)
        self.assertEqual(weak[0]["note"], "E4")
        self.assertEqual(weak[0]["cents_off"], -40)

    def test_a_note_sung_both_ways_is_not_weak(self):
        """Sharp half the time and flat the other half averages to in tune."""
        rows = ([{"note": "E4", "freq": 330.0, "cents_off": 30}] * 3
                + [{"note": "E4", "freq": 330.0, "cents_off": -30}] * 3)
        self.assertEqual(take_analyzer.identify_weak_notes(rows), [])

    def test_contour_is_bounded(self):
        rows = [{"note": "A4", "freq": 440.0, "cents_off": 0, "timestamp": i}
                for i in range(5000)]
        kept = take_analyzer._sampled(rows, take_analyzer.MAX_STORED_NOTES)
        self.assertEqual(len(kept), take_analyzer.MAX_STORED_NOTES)
        self.assertEqual(kept[0], rows[0])


class ItActuallyHears(TestCase):
    """The only test here that proves the analyser measures anything.

    Every other test in this file pins the plumbing — that the right field is
    read, that a failure lands on the row, that an unpriced case is named.
    None of them would notice if the pitch maths were wrong, because none of
    them ever hand it a sound.

    This one synthesises a tone at a KNOWN frequency and asserts the analyser
    says so. It is the same argument tools/coach_live_check.sh makes about the
    Gemini transport: a suite that only ever tests the protocol it believes in
    cannot tell you the belief is wrong.
    """

    def setUp(self):
        if not take_analyzer.HAS_LIBROSA:
            self.skipTest("librosa not installed")

    def _take(self, *freqs, secs=2.0, sr=22050):
        """A wav of pure tones, one per frequency, back to back."""
        import numpy as np
        parts = []
        for f in freqs:
            t = np.linspace(0, secs, int(sr * secs), endpoint=False)
            parts.append(0.5 * np.sin(2 * np.pi * f * t))
        return np.concatenate(parts).astype("float32"), sr

    def _contour(self, *freqs):
        return take_analyzer.detect_pitch_contour(*self._take(*freqs))

    def test_it_names_the_note_it_was_given(self):
        rows = self._contour(440.0)
        self.assertTrue(rows, "no voiced frames found in a pure tone")
        notes = {r["note"] for r in rows}
        self.assertIn("A4", notes)
        # Within a couple of cents across the whole steady tone.
        self.assertLessEqual(
            max(abs(r["cents_off"]) for r in rows if r["note"] == "A4"), 5)

    def test_it_measures_how_flat_a_flat_note_is(self):
        """Synthesised 40 cents flat; the reported number has to agree."""
        e4_flat = 329.63 * (2 ** (-40 / 1200))
        weak = take_analyzer.identify_weak_notes(self._contour(e4_flat))
        self.assertEqual(len(weak), 1)
        self.assertEqual(weak[0]["note"], "E4")
        self.assertAlmostEqual(weak[0]["cents_off"], -40, delta=5)

    def test_an_in_tune_take_is_not_flagged(self):
        """The failure that would make the whole feature noise."""
        self.assertEqual(take_analyzer.identify_weak_notes(self._contour(440.0)), [])

    def test_accuracy_tracks_how_much_was_in_tune(self):
        """Half in tune, half 40 cents flat — the number lands near half."""
        e4_flat = 329.63 * (2 ** (-40 / 1200))
        acc = take_analyzer.calculate_pitch_accuracy(self._contour(440.0, e4_flat))
        self.assertIsNotNone(acc)
        self.assertGreater(acc, 30)
        self.assertLess(acc, 70)

    def test_silence_is_not_scored_as_singing(self):
        """yin would have invented a pitch here; pyin's voiced flag must not."""
        import numpy as np
        silence = np.zeros(22050 * 2, dtype="float32")
        rows = take_analyzer.detect_pitch_contour(silence, 22050)
        self.assertEqual(rows, [])
        # And no voiced frame means no verdict, rather than a damning 0%.
        self.assertIsNone(take_analyzer.calculate_pitch_accuracy(rows))


class Endpoint(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="u4", password="pw")
        self.other = User.objects.create_user(username="u5", password="pw")
        self.up = _upload(self.user)

    def _url(self, upload_id):
        return reverse("economy-take-analysis", args=[upload_id])

    def test_requires_auth(self):
        self.assertIn(self.client.get(self._url(self.up.id)).status_code,
                      (401, 403))

    def test_owner_gets_an_answer_not_an_error(self):
        """The query used to raise FieldError on every single call."""
        self.client.force_login(self.user)
        r = self.client.get(self._url(self.up.id))
        self.assertEqual(r.status_code, 200)
        self.assertIn("analysis_status", r.json())

    def test_somebody_elses_take_is_not_readable(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self._url(self.up.id)).status_code, 404)

    def test_missing_upload_404s(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self._url(999999)).status_code, 404)

    def test_an_image_is_not_a_take(self):
        self.client.force_login(self.user)
        img = _upload(self.user, "a.png", "image/png")
        self.assertEqual(self.client.get(self._url(img.id)).status_code, 404)

    def test_result_is_cached_not_recomputed(self):
        self.client.force_login(self.user)
        self.client.get(self._url(self.up.id))
        row = TakeAnalysis.objects.get(upload=self.up)
        stamp = row.analysis_status

        self.client.get(self._url(self.up.id))
        self.assertEqual(TakeAnalysis.objects.filter(upload=self.up).count(), 1)
        self.assertEqual(TakeAnalysis.objects.get(upload=self.up).analysis_status,
                         stamp)
