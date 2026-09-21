"""AttractivenessZ — opt-in presentation feedback, 18+ verified, self only.

Corey asked for an AI attractiveness rating with improvement advice. The
first version of this request — any member, any uploaded photo, a bare
1-10 — was declined outright: this platform's own onboarding puts the floor
at 13, and a machine telling a minor their face scores a 6 is a body-image
harm generator, opt-in or not, because opt-in does not change who else is
standing in the room.

What ships here is the version that survives that objection, built on a
mechanism this codebase already trusts for the same job:
`Profile.verified_18plus` (Stripe Identity) is the SAME gate BattleZ money
betting and adult content already stand behind. A member who has passed
that check is not the audience the first version put at risk.

Four more lines hold it, and none of them are decoration:

1. **Self only.** The request must attest the photo is of the account
   holder (`confirm_self`), enforced as a hard 400 without it — a rating of
   someone else's face without their consent is harassment material, and no
   checkbox on the RATER's side fixes that. This does not verify the
   attestation is true; it makes lying about it a deliberate act rather
   than a checkbox nobody read.
2. **Presentation, never identity.** The model is instructed to score and
   advise ONLY on things a person can act on — skin, grooming, styling,
   photo quality, oral hygiene as visible — and explicitly NOT on bone
   structure, body shape, race, or any other trait nobody can change. An
   "attractiveness" score built on immutable features is a bias engine; one
   built on presentation is closer to a skincare consult, which is what was
   actually asked for ("advice to improve like skincare or teeth").
3. **No video, ever, from this or anything near it.** Generating video from
   a stored face is a separate, categorically different risk (non-consensual
   synthetic media of a real person) that verifying the REQUESTER's age does
   not resolve, because a verified adult can still misuse someone else's
   face. That request is declined independently and permanently — this
   module does not store, cache, or forward the photo to anything that
   could generate video from it, and never will.
4. **Nothing is stored.** No photo, no score, no history — read the result
   once and it is gone, the same choice KeyConnectZ's read-aloud makes for
   the same reason: a repeated biometric-adjacent rating held over time is
   its own privacy risk that a stateless call does not create.

Priced and billed exactly like DirectZ craft and the Boss Take coach: a run
that cannot be read is never charged, and the day's free prompts are spent
before any balance.
"""
import base64
import json
import logging
import re

import requests

from .gemini import generate_content
from .vocalcoach import INLINE_MAX_MB, _key, gemini_mime

logger = logging.getLogger(__name__)

PRESENTATION_SCORES = {
    "skin": "Skin",
    "grooming": "Grooming",
    "styling": "Styling",
    "photo_quality": "Photo quality",
}

# The caveat every response carries, unreworded on the client — the same
# discipline instruments.py's _HISTORY_CAVEAT follows: a member must be told
# what a number does and does not mean, on the same screen, every time.
CAVEAT = ("This reads ONE photo — lighting, angle and a bad hair day all "
          "move it. It scores what you can change (skin, grooming, styling), "
          "never anything you can't. Not a permanent judgment.")

PROMPT = """You are a grooming and presentation consultant, not a beauty \
judge. Look at this ONE photo and give honest, specific, ACTIONABLE feedback \
on presentation only.

Score and advise ONLY on things a person can change: skin condition and care \
(visible texture, blemishes, hydration, sun damage), grooming (hair, facial \
hair, eyebrows), styling (clothing fit, color choices for the photo), oral \
hygiene as visible (teeth), and photo quality (lighting, angle, focus — since \
a bad photo undersells a good presentation).

Do NOT score, mention, or imply anything about bone structure, facial \
proportions, body shape or size, race, ethnicity, age, disability, or any \
other trait nobody can change by Tuesday. If the photo shows something in \
that category, ignore it entirely — it is not what this rates.

Be constructive. Real advice teaches; a list of complaints does not. Name \
what is already working before what to change. Never insulting, never \
clinical-cold — talk TO the person, the way an honest friend who happens to \
know skincare would.

If the photo does not clearly show a face (too dark, too blurry, not a \
person, or multiple people), set "unreadable" to a short sentence saying \
what you saw instead, set every score to null, and stop.

Reply with ONLY a JSON object, no prose around it:
{{
  "unreadable": <null, or a short sentence: what you saw instead>,
  "score": <overall 1-10 on PRESENTATION ONLY, or null if unreadable>,
  "scores": {{"skin": <1-10>, "grooming": <1-10>, "styling": <1-10>, "photo_quality": <1-10>}},
  "verdict": "<one or two sentences, direct and kind>",
  "working": ["<what's already working, specific to this photo>"],
  "advice": ["<specific, actionable next steps — skincare routine, grooming habit, photo tips>"]
}}"""


