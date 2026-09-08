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
        events = note_events(voiced)
        analysis.overall_pitch_accuracy = calculate_pitch_accuracy(voiced)
        # The count travels with the score so the member can check it, and so
        # a null accuracy can say "4 notes — sing a bit more" rather than
        # leaving a blank nobody can act on.
        analysis.timing_issues = dict(analysis.timing_issues or {},
                                      notes_counted=len(events),
                                      notes_needed=MIN_NOTES_FOR_ACCURACY)
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


def identify_weak_notes(detected_notes, cent_threshold=15, min_events=2):
    """Notes you sang more than once and bent the same way every time.

    Counts EVENTS, not frames, and that distinction was a bug before it was a
    refinement: `min_occurrences=3` used to mean three consecutive frames,
    which at hop 512 is about 35 milliseconds — so "sung often enough to
    judge" was satisfied by a thirtieth of a second. Now it means you went for
    that note on two separate occasions.

    The SIGNED mean across those events decides, and that is the whole rule.
    What this flags is a note bent consistently one way, because the only
    thing we can hand somebody is a direction to correct toward — "you are 30
    cents flat on E4, aim higher". A note sung sharp as often as flat averages
    to nearly zero and is deliberately NOT flagged: it is unsteady rather than
    mistuned, and telling that member they are "flat by 0 cents" would be a
    drill pointed at nothing.
    """
    events = note_events(detected_notes)
    if not events:
        return []

    groups = {}
    for e in events:
        groups.setdefault(e["note"], []).append(e)

    weak = []
    for note, hits in groups.items():
        if len(hits) < min_events:
            continue
        offset = _mean(h["cents_off"] for h in hits)
        if abs(offset) <= cent_threshold:
            continue
        weak.append({
            "note": note,
            "freq": _mean(h["freq"] for h in hits),
            "cents_off": int(round(offset)),
            # How many separate times you went for it — the member can check
            # this against their own take, which a frame count never was.
            "hits": len(hits),
        })

    return sorted(weak, key=lambda x: abs(x["cents_off"]), reverse=True)


def note_events(rows, min_frames=3):
    """Consecutive frames of the same note, collapsed into one event.

    Everything downstream counts EVENTS rather than frames, and that is a
    correction rather than a tidy-up. Frame counting weights a note by how
    long it was held: at hop 512 an eight-second held note is ~700 frames and
    twenty short ones are ~60 between them, so one bad long note buried twenty
    good short ones and — worse — one good held note could hide twenty bad
    ones. A note is a note. One note, one vote.

    `min_frames` drops the one- and two-frame flickers at note boundaries,
    which are the transition and not a note anybody sang.
    """
    events = []
    for r in rows:
        if events and events[-1]["note"] == r["note"]:
            events[-1]["frames"].append(r)
        else:
            events.append({"note": r["note"], "frames": [r]})

    out = []
    for e in events:
        if len(e["frames"]) < min_frames:
            continue
        cents = sorted(f["cents_off"] for f in e["frames"])
        mid = len(cents) // 2
        out.append({
            "note": e["note"],
            # The MEDIAN of the event, not the mean: a note that starts flat
            # and is corrected mid-way is not half wrong, it is a note that
            # was found. The median follows where the voice settled.
            "cents_off": cents[mid] if len(cents) % 2 else
                         int(round((cents[mid - 1] + cents[mid]) / 2)),
            "freq": _mean(f["freq"] for f in e["frames"]),
            "frames": len(e["frames"]),
            "at": e["frames"][0]["timestamp"],
        })
    return out


