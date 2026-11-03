#!/usr/bin/env python3
"""Does Inspiration actually work against Google, and does it keep the two tracks apart?

Same reason tools/coach_live_check.sh exists: every test of matchref stubs `requests`, which pins
the protocol we BELIEVE in and cannot say whether the model reads it the way we mean. This runs the
real `matchref.run_match` — the same prompt, labels, parsing and cleaning the endpoint uses.

    GEMINI_API_KEY=... python tools/inspiration_live_check.py [--take FILE --reference FILE] [--app rapz]

With no files it makes two that are easy to tell apart (Gemini TTS: a slow low voice for Track A,
a fast bright one for Track B). It runs the comparison TWICE, the second time with the files
swapped, and fails unless the model's "heard" sentence follows each file to its new slot — which
is the only way to show from outside that "take" really means the member's track.

Costs: two TTS calls (only when it makes the clips) and two comparisons. Writes nothing to the
database and keeps nothing; the clips land in $TMPDIR so you can listen to them.
"""
import argparse, base64, json, os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "music_connectz.settings")
import django  # noqa: E402
django.setup()

import requests  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from apps.economy import matchref  # noqa: E402
from apps.economy.keyconnectz import _wav  # noqa: E402

KEY = os.environ.get("GEMINI_API_KEY") or sys.exit("set GEMINI_API_KEY")
BASE = "https://generativelanguage.googleapis.com/v1beta"
TTS = os.environ.get("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")

A_LINES = ("Read this slowly, in a low, calm, heavy voice, like a laid-back rapper on a slow beat: "
           "Late night grinding, city lights below, every step I take I'm moving kinda slow, "
           "I keep it steady, keep it low, this is how I flow.")
B_LINES = ("Read this fast, bright and high-energy, like an excited double-time rapper: "
           "Quick quick quick, I'm on the clock, tick tock, never gonna stop, running to the top, "
           "rapid fire, never tire, lift it higher, higher, higher!")


def tts(prompt, voice, out):
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    r = requests.post(f"{BASE}/models/{TTS}:generateContent", params={"key": KEY}, json=body, timeout=120)
    r.raise_for_status()
    part = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
    out.write_bytes(_wav(base64.b64decode(part["data"])))
    return out


def slot(path):
    data = Path(path).read_bytes()
    ctype = {"wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4", "mp4": "video/mp4",
             "webm": "audio/webm", "ogg": "audio/ogg"}.get(Path(path).suffix.lstrip(".").lower(), "audio/wav")
    return matchref._Slot(SimpleUploadedFile(Path(path).name, data, content_type=ctype), ctype)


def run(app, take, ref):
    out, failed = matchref.run_match(app, slot(take), slot(ref), "unspecified")
    if failed is not None:
        print("  FAILED:", failed.status_code, json.dumps(failed.data)[:400])
        sys.exit(1)
    return out


def show(label, out):
    h = out.get("heard") or {}
    o = out.get("overall") or {}
    print(f"\n== {label}")
    print("  heard as YOUR TRACK (A):  ", h.get("take"))
    print("  heard as INSPIRATION (B): ", h.get("reference"))
    print(f"  overall  you {o.get('take')}  ·  inspiration {o.get('reference')}  ·  closeness {out.get('closeness')}%")
    print("  better:", out["compare"].get("better"), " worse:", out["compare"].get("worse"))
    print("  drills:", [f"{d['name']} ({d['targets']}, {d['minutes']} min)" for d in out.get("drills", [])])
    print("  lyric direction:", (out.get("lyric_direction") or "")[:160])


SLOW = ("slow", "low", "calm", "laid", "heavy", "steady", "relaxed", "deep", "measured")
FAST = ("fast", "quick", "bright", "high", "energ", "rapid", "double", "excit", "upbeat")


def leans(sentence):
    s = (sentence or "").lower()
    slow, fast = sum(w in s for w in SLOW), sum(w in s for w in FAST)
    return "slow" if slow > fast else "fast" if fast > slow else "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--take"); ap.add_argument("--reference"); ap.add_argument("--app", default="rapz")
    a = ap.parse_args()
    made = not (a.take and a.reference)
    if made:
        d = Path(tempfile.gettempdir())
        print("==> making two clips with", TTS)
        a.take = str(tts(A_LINES, "Charon", d / "inspiration-check-A-slow.wav"))
        a.reference = str(tts(B_LINES, "Puck", d / "inspiration-check-B-fast.wav"))
        print("   ", a.take, "\n   ", a.reference)

    first = run(a.app, a.take, a.reference)
    show(f"take={Path(a.take).name}  inspiration={Path(a.reference).name}", first)
    second = run(a.app, a.reference, a.take)
    show(f"SWAPPED: take={Path(a.reference).name}  inspiration={Path(a.take).name}", second)

    ok = True
    for name, out in (("first", first), ("swapped", second)):
        if not out.get("heard"):
            print(f"\nFAIL: the {name} run came back without a 'heard' line for both tracks"); ok = False
        if not out.get("drills"):
            print(f"\nFAIL: the {name} run came back with no drills"); ok = False
        if not out.get("overall"):
            print(f"\nFAIL: the {name} run did not rate both tracks"); ok = False
    if made and ok:
        got = (leans(first["heard"]["take"]), leans(first["heard"]["reference"]),
               leans(second["heard"]["take"]), leans(second["heard"]["reference"]))
        print("\n==> who was heard where (expect slow, fast, fast, slow):", ", ".join(got))
        if got != ("slow", "fast", "fast", "slow"):
            print("FAIL: the descriptions did not follow the files to their slots — read the lines above."
                  " A '?' means the sentence did not say slow or fast; check it by ear.")
            ok = False
    print("\nPASS" if ok else "\nFAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
