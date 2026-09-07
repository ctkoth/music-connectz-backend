"""Automatic analysis of submitted takes: pitch detection, timing issues, weak notes.

Requires: librosa, numpy. If not available, analysis is skipped gracefully.
"""
try:
    import librosa
    import numpy as np
    HAS_LIBROSA = True
except ImportError:
    HAS_LIBROSA = False
    librosa = None
    np = None

from .models import TakeAnalysis, Upload
from django.utils import timezone


def analyze_take_audio(upload_id):
    """Run pitch and timing analysis on an uploaded take.

    Args:
        upload_id: Upload.id to analyze

    Returns:
        TakeAnalysis object with results, or None if failed
    """
    if not HAS_LIBROSA:
        return None

    try:
        upload = Upload.objects.get(id=upload_id)
    except Upload.DoesNotExist:
        return None

    analysis, _ = TakeAnalysis.objects.get_or_create(upload=upload)
    analysis.analysis_status = "pending"
    analysis.save(update_fields=["analysis_status"])

    try:
        media_path = upload.url
        if not media_path or media_path.startswith("http"):
            analysis.analysis_status = "failed"
            analysis.error_message = "Media file not accessible locally"
            analysis.save(update_fields=["analysis_status", "error_message"])
            return analysis

        y, sr = librosa.load(media_path, sr=None)

        detected = detect_pitch_contour(y, sr)
        weak = identify_weak_notes(detected)
        timing = detect_timing_issues(y, sr)
        accuracy = calculate_pitch_accuracy(detected)

        analysis.detected_notes = detected
        analysis.weak_notes = weak
        analysis.timing_issues = timing
        analysis.overall_pitch_accuracy = accuracy
        analysis.analysis_status = "done"
        analysis.analyzed_at = timezone.now()
        analysis.save()

        return analysis

    except Exception as e:
        analysis.analysis_status = "failed"
        analysis.error_message = str(e)[:500]
        analysis.save(update_fields=["analysis_status", "error_message"])
        return analysis


def detect_pitch_contour(y, sr, hop_length=512, fmin=50, fmax=2000):
    """Extract pitch contour from audio using autocorrelation.

    Returns:
        List of {note, freq, cents_off, timestamp}
    """
    S = librosa.stft(y, hop_length=hop_length)
    magnitude = np.abs(S)

    f0 = librosa.yin(y, fmin=fmin, fmax=fmax, sr=sr, hop_length=hop_length)
    times = librosa.frames_to_time(np.arange(len(f0)), sr=sr, hop_length=hop_length)

    result = []
    for i, (t, freq) in enumerate(zip(times, f0)):
        if freq > 0 and freq < fmax:
            note_name, cents_off = freq_to_note(freq)
            result.append({
                "note": note_name,
                "freq": float(freq),
                "cents_off": cents_off,
                "timestamp": float(t)
            })

    return result


def freq_to_note(freq):
    """Convert frequency to nearest note and cents deviation.

    Returns:
        (note_name, cents_off) tuple
    """
    NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    A4_FREQ = 440.0

    semitones_from_a4 = 12 * np.log2(freq / A4_FREQ)
    semitone = round(semitones_from_a4)
    cents_off = round(100 * (semitones_from_a4 - semitone))

    note_index = (semitone + 9) % 12
    octave = 4 + (semitone + 9) // 12
    note_name = f"{NOTE_NAMES[note_index]}{octave}"

    return note_name, cents_off


def identify_weak_notes(detected_notes, cent_threshold=15, min_occurrences=3):
    """Identify notes that are consistently off-pitch.

    Args:
        detected_notes: List from detect_pitch_contour
        cent_threshold: Notes off by more than this are flagged
        min_occurrences: Must occur at least this many times

    Returns:
        List of {note, freq, cents_off} for weak notes
    """
    if not detected_notes:
        return []

    note_groups = {}
    for d in detected_notes:
        key = d["note"]
        if key not in note_groups:
            note_groups[key] = []
        note_groups[key].append(d)

    weak = []
    for note, occurrences in note_groups.items():
        if len(occurrences) >= min_occurrences:
            avg_cents = np.mean([abs(o["cents_off"]) for o in occurrences])
            if avg_cents > cent_threshold:
                avg_freq = np.mean([o["freq"] for o in occurrences])
                avg_cents_off = round(np.mean([o["cents_off"] for o in occurrences]))
                weak.append({
                    "note": note,
                    "freq": float(avg_freq),
                    "cents_off": avg_cents_off
                })

    return sorted(weak, key=lambda x: abs(x["cents_off"]), reverse=True)


def detect_timing_issues(y, sr, hop_length=512):
    """Detect rushing (speeding up) and dragging (slowing down).

    Returns:
        {rushing_count, dragging_count}
    """
    try:
        onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
        onsets = librosa.onset.onset_detect(onset_env=onset_env, sr=sr, hop_length=hop_length)

        if len(onsets) < 2:
            return {"rushing_count": 0, "dragging_count": 0}

        times = librosa.frames_to_time(onsets, sr=sr, hop_length=hop_length)
        intervals = np.diff(times)

        if len(intervals) < 2:
            return {"rushing_count": 0, "dragging_count": 0}

        avg_interval = np.mean(intervals)
        std_interval = np.std(intervals)

        rushing = sum(1 for i in intervals if i < (avg_interval - std_interval))
        dragging = sum(1 for i in intervals if i > (avg_interval + std_interval))

        return {
            "rushing_count": int(rushing),
            "dragging_count": int(dragging)
        }
    except Exception:
        return {"rushing_count": 0, "dragging_count": 0}


def calculate_pitch_accuracy(detected_notes, cent_threshold=50):
    """Calculate overall pitch accuracy as a percentage.

    0% = all notes significantly off
    100% = all notes in tune (±5 cents)
    """
    if not detected_notes:
        return 0

    in_tune = sum(1 for n in detected_notes if abs(n["cents_off"]) <= 5)
    total = len(detected_notes)

    return max(0, min(100, round(100 * in_tune / total)))
