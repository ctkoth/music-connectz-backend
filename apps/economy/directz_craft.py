"""The DirectZ craft rating — a model that actually watches the video.

What this replaces: `models.directz_ai_rating` called itself "a deterministic AI
craft estimate" and measured contributor count, how many skills were listed,
description length, the sum of skill prices, and whether the duration fit its
band. None of that is craft. A weak video with five contributors and a padded
description scored ~8; a good one-person video with a terse description scored
~4, and `directz_display_rating` showed it as THE rating until three members
rated it. It taught people to pad the form.

`CLAUDE.md`'s third rule is the test it failed: could a member get a good number
without getting good? There, yes — trivially.

So this does what `vocalcoach.py` does. The video goes to a model that watches
it and comes back scored on things a director would recognise, and the number
moves because the film-making moved.

Three rules taken from the coach rather than reinvented:

**A take the model can't read isn't charged, and isn't scored.** Same rule
`vocalcoach.py` bills on. Here it goes further: where the video cannot be read,
DirectZ stores **no rating at all** rather than falling back to a number. An
empty rating invites a real one; a fake one ends the question.

**Normalise the container before the call.** `gemini_mime()` is imported rather
than copied — it is the function that took a live outage to get right, and a
second copy would drift from it.

**Don't forward the upstream error text.** It is a third party's words about our
member's work. The status and our own reading of it is the useful part.

### The honest limit

Gemini's inline path caps the whole request at 20MB, and base64 inflates by 4/3
— so about 14MB of video, which is `vocalcoach.MAX_MB`. A MovieZ entry is one to
three hours and will not fit. That is not worked around here: a video too large
to read is **not rated**, and the work says so. Rating a three-hour film from its
metadata is precisely the thing this module exists to stop doing.
"""
import base64
import json
import logging
import re

import requests

from .gemini import generate_content
from .vocalcoach import MAX_MB, _key, gemini_mime

logger = logging.getLogger(__name__)

# What a director is actually judged on. Each is visible IN the video — none of
# them can be satisfied by filling in a form, which is the whole point.
CRAFT_SCORES = {
    "framing": "Framing & composition",
    "editing": "Editing & pacing",
    "lighting": "Lighting & image",
    "sound": "Sound quality",
    "story": "Storytelling",
}

PROMPT = """You are a film and video craft critic rating a piece of work for \
DirectZ, a collaborative video app for musicians. Watch the video and judge what \
is actually on screen.

This is a {fmt} ({length}) filed under the genre "{genre}".

Rate ONLY what you can see and hear. Do not reward length, ambition, or how many \
people were involved — you cannot see those and they are not craft. A simple \
video executed well beats an elaborate one executed badly.

Reply with ONLY a JSON object, no prose around it:
{{
  "score": <overall 1-10>,
  "scores": {{"framing": <1-10>, "editing": <1-10>, "lighting": <1-10>,
             "sound": <1-10>, "story": <1-10>}},
  "verdict": "<one or two sentences on what this video is and how well it is made>",
  "strengths": ["<what genuinely works, specific to this video>"],
  "fixes": ["<what to do differently next time, specific and actionable>"]
}}"""


def _parse(text):
    """Pull the JSON object out of a reply that may be fenced. Mirrors the coach."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def _clamp(v, lo=1, hi=10):
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return None


def too_big(size_bytes):
    """Whether a video is past what the inline path can carry.

    Checked by callers BEFORE reading the file, so a three-hour MovieZ never
    gets loaded into memory just to be refused.
    """
    return bool(size_bytes) and size_bytes > MAX_MB * 1024 * 1024


def rate_video(fileobj, content_type, *, fmt="reelz", genre="", length=""):
    """Watch one video and score its craft. Returns (payload, reason).

    Exactly one is None. `reason` is a short phrase for logs and for the work's
    own record of why it has no rating — never shown as a score, because the
    absence of a rating is the honest answer when the video couldn't be read.
    """
    key = _key()
    if not key:
        return None, "the video rater isn't configured (GEMINI_API_KEY)"

    # Normalised before the call, using the coach's own function — an
    # unsupported container is a refusal we can give instantly rather than a
    # round trip that comes back as something the member reads as "my film was
    # bad".
    mime = gemini_mime(content_type)
    if not mime:
        return None, f"the rater can't read {content_type or 'that format'}"

    prompt = PROMPT.format(fmt=fmt, length=length or "unspecified length",
                           genre=genre or "unspecified")
    # Read the video ONCE — the chain may try more than one model, and a file
    # object read twice sends the second attempt nothing.
    body = {"contents": [{"parts": [
        {"text": prompt},
        {"inline_data": {"mime_type": mime, "data": base64.b64encode(fileobj.read()).decode()}},
    ]}]}
    try:
        # Same chain the coach walks, so a retired model name can't take the
        # rater down on its own — see gemini.MODEL_CHAINS.
        resp, tried = generate_content(
            "text", body, key=key,
            timeout=180,     # a video is a longer watch than a vocal take
            env_vars=("GEMINI_VIDEO_MODEL", "GEMINI_AUDIO_MODEL"),
            label="DirectZ craft")
    except requests.RequestException:
        logger.exception("DirectZ craft: could not reach Gemini")
        return None, "couldn't reach the rater"
    model = ", ".join(tried)

    if resp.status_code != 200:
        # The mime and model in the line, for the same reason the coach logs
        # them: without those, a container rejection and a bad key look
        # identical, which is how that one stayed hidden for weeks.
        logger.error("DirectZ craft: Gemini %s for mime=%s model=%s — %s",
                     resp.status_code, mime, model, resp.text[:300])
        return None, {
            400: "that video's format wasn't accepted",
            403: "the rater's API key was refused",
            404: "the rater can't reach a model right now",
            429: "the rater has hit its limit for now",
        }.get(resp.status_code,
              "the rater is having a moment" if resp.status_code >= 500
              else "the rater refused that one")

    try:
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, ValueError):
        logger.error("DirectZ craft: unexpected Gemini shape")
        return None, "the rater's reply didn't come back readable"

    parsed = _parse(text)
    if not parsed or _clamp(parsed.get("score")) is None:
        logger.error("DirectZ craft: unparseable reply — %s", text[:300])
        return None, "the rater's reply didn't come back readable"

    listy = lambda v: [str(x)[:300] for x in v][:6] if isinstance(v, list) else []
    return {
        "score": _clamp(parsed.get("score")),
        "scores": {k: _clamp((parsed.get("scores") or {}).get(k)) for k in CRAFT_SCORES},
        "verdict": str(parsed.get("verdict", ""))[:400],
        "strengths": listy(parsed.get("strengths")),
        "fixes": listy(parsed.get("fixes")),
    }, None
