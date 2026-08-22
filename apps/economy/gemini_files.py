"""Send the model a file too big to inline: Google's Files API.

The coach reads a take by base64'ing it into the `generateContent` body, and
that path caps the WHOLE request at 20MB — about 14MB of actual audio once the
encoding overhead is counted. That is `vocalcoach.MAX_MB`, and it is why a
29MB track posted on this platform could not be scored on this platform.

There is no need for a second vendor. The same API has a second way in: upload
the file first, then reference it by URI. Per Google's published limits that
path takes **2GB per file** and 20GB per project, files live for 48 hours, and
it costs nothing — the storage is free and only the generateContent call is
billed, exactly as it is today.

So the transport stops being the thing that decides what can be coached.

TWO PATHS, ON PURPOSE
---------------------
Small takes keep going inline. It is one round trip instead of three, there is
nothing to clean up afterwards, and it is the path with a year of production
behind it. The Files API is what happens when a take is too big for that — not
a replacement for it.

And if the upload path fails for any reason, the caller falls back to the
inline attempt when the file would fit. That ordering matters: this module is
new and cannot be exercised against the live API from CI, so it is built so
that the worst case is exactly today's behaviour rather than a new way to fail.
"""
import logging
import time

import requests

from .gemini import _key

logger = logging.getLogger(__name__)

# The upload host is a different path prefix from the generate host, and it is
# NOT under /v1beta directly — `/upload/v1beta/files`. Verified against the
# live API: this path answers PERMISSION_DENIED without a key (i.e. it exists),
# while a made-up sibling answers 404.
UPLOAD_BASE = "https://generativelanguage.googleapis.com/upload/v1beta/files"
FILES_BASE = "https://generativelanguage.googleapis.com/v1beta/files"

# Google's published per-file ceiling for this API.
API_MAX_MB = 2048

# How long to wait for an uploaded file to finish processing. Audio is ACTIVE
# almost immediately; video is transcoded first and takes longer the longer it
# is. Bounded, because a member is sitting in front of this.
POLL_SECONDS = 1.5
POLL_TRIES = 40


def upload(fileobj, mime_type, size_bytes, display_name="take"):
    """Put a file where generateContent can reach it. Returns (file, error).

    `file` is {"uri", "name"} — `uri` goes in the request, `name` is what
    `delete` takes. Exactly one of the two return values is None.

    Resumable in two legs, which is what this API wants even for one shot: the
    first call declares the size and type and answers with a one-time upload
    URL, the second sends the bytes to it.
    """
    key = _key()
    if not key:
        return None, "the coach isn't configured"
    try:
        start = requests.post(
            f"{UPLOAD_BASE}?key={key}",
            headers={
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(size_bytes),
                "X-Goog-Upload-Header-Content-Type": mime_type,
                "Content-Type": "application/json",
            },
            json={"file": {"display_name": str(display_name)[:120]}},
            timeout=30,
        )
    except requests.RequestException:
        logger.exception("Files API: could not reach the upload endpoint")
        return None, "couldn't reach the coach's file store"
    if start.status_code != 200:
        logger.error("Files API: start returned %s — %s",
                     start.status_code, start.text[:300])
        return None, "the coach's file store refused the upload"

    # The one-time URL comes back as a header, not in the body. Header lookup
    # is case-insensitive through requests, which is the only reason this does
    # not have to guess Google's capitalisation.
    put_url = start.headers.get("X-Goog-Upload-URL")
    if not put_url:
        logger.error("Files API: start gave no upload URL — headers=%s",
                     dict(start.headers))
        return None, "the coach's file store didn't say where to send it"

    try:
        done = requests.post(
            put_url,
            headers={
                "Content-Length": str(size_bytes),
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
            },
            data=fileobj,
            timeout=300,          # a big take over a slow link is still a take
        )
    except requests.RequestException:
        logger.exception("Files API: upload leg failed")
        return None, "the take didn't finish uploading to the coach"
    if done.status_code != 200:
        logger.error("Files API: upload returned %s — %s",
                     done.status_code, done.text[:300])
        return None, "the coach's file store wouldn't take that file"

    try:
        f = done.json()["file"]
        return {"uri": f["uri"], "name": f["name"], "state": f.get("state", "")}, None
    except (KeyError, ValueError):
        logger.error("Files API: unexpected upload reply — %s", done.text[:300])
        return None, "the coach's file store answered in a shape we don't know"


def wait_active(f):
    """Block until an uploaded file is ready to be read, or give up.

    Video is transcoded after upload and is not readable until that finishes;
    referencing it too early fails the generate call. Audio is usually ACTIVE
    on arrival, so the common case costs one cheap GET.
    """
    key = _key()
    if f.get("state") == "ACTIVE":
        return True, None
    for _ in range(POLL_TRIES):
        try:
            r = requests.get(f"{FILES_BASE}/{f['name'].split('/')[-1]}?key={key}",
                             timeout=20)
            state = r.json().get("state", "") if r.status_code == 200 else ""
        except (requests.RequestException, ValueError):
            state = ""
        if state == "ACTIVE":
            return True, None
        if state == "FAILED":
            return False, "the coach couldn't process that file"
        time.sleep(POLL_SECONDS)
    return False, "that take took too long to process — try a shorter section"


def delete(f):
    """Tidy up. Best-effort: files expire in 48 hours anyway, so failing to
    delete one is untidy, never a reason to fail the take that just worked."""
    try:
        requests.delete(f"{FILES_BASE}/{f['name'].split('/')[-1]}?key={_key()}",
                        timeout=15)
    except requests.RequestException:                    # pragma: no cover
        logger.warning("Files API: could not delete %s", f.get("name"))


def part_for(f, mime_type):
    """The generateContent part that points at an uploaded file, where an
    inline_data part would otherwise go."""
    return {"file_data": {"mime_type": mime_type, "file_uri": f["uri"]}}