def detect_timing_issues(y, sr, hop_length=512):
    """Onsets that land early or late against the take's OWN pulse.

    The first version of this compared every gap between onsets to the mean
    gap plus or minus a standard deviation, and that measured the wrong thing
    entirely: MUSIC HAS RHYTHM. A phrase of quarter notes followed by eighth
    notes has legitimately different gaps, so a perfectly played bar came back
    flagged as both rushing AND dragging. It was detecting "the gaps vary",
    which is a description of music rather than a fault in it.

    Rushing and dragging are words about a PULSE — early or late against the
    beat you are playing to. So the beat is tracked first, a grid is laid down
    at the eighth-note subdivision, and each onset is measured against the
    nearest grid point. Consistently early is rushing; consistently late is
    dragging; the same phrase played straight is neither, whatever its note
    durations.

    The tempo comes back too, because it is the number that makes the finding
    ACTIONABLE — "you drifted at 96 BPM" leads somewhere (MetZ), and a bare
    count of dragged notes does not.
    """
    quiet = {"rushing_count": 0, "dragging_count": 0, "tempo_bpm": None,
             "onsets": 0, "pulse": False, "detail": ""}
    try:
        env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
        onsets = librosa.onset.onset_detect(onset_envelope=env, sr=sr,
                                            hop_length=hop_length)
        if len(onsets) < 4:
            return quiet

        try:
            tempo = float(np.atleast_1d(librosa.beat.beat_track(
                onset_envelope=env, sr=sr, hop_length=hop_length)[0])[0])
        except Exception:
            tempo = 0.0

        onset_times = librosa.frames_to_time(onsets, sr=sr, hop_length=hop_length)
        if onset_times.size < 4:
            return quiet

        # The grid spacing comes from WHAT WAS PLAYED — the median gap between
        # onsets — and not from beat_track's tempo.
        #
        # Deriving it from the tempo estimate was wrong twice over. It drifts
        # (117bpm reported for a 120bpm take walks the grid a fifth of a
        # second out over eight bars), and it assumes a subdivision: half a
        # beat is right for eighth notes and wrong for a take played in
        # quarters, where it leaves every other slot empty and makes the slot
        # assignment fragile. The median gap is whatever the player actually
        # subdivided into, which is the grid they were playing to.
        #
        # beat_track is still worth running, but only for the tempo NUMBER —
        # which is the part that leads somewhere (MetZ), not the part the
        # measurement depends on.
        step = float(np.median(np.diff(onset_times)))
        if step <= 0:
            return quiet

        # The grid's PHASE is fitted to the player, not taken from the beat
        # tracker. beat_track reports beats with a systematic lag, so anchoring
        # the grid at beat_times[0] put every onset slightly before it and a
        # metronomically perfect take came back "rushing" on every note. It is
        # also the musically right choice: nobody is rushing because their
        # whole performance sits 20ms off an arbitrary origin — rushing is
        # being early against YOUR OWN pulse.
        #
        # Circular mean, because the residuals wrap: 0.01s and step-0.01s are
        # adjacent, and a plain average of them lands halfway round the circle.
        # Each onset gets the grid slot it is nearest, then the grid's TRUE
        # spacing and phase are least-squares fitted to those slots.
        #
        # Laying a fixed grid from the tempo estimate is what a first version
        # did, and it drifts: beat_track returned 117bpm for a 120bpm take, a
        # 2.5% error, which over eight seconds walks the grid a fifth of a
        # second away from the notes — so the end of a metronomically perfect
        # take came back "rushing". Fitting absorbs that, because a constant
        # tempo error is a change of slope and the fit finds the slope.
        k = np.round((onset_times - onset_times[0]) / step)
        if np.ptp(k) < 2:
            return quiet
        slope, intercept = np.polyfit(k, onset_times, 1)
        if slope <= 0:
            return quiet
        deltas = onset_times - (slope * k + intercept)
        step = float(slope)

        # Does this take HAVE a pulse to be early or late against?
        #
        # Free singing has onsets — breaths, consonants, phrase starts — but
        # no grid. Without this gate a grid gets fitted to that anyway and
        # rushing/dragging counts fall out of noise, which is a number where
        # the honest answer is "there is no beat here to measure you against".
        # Same shape as the accuracy floor: refuse the verdict rather than
        # invent one.
        #
        # A quarter of a subdivision is the line. Inside it the onsets are
        # sitting on a grid; outside it they are not, and no amount of fitting
        # makes them.
        spread = float(np.std(deltas))
        if spread > step * PULSE_FIT_TOLERANCE:
            return {**quiet, "onsets": int(onset_times.size), "pulse": False,
                    "detail": "No steady pulse in this take to measure timing against."}

        # A fifth of a subdivision either way is "on time" — around 60ms at
        # 100bpm, which is about where a listener starts to hear it.
        tol = step * 0.2
        return {
            "rushing_count": int(np.sum(deltas < -tol)),
            "dragging_count": int(np.sum(deltas > tol)),
            "tempo_bpm": int(round(tempo)) or None,
            "onsets": int(onset_times.size),
            "pulse": True,
            "detail": "",
        }
    except Exception:
        return quiet


# How many notes a take needs before its accuracy means anything.
#
# Without a floor the number is trivially farmable: hold ONE "aah" on a note
# you can hit, and the take is 100% in tune. That is the substance rule's own
# test failing — a member gets a good number without getting good — and it is
# the same failure a rating median has with one rater, answered the same way.
#
# Eight is a phrase rather than a note. Below it there is no verdict, which is
# the honest answer: an absent number invites a real take, a fake one ends the
# question.
MIN_NOTES_FOR_ACCURACY = 8

# How far onsets may sit off the fitted grid before we admit there is no grid.
# A quarter of a subdivision — inside that they are playing to a pulse, outside
# it they are not, and fitting harder does not create one.
PULSE_FIT_TOLERANCE = 0.25


def calculate_pitch_accuracy(detected_notes, cent_threshold=5):
    """Share of NOTES within `cent_threshold`, or None if there aren't enough.

    Counts notes, not frames, so a note counts once however long it was held —
    otherwise one bad eight-second note outvotes twenty good short ones, and
    one good held note hides twenty bad ones.
    """
    events = note_events(detected_notes)
    if len(events) < MIN_NOTES_FOR_ACCURACY:
        return None
    good = sum(1 for e in events if abs(e["cents_off"]) <= cent_threshold)
    return int(round(100 * good / len(events)))


def _mean(values):
    vals = [float(v) for v in values]
    return sum(vals) / len(vals) if vals else 0.0


def _sampled(rows, limit):
    """Evenly thin `rows` down to at most `limit`, keeping the shape."""
    if len(rows) <= limit:
        return rows
    step = len(rows) / limit
    return [rows[int(i * step)] for i in range(limit)]
