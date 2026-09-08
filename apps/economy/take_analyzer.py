"""Pitch and timing analysis of a recorded take.

Requires librosa + numpy. Both are optional: with neither installed the
analysis is skipped and the row says so, rather than the import taking the
whole app down.

Two things here are load-bearing and neither is decoration:

- **It reads `upload.file`, never a URL.** `Upload` has no `url` attribute —
  the address a member's browser uses is built by `media._upload_dict` and is
  a ROUTE, not a path. An earlier version read `upload.url`, which raised
  AttributeError into a bare `except` and wrote the failure to the row, so
  every analysis on the platform "ran" and none of them ever produced a
  number.

- **Silence is not scored.** `librosa.yin` returns an f0 for every frame
  whether or not anybody is singing, so a take with pauses in it gets a pitch
  read off the room tone and an accuracy dragged down by the gaps. `pyin`
  returns a voiced flag per frame and only voiced frames count. That is the
  substance rule applied to this number: it has to move because the SINGING
  moved, not because the silence did.
"""
import math

try:
    import librosa
    import numpy as np
    HAS_LIBROSA = True
except ImportError:  # pragma: no cover - depends on the deploy's wheels
    HAS_LIBROSA = False
    librosa = None
    np = None

from django.utils import timezone

from .models import TakeAnalysis, Upload

# The contour is the raw material, not the finding. At hop 512 / 44.1kHz it is
# ~86 readings a second, so a three-minute take is ~15,000 of them — a
# JSONField that size is serialized into every response that touches the row.
# The weak notes and the accuracy are what a member reads; the contour is kept
# only as a bounded sample so a future screen can draw it.
MAX_STORED_NOTES = 400

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
A4_FREQ = 440.0


def analyzable(upload):
    """Whether this upload is a recording worth listening to.

    `Upload` carries no app_key — the only honest signal on the row is what
    the browser said it was sending.
    """
    return (upload.content_type or "").startswith(("audio/", "video/"))


def analyze_take_audio(upload_id):
    """Analyse one take. Returns the TakeAnalysis row, or None if it can't run.

    Slow — seconds of DSP on a real take — so nothing calls this from a write
    path. It is computed once, on the first request that asks for it, and the
    row is the cache.
    """
    try:
        upload = Upload.objects.get(id=upload_id)
    except Upload.DoesNotExist:
        return None

    if not analyzable(upload):
        return None

    analysis, _ = TakeAnalysis.objects.get_or_create(upload=upload)

    if not HAS_LIBROSA:
        analysis.analysis_status = "failed"
        analysis.error_message = "Audio analysis isn't available on this server."
        analysis.save(update_fields=["analysis_status", "error_message"])
        return analysis

    # The bytes are already known to be gone. Going to look again would stat
    # storage on a read path for a file something else has already established
    # is missing.
    if upload.missing_since:
        analysis.analysis_status = "failed"
        analysis.error_message = "That recording isn't on the server any more."
        analysis.save(update_fields=["analysis_status", "error_message"])
        return analysis

    try:
        y, sr = _load_audio(upload)

        voiced = detect_pitch_contour(y, sr)
        analysis.weak_notes = identify_weak_notes(voiced)
        analysis.timing_issues = detect_timing_issues(y, sr)
        analysis.overall_pitch_accuracy = calculate_pitch_accuracy(voiced)
        analysis.detected_notes = _sampled(voiced, MAX_STORED_NOTES)
        analysis.analysis_status = "done"
        analysis.error_message = ""
        analysis.analyzed_at = timezone.now()
        analysis.save()
    except Exception as e:
        analysis.analysis_status = "failed"
        analysis.error_message = _why(e)
        analysis.save(update_fields=["analysis_status", "error_message"])

    return analysis


def _why(exc):
    """A reason a member can read. Never an empty string.

    `str(exc)` is EMPTY for some of the exceptions most likely to land here —
    audioread's NoBackendError, which is exactly what an unreadable or
    truncated file raises. That put "Analysis unavailable:" on screen with
    nothing after the colon: a failure that does not say what failed, which is
    worse than no message because it reads as a broken screen rather than a
    broken file.
    """
    name = type(exc).__name__
    if name == "NoBackendError":
        return ("That file couldn't be decoded — it may be truncated, or in a "
                "format this server has no decoder for.")
    return (str(exc) or name)[:500]


