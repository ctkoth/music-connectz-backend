"""A sound or a picture as the starting point for a maker — the "any medium" prompt, step one.

Corey: members should be able to give the makers any medium, or a combination, not only words.
An AUDIO clip or a PICTURE, optional, alongside the words: the writer (every kind but a legal
draft), the instrumental maker, MangaZ's script, Video ConnectZ's Direct plan, and the
video renders — where it is first read into a look-and-feel line (`describe`), because Veo takes a
picture only as the first frame. The image maker and LookZMaxZ have their own.

Four rules, each from something else in this codebase:

* **Validated BEFORE anything is charged.** An unreadable or oversized reference is a 400 with a
  sentence and no price, the same rule the coach bills on.
* **Never kept.** It rides to the model in the request and nowhere else: no Upload row, no file,
  nothing stored (the same line matchref draws for a reference song).
* **Inspiration only, in the prompt, in the server's words.** Whatever the member attached, the
  model is told to take mood, energy, theme and feel and NEVER to reproduce its melody, lyrics,
  or distinctive phrases or imitate a named artist. A reference is a direction, not a source.
* **Closed list of types and a size ceiling.** Gemini's inline path caps the whole request, so
  the file is capped well under it; the screen says the ceiling before a file is picked.
"""
import base64
import binascii

MAX_BYTES = 6 * 1024 * 1024            # decoded; ~ a minute of mp3 or a large photo
AUDIO = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/webm", "audio/ogg",
         "audio/flac", "audio/aac", "audio/mp4", "audio/x-m4a", "audio/m4a"}
IMAGE = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_RELABEL = {"audio/mp3": "audio/mpeg", "audio/x-wav": "audio/wav", "audio/x-m4a": "audio/mp4",
            "audio/m4a": "audio/mp4"}

GUARD = (
    "\n\nThe author attached a reference {kind}. Take its mood, energy, theme and feel as "
    "inspiration ONLY. Do not reproduce its melody, words, lyrics or distinctive phrases, and do "
    "not name or imitate a specific artist or copyrighted work. Make something new.")


def parse(raw, allow=("audio", "image")):
    """(ref, None) or (None, "the sentence for the member"). `raw` is a data URL, or empty for none."""
    if not raw:
        return None, None
    if not isinstance(raw, str) or not raw.startswith("data:") or "," not in raw:
        return None, "That reference didn't arrive as a file the maker can read."
    header, b64 = raw.split(",", 1)
    mime = header[5:].split(";")[0].strip().lower()
    mime = _RELABEL.get(mime, mime)
    kind = "audio" if mime in AUDIO | {"audio/mpeg", "audio/wav", "audio/mp4"} else "image" if mime in IMAGE else ""
    if not kind or kind not in allow:
        return None, f"The maker can't use a {mime or 'file like that'} as a reference."
    # Cheap length check first, so a huge string is never decoded just to be refused.
    if len(b64) > MAX_BYTES * 4 // 3 + 8:
        return None, f"That reference is over {MAX_BYTES // (1024 * 1024)}MB — use a shorter clip or a smaller picture."
    try:
        size = len(base64.b64decode(b64, validate=True))
    except (binascii.Error, ValueError):
        return None, "That reference didn't arrive as a file the maker can read."
    if not size:
        return None, "That reference file is empty."
    if size > MAX_BYTES:
        return None, f"That reference is over {MAX_BYTES // (1024 * 1024)}MB — use a shorter clip or a smaller picture."
    return {"kind": kind, "mime": mime, "b64": b64}, None


def part(ref):
    """The Gemini part for a parsed reference."""
    return {"inlineData": {"mimeType": ref["mime"], "data": ref["b64"]}}


def guard(ref):
    return GUARD.format(kind=ref["kind"]) if ref else ""


DESCRIBE = (
    "A video maker attached this {kind} as INSPIRATION for a new music video. In one or two "
    "sentences (under 60 words), describe only the feel a shot could borrow from it: mood, colour "
    "palette, light, pace, energy, setting. Never name a person, a brand, an artist, a song or a "
    "copyrighted work; never describe a face or a body; never quote words. Plain text, no preamble.")
DESCRIBE_FAILED = ("The inspiration couldn't be read into a direction for the video. Nothing was "
                   "charged — try another file, or leave it off.")


def describe(ref, key, timeout=30):
    """(words, None) or (None, sentence): a reference turned into a look-and-feel line.

    For the makers that cannot take a reference as a part — Veo reads a picture as the FIRST
    FRAME, which would copy it rather than be inspired by it. The words are ours to cap and
    the guard still goes beside them in the prompt. The call is not billed: it is a tiny text
    read inside a render whose own price is already stated."""
    import requests
    from .gemini import generate_content
    if not ref:
        return "", None
    body = {"contents": [{"parts": [{"text": DESCRIBE.format(kind=ref["kind"])}, part(ref)]}],
            "generationConfig": {"temperature": 0.4}}
    try:
        resp, _ = generate_content("text", body, key=key, timeout=timeout, label="inspiration")
        text = "".join(str(x.get("text", "")) for x in resp.json()["candidates"][0]["content"]["parts"])
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError):
        return None, DESCRIBE_FAILED
    words = " ".join(text.split())[:400]
    if not words:
        return None, DESCRIBE_FAILED
    return words, None


def video_line(words):
    """The sentence a video prompt carries for a described reference — feel only."""
    return (f" Inspiration for the feel only (do not copy any person, logo, artist or work): {words}"
            if words else "")