def _parse(text):
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


def rate_presentation(fileobj, content_type):
    """One photo in, presentation feedback out. Returns (payload, reason).

    Exactly one is None. Caller must have already checked verified_18plus
    and confirm_self — this function does not know about either, the same
    separation `rate_video` keeps from its own caller's billing checks.
    """
    key = _key()
    if not key:
        return None, "the coach isn't configured (GEMINI_API_KEY)"

    mime = gemini_mime(content_type)
    if not mime:
        return None, f"can't read {content_type or 'that format'}"

    body = {"contents": [{"parts": [
        {"text": PROMPT},
        {"inline_data": {"mime_type": mime, "data": base64.b64encode(fileobj.read()).decode()}},
    ]}]}
    try:
        resp, tried = generate_content(
            "text", body, key=key, timeout=90,
            env_vars=("GEMINI_VIDEO_MODEL", "GEMINI_AUDIO_MODEL"),
            label="AttractivenessZ")
    except requests.RequestException:
        logger.exception("AttractivenessZ: could not reach Gemini")
        return None, "couldn't reach the coach"
    model = ", ".join(tried)

    if resp.status_code != 200:
        logger.error("AttractivenessZ: Gemini %s mime=%s model=%s — %s",
                     resp.status_code, mime, model, resp.text[:300])
        return None, {
            400: "that photo wasn't accepted",
            403: "the coach's API key was refused",
            404: "the coach can't reach a model right now",
            429: "the coach has hit its limit for now",
        }.get(resp.status_code,
              "the coach is having a moment" if resp.status_code >= 500
              else "the coach refused that one")

    try:
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, ValueError):
        logger.error("AttractivenessZ: unexpected Gemini shape")
        return None, "the reply didn't come back readable"

    parsed = _parse(text)
    if not parsed:
        logger.error("AttractivenessZ: unparseable reply — %s", text[:300])
        return None, "the reply didn't come back readable"

    if parsed.get("unreadable"):
        return {
            "unreadable": str(parsed["unreadable"])[:300],
            "score": None, "scores": {}, "verdict": "", "working": [], "advice": [],
            "caveat": CAVEAT,
        }, None

    if _clamp(parsed.get("score")) is None:
        logger.error("AttractivenessZ: no usable score — %s", text[:300])
        return None, "the reply didn't come back readable"

    listy = lambda v: [str(x)[:300] for x in v][:6] if isinstance(v, list) else []
    return {
        "unreadable": "",
        "score": _clamp(parsed.get("score")),
        "scores": {k: _clamp((parsed.get("scores") or {}).get(k)) for k in PRESENTATION_SCORES},
        "verdict": str(parsed.get("verdict", ""))[:400],
        "working": listy(parsed.get("working")),
        "advice": listy(parsed.get("advice")),
        "caveat": CAVEAT,
    }, None


def too_big(size_bytes):
    """Same transport limit `directz_craft.too_big` checks, for the same
    reason: this rides inline in the request body, which caps at 20MB."""
    return bool(size_bytes) and size_bytes > INLINE_MAX_MB * 1024 * 1024