def _load_audio(upload):
    """Hand librosa the actual bytes.

    A local disk gives a real path. A bucket raises NotImplementedError for
    `.path`, so the file is spooled to a temp file — librosa's mp3/m4a decode
    goes through audioread, which needs a name on disk, not a file object.
    """
    import os
    import tempfile

    try:
        return librosa.load(upload.file.path, sr=None, mono=True)
    except (NotImplementedError, AttributeError, ValueError):
        pass

    suffix = os.path.splitext(upload.name or "")[1][:10]
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        upload.file.open("rb")
        try:
            for chunk in upload.file.chunks():
                tmp.write(chunk)
        finally:
            upload.file.close()
        tmp.close()
        return librosa.load(tmp.name, sr=None, mono=True)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def detect_pitch_contour(y, sr, hop_length=512, fmin=65, fmax=1200):
    """Voiced frames only, each as {note, freq, cents_off, timestamp}.

    `pyin` is slower than `yin` and returns what `yin` cannot: whether a frame
    is a note at all. Everything downstream depends on that distinction.
    """
    f0, voiced_flag, _ = librosa.pyin(
        y, fmin=fmin, fmax=fmax, sr=sr, hop_length=hop_length)
    times = librosa.times_like(f0, sr=sr, hop_length=hop_length)

    out = []
    for t, freq, is_voiced in zip(times, f0, voiced_flag):
        if not is_voiced or freq is None or not np.isfinite(freq) or freq <= 0:
            continue
        note_name, cents_off = freq_to_note(freq)
        out.append({
            "note": note_name,
            "freq": float(freq),
            "cents_off": cents_off,
            "timestamp": round(float(t), 3),
        })
    return out


def freq_to_note(freq):
    """Frequency → nearest note name and how far off it is, in cents.

    Plain arithmetic on purpose. Reaching for numpy here would tie the note
    names — and every test of them — to whether the DSP wheels happen to be
    installed, which is exactly the kind of coupling that leaves a rule
    untested on the box where it matters.
    """
    semitones_from_a4 = 12 * math.log2(freq / A4_FREQ)
    semitone = int(round(semitones_from_a4))
    cents_off = int(round(100 * (semitones_from_a4 - semitone)))

    note_index = (semitone + 9) % 12
    octave = 4 + (semitone + 9) // 12
    return f"{NOTE_NAMES[note_index]}{octave}", cents_off


def identify_weak_notes(detected_notes, cent_threshold=15, min_occurrences=3):
    """Notes sung often enough to judge, and consistently out of tune."""
    if not detected_notes:
        return []

    groups = {}
    for d in detected_notes:
        groups.setdefault(d["note"], []).append(d)

    weak = []
    for note, hits in groups.items():
        if len(hits) < min_occurrences:
            continue
        # The SIGNED mean decides, and that is the whole rule. What this flags
        # is a note bent consistently one way, because the only thing we can
        # hand somebody is a direction to correct toward — "you are 30 cents
        # flat on E4, aim higher". A note sung sharp as often as flat averages
        # to nearly zero and is deliberately NOT flagged: it is unsteady
        # rather than mistuned, and telling that member they are "flat by 0
        # cents" would be a drill pointed at nothing.
        offset = _mean(h["cents_off"] for h in hits)
        if abs(offset) <= cent_threshold:
            continue
        weak.append({
            "note": note,
            "freq": _mean(h["freq"] for h in hits),
            "cents_off": int(round(offset)),
            "hits": len(hits),
        })

    return sorted(weak, key=lambda x: abs(x["cents_off"]), reverse=True)


def detect_timing_issues(y, sr, hop_length=512):
    """How many gaps between onsets run short (rushing) or long (dragging)."""
    try:
        onsets = librosa.onset.onset_detect(y=y, sr=sr, hop_length=hop_length)
        if len(onsets) < 3:
            return {"rushing_count": 0, "dragging_count": 0}

        intervals = np.diff(librosa.frames_to_time(onsets, sr=sr, hop_length=hop_length))
        if len(intervals) < 2:
            return {"rushing_count": 0, "dragging_count": 0}

        avg, spread = float(np.mean(intervals)), float(np.std(intervals))
        if spread == 0:
            return {"rushing_count": 0, "dragging_count": 0}

        return {
            "rushing_count": int(np.sum(intervals < avg - spread)),
            "dragging_count": int(np.sum(intervals > avg + spread)),
        }
    except Exception:
        return {"rushing_count": 0, "dragging_count": 0}


def calculate_pitch_accuracy(detected_notes, cent_threshold=5):
    """Share of SUNG frames landing within `cent_threshold` of a real note.

    None when there was nothing to measure. A take with no voiced frames has
    no accuracy — reporting 0% would tell somebody their singing was wrong
    when what actually happened is that we never heard any.
    """
    if not detected_notes:
        return None
    in_tune = sum(1 for n in detected_notes if abs(n["cents_off"]) <= cent_threshold)
    return int(round(100 * in_tune / len(detected_notes)))


def _mean(values):
    vals = [float(v) for v in values]
    return sum(vals) / len(vals) if vals else 0.0


def _sampled(rows, limit):
    """Evenly thin `rows` down to at most `limit`, keeping the shape."""
    if len(rows) <= limit:
        return rows
    step = len(rows) / limit
    return [rows[int(i * step)] for i in range(limit)]
