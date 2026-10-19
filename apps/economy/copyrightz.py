"""Does this video contain a recording somebody else owns?

DirectZ takes an upload, the coach watches it and scores the craft, and until
now nothing asked the one question that decides whether a member can safely
publish it. This is that check.

## A match is not a verdict, and this file is built around that

The most common match on a music platform is **the member's own release**. The
next most common is a licensed sample, a cover they have the rights to, or a
clip they were paid to cut. So a match here is a FACT — this audio matches this
recording — and never a finding of infringement:

* Nothing is blocked, deleted or hidden automatically.
* The member is told WHAT matched, with the title, the artist and the label,
  BEFORE they publish. That is the same rule as a price: something you find out
  by publishing is not a warning, it's a takedown.
* They answer it — mine, licensed, cover, or "I didn't know" — and their answer
  travels with the work.
* The owner sees the ones that stay unanswered.

Naming what matched is the whole value. "Possible copyrighted content" tells a
member nothing they can act on; "this matches *Bad and Boujee*, Quality Control,
from 0:14" tells them exactly what to cut or clear.

## An unscanned upload is never reported as clear

Same rule as the link scanner, for the same reason, and the mistake is easier
to make here because "no match" and "we did not look" both feel like good news.
They are not the same fact, and only one of them is worth anything to a member
about to publish. `state` has three values — `unscanned`, `clear`, `matched` —
and `unscanned` is the default.

Two things have to be true before anything is scanned, and each says so
separately when it is missing:

* **A provider.** `ACRCLOUD_ACCESS_KEY` + `ACRCLOUD_ACCESS_SECRET` (+ optional
  `ACRCLOUD_HOST` for the region). Recognition is a fingerprint database, not
  something a model can be asked to guess at — a language model's opinion about
  whether audio is copyrighted is exactly the number-with-nothing-behind-it the
  substance rule forbids, and it would be one attached to a legal question.
* **ffmpeg**, to cut a short audio sample out of a video. The identify API takes
  an audio sample under 5MB and works best on about 15 seconds; a video file's
  first bytes are not a decodable audio stream, so sending them would be a
  request that always answers "no match" — the worst possible failure, because
  it looks exactly like a pass.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

# Three states, and the difference between the first two is the whole point.
UNSCANNED, CLEAR, MATCHED = "unscanned", "clear", "matched"

# What the member can say about a match. `unanswered` is the state a work sits
# in until they do, and it is what the owner's queue is a list of.
CLAIMS = {
    "mine": "It's my own recording",
    "licensed": "I licensed or cleared it",
    "cover": "It's my performance of someone else's song",
    "unaware": "I didn't know it was in there",
}

# The sample the identify API wants: short, and well under its 5MB ceiling.
SAMPLE_SECONDS = int(os.environ.get("COPYRIGHT_SAMPLE_SECONDS", "15"))
SAMPLE_MAX_BYTES = 4 * 1024 * 1024
# Where in the video to cut from. Not zero: the opening seconds of a music
# video are routinely a logo sting or silence, and a sample of silence is a
# "no match" that means nothing.
SAMPLE_OFFSET_SECONDS = int(os.environ.get("COPYRIGHT_SAMPLE_OFFSET", "20"))
TIMEOUT = 12


def _cfg(name, default=""):
    return (getattr(settings, name, "") or os.environ.get(name, "") or default).strip()


def provider():
    """Which recognition provider is configured, or "". """
    if _cfg("ACRCLOUD_ACCESS_KEY") and _cfg("ACRCLOUD_ACCESS_SECRET"):
        return "acrcloud"
    return ""


def has_ffmpeg():
    return bool(shutil.which("ffmpeg"))


def readiness():
    """What is missing, named separately, so the reason a scan didn't run is
    actionable rather than a shrug."""
    return {
        "provider": provider(),
        "ffmpeg": has_ffmpeg(),
        "ready": bool(provider()) and has_ffmpeg(),
        "why": (
            "" if provider() and has_ffmpeg()
            else "No recognition provider is configured." if not provider()
            else "ffmpeg isn't installed on the host, so audio can't be cut out of a video."
        ),
    }


def _sample_from(path, content_type=""):
    """A short audio sample, or None. Never raises.

    An audio upload under the ceiling is sent as-is when ffmpeg is absent —
    there is nothing to extract, so the one missing dependency should not stop
    the check it isn't needed for.
    """
    if not has_ffmpeg():
        if content_type.startswith("audio/"):
            try:
                with open(path, "rb") as fh:
                    data = fh.read(SAMPLE_MAX_BYTES)
                return data or None
            except OSError:
                return None
        return None
    out = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    out.close()
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(SAMPLE_OFFSET_SECONDS), "-i", path,
             "-t", str(SAMPLE_SECONDS), "-vn", "-ac", "1", "-ar", "8000",
             "-b:a", "64k", out.name],
            capture_output=True, timeout=TIMEOUT * 2, check=False)
        with open(out.name, "rb") as fh:
            data = fh.read(SAMPLE_MAX_BYTES)
        if data:
            return data
        # Past the end of a short clip. Try again from the top rather than
        # calling a 25-second ReelZ unscannable.
        subprocess.run(
            ["ffmpeg", "-y", "-i", path, "-t", str(SAMPLE_SECONDS), "-vn",
             "-ac", "1", "-ar", "8000", "-b:a", "64k", out.name],
            capture_output=True, timeout=TIMEOUT * 2, check=False)
        with open(out.name, "rb") as fh:
            return fh.read(SAMPLE_MAX_BYTES) or None
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        try:
            os.unlink(out.name)
        except OSError:
            pass


def _acrcloud(sample):
    """POST the sample to ACRCloud's identify API. Returns its decoded body.

    The signature is over a fixed field order — method, uri, key, data type,
    signature version, timestamp — joined by newlines. Getting the order wrong
    produces a clean 401 that reads like a bad key, so it is written out here
    rather than built in a loop somebody can reorder.
    """
    host = _cfg("ACRCLOUD_HOST", "identify-eu-west-1.acrcloud.com")
    uri, method, data_type, version = "/v1/identify", "POST", "audio", "1"
    key, secret = _cfg("ACRCLOUD_ACCESS_KEY"), _cfg("ACRCLOUD_ACCESS_SECRET")
    timestamp = str(int(time.time()))
    to_sign = "\n".join([method, uri, key, data_type, version, timestamp])
    signature = base64.b64encode(
        hmac.new(secret.encode(), to_sign.encode(), hashlib.sha1).digest()).decode()

    boundary = "----mcz" + hashlib.sha1(timestamp.encode()).hexdigest()[:16]
    fields = {
        "access_key": key, "data_type": data_type, "signature_version": version,
        "signature": signature, "sample_bytes": str(len(sample)), "timestamp": timestamp,
    }
    body = b""
    for name, value in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                 f"{value}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"sample\"; "
             f"filename=\"sample.mp3\"\r\nContent-Type: audio/mpeg\r\n\r\n").encode()
    body += sample + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"https://{host}{uri}", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode() or "{}")


def _matches_from(payload):
    """The recordings ACRCloud says this is, in our shape.

    Named, not counted. "Possible copyrighted content" tells a member nothing
    they can act on; a title, an artist, a label and an offset tells them
    exactly what to cut or clear.
    """
    out = []
    for m in ((payload.get("metadata") or {}).get("music") or [])[:5]:
        out.append({
            "title": str(m.get("title", ""))[:200],
            "artists": [str(a.get("name", ""))[:120]
                        for a in (m.get("artists") or [])][:6],
            "album": str((m.get("album") or {}).get("name", ""))[:200],
            "label": str(m.get("label", ""))[:160],
            "isrc": str((m.get("external_ids") or {}).get("isrc", ""))[:32],
            # Where in the member's own upload it was heard, so "cut it" is an
            # instruction rather than a search.
            "at_seconds": int((m.get("play_offset_ms") or 0) / 1000),
            "score": int(m.get("score") or 0),
        })
    return out


def scan(path, content_type=""):
    """Identify a file. Returns the result dict — always, never raises.

    `state` is `unscanned` for every outcome that is not a real answer,
    including our own outage. A check that reports "clear" when it could not
    look is worse than no check at all, because clear is the answer a member
    publishes on.
    """
    ready = readiness()
    base = {"state": UNSCANNED, "matches": [], "provider": ready["provider"],
            "checked_at": None, "note": ready["why"]}
    if not ready["provider"]:
        return base
    sample = _sample_from(path, content_type)
    if not sample:
        return {**base, "note": ready["why"] or (
            "No audio could be read out of that file, so nothing was checked.")}
    try:
        payload = _acrcloud(sample)
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        logger.warning("copyrightz: identify failed: %s", exc)
        return {**base, "note": "The copyright check couldn't run just now."}

    code = (payload.get("status") or {}).get("code")
    now = int(time.time())
    if code == 0:
        matches = _matches_from(payload)
        if matches:
            return {"state": MATCHED, "matches": matches, "provider": ready["provider"],
                    "checked_at": now, "note": ""}
        return {"state": CLEAR, "matches": [], "provider": ready["provider"],
                "checked_at": now, "note": ""}
    if code == 1001:
        # "No result" is a real answer from a scan that ran, unlike every other
        # non-zero code, which is ours or theirs failing.
        return {"state": CLEAR, "matches": [], "provider": ready["provider"],
                "checked_at": now, "note": ""}
    logger.warning("copyrightz: provider said %s: %s",
                   code, (payload.get("status") or {}).get("msg"))
    return {**base, "note": "The copyright check couldn't run just now."}


def summary(result, claim=""):
    """One line a member reads, for whichever of the three states this is."""
    state = (result or {}).get("state", UNSCANNED)
    if state == UNSCANNED:
        return ("This hasn't been checked for copyrighted recordings — "
                "that's our check not running, not a result about your video.")
    if state == CLEAR:
        return "No commercial recording was recognised in this."
    names = []
    for m in (result.get("matches") or [])[:3]:
        who = ", ".join(m.get("artists") or []) or "unknown artist"
        at = f" from {m['at_seconds'] // 60}:{m['at_seconds'] % 60:02d}" if m.get("at_seconds") else ""
        names.append(f"“{m.get('title') or 'untitled'}” — {who}{at}")
    line = "This matches " + "; ".join(names) + "."
    if claim in CLAIMS:
        return f"{line} You said: {CLAIMS[claim]}."
    # The way forward, on a refusal-shaped message. A match with no next step
    # is a dead end on the one screen where a member most needs one.
    return (f"{line} A match isn't a verdict — if it's your own recording, a "
            f"cover, or something you cleared, say so and it travels with the work.")
