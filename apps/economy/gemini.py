"""Gemini generation for Image ConnectZ (image) + Video ConnectZ (Veo video).

Uses Google's Generative Language REST API. Charges the AI-cost minimum (PromptZ
first, then cash) like the rest of the AI suite. Every endpoint 503s cleanly
when GEMINI_API_KEY isn't configured, so the client falls back gracefully.

Model names are env-overridable since Google revises them often — and, since
one of those revisions took the Boss Take coach down mid-promotion, they are
CHAINS rather than single names. See MODEL_CHAINS below.
"""
import base64
import logging
import os
import time

import requests
from django.conf import settings

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import ai_cost
from .models import can_afford_ai, charge_ai_usage, daily_prompt_state, wallet_for
from .views import credit_owner

logger = logging.getLogger(__name__)

BASE = "https://generativelanguage.googleapis.com/v1beta"
# Uploads go to a different host path than everything else.
UPLOAD_BASE = "https://generativelanguage.googleapis.com/upload/v1beta"


# A model is a CHAIN, not a name.
#
# `models/<name>:generateContent` answers 404 when the key has no such model —
# and Google retires names on its own schedule, without asking us. Pinning one
# name means every feature built on it goes dark together the day that name
# goes, which is what took the Boss Take coach down: "the coach's model isn't
# available" on a perfectly good take.
#
# The env override still wins, because setting it is a deliberate act. What it
# no longer does is stand ALONE — a stale GEMINI_AUDIO_MODEL from a year ago
# used to be a single point of failure with no way back. Now it is the first
# guess, and a 404 falls through to the next one.
#
# Order within a chain is cheapest-that-can-do-the-job first. Every take is
# billed at the same flat prompt whichever name answers, so a fallback must
# never cost the member more than the take they were quoted.
MODEL_CHAINS = {
    # Multimodal in, text out — the vocal/rap coach and the DirectZ craft
    # rater both send media and ask for JSON back.
    "text": (
        "gemini-2.5-flash",
        "gemini-flash-latest",
        "gemini-2.0-flash",
        "gemini-2.5-pro",
    ),
}

# Proven this process: once a name answers, it goes to the front of the chain
# so the next take doesn't re-walk the 404s. Per-process and deliberately not
# persisted — a fresh worker re-checks, which is how a name coming BACK gets
# noticed without a deploy.
_proven = {}
_catalogue = None       # what ListModels said, asked at most once per process


def _remember(kind, model):
    if _proven.get(kind) != model:
        logger.info("Gemini: %s runs on %s", kind, model)
    _proven[kind] = model


def _forget(kind, model):
    if _proven.get(kind) == model:
        _proven.pop(kind, None)


def _suits_text(name):
    """Could this model take media in and give text back?

    Named exclusions rather than an allow-list: the catalogue is Google's and
    it grows. A name we don't recognise is a candidate, not a reject — the
    worst case is one wasted 400 and the next name in the chain.
    """
    if not name.startswith("gemini-"):
        return False
    return not any(bad in name for bad in
                   ("embedding", "aqa", "imagen", "veo", "-tts", "-image", "live", "native-audio"))


def _catalogue_for(kind, key):
    """What this key can ACTUALLY run, straight from the API. Asked once.

    Every name shipped in MODEL_CHAINS is a guess about someone else's
    catalogue, made at the time the file was written. This is the one source
    that cannot be out of date, so when all the guesses 404, ask.
    """
    global _catalogue
    if _catalogue is None:
        # Cached only on success. A timeout here is not an answer, and caching
        # it as one would leave a worker permanently convinced the key can run
        # nothing — the next take should get to ask again.
        try:
            r = requests.get(f"{BASE}/models", params={"key": key, "pageSize": 200}, timeout=20)
        except requests.RequestException:
            logger.exception("Gemini: could not list models")
            return []
        if r.status_code != 200:
            logger.error("Gemini ListModels %s — %s", r.status_code, r.text[:200])
            return []
        try:
            models = r.json().get("models") or []
        except ValueError:
            logger.error("Gemini ListModels: unreadable reply")
            return []
        _catalogue = [
            (m.get("name") or "").split("/")[-1] for m in models
            if "generateContent" in (m.get("supportedGenerationMethods") or [])
        ]
        logger.warning("Gemini: every shipped model name 404'd; the key can run %s",
                       ", ".join(_catalogue) or "nothing")
    if kind != "text":
        return list(_catalogue)
    names = [n for n in _catalogue if _suits_text(n)]
    # Cheap and stable first: flash before pro, GA before preview or exp.
    return sorted(names, key=lambda n: (0 if "flash" in n else 1,
                                        "preview" in n, "exp" in n, n))


def model_chain(kind, *env_vars, key=""):
    """Every model name worth trying for this kind of run, best first.

    A generator on purpose: ListModels is only called if the caller actually
    gets to the end of the shipped names, so the happy path is one request.
    """
    seen = set()

    def fresh(names):
        for name in names:
            name = (name or "").strip()
            if name and name not in seen:
                seen.add(name)
                yield name

    yield from fresh([_proven.get(kind)])
    yield from fresh(os.environ.get(v) for v in env_vars)
    yield from fresh(MODEL_CHAINS.get(kind, ()))
    if key:
        yield from fresh(_catalogue_for(kind, key))


# ---- Getting the media to the model ----
#
# There are two ways in, and the size decides which.
#
# `inline_data` carries the bytes inside the generateContent request body. That
# body caps at 20MB TOTAL and base64 inflates by 4/3, so the real ceiling on the
# file is about 15MB. That cap was the coach's advertised limit for a year, and
# it is not a number anybody chose — it is the inline path's ceiling wearing a
# product decision's clothes. A member with a 29MB take was told to go and cut
# their song up.
#
# The Files API is the other way: upload once, get a URI back, reference it from
# generateContent. Google keeps the file 48 hours and takes up to 2GB of it.
#
# So inline stays for small takes — it is one request instead of three, and most
# takes are small — and anything bigger goes up the Files API. The member is
# never asked which; the size picks.
INLINE_MAX_BYTES = 14 * 1024 * 1024

# What the Files API itself will take. Not what WE take — the coach's ceiling is
# set in vocalcoach.MAX_MB against what one request can realistically finish
# inside the deploy's worker timeout, which is far below this.
FILES_MAX_BYTES = 2 * 1024 * 1024 * 1024


def _size_of(fileobj):
    """Bytes in an open file object, without reading it into memory."""
    size = getattr(fileobj, "size", None)
    if isinstance(size, int):
        return size
    try:
        here = fileobj.tell()
        fileobj.seek(0, 2)
        size = fileobj.tell()
        fileobj.seek(here)
        return size
    except (AttributeError, OSError):            # pragma: no cover
        return None


def upload_media(key, fileobj, mime, size_bytes, *, display_name="take", timeout=90):
    """Put one file on the Files API. Returns (uri, name, error).

    Resumable rather than the simple multipart upload: the simple one has to
    buffer the whole body, and the point of this path is the files that are too
    big to hold. `data=fileobj` streams straight off disk.

    Uploading is not the end of it — a video arrives PROCESSING and cannot be
    referenced until it goes ACTIVE, so the poll is part of the upload, not an
    optimisation on top of it.
    """
    try:
        start = requests.post(
            f"{UPLOAD_BASE}/files", params={"key": key},
            headers={"X-Goog-Upload-Protocol": "resumable",
                     "X-Goog-Upload-Command": "start",
                     "X-Goog-Upload-Header-Content-Length": str(size_bytes),
                     "X-Goog-Upload-Header-Content-Type": mime,
                     "Content-Type": "application/json"},
            json={"file": {"display_name": display_name[:120]}}, timeout=30)
    except requests.RequestException:
        logger.exception("Gemini upload: could not start")
        return None, None, "couldn't reach the coach to send that take"
    if start.status_code != 200:
        logger.error("Gemini upload start %s — %s", start.status_code, start.text[:300])
        return None, None, "the coach wouldn't accept that upload"
    # Header case varies by proxy; requests' headers are case-insensitive, but
    # be explicit rather than rely on it.
    url = start.headers.get("X-Goog-Upload-URL") or start.headers.get("x-goog-upload-url")
    if not url:
        logger.error("Gemini upload start: no upload URL in %s", dict(start.headers))
        return None, None, "the coach wouldn't accept that upload"

    try:
        done = requests.post(
            url,
            headers={"Content-Length": str(size_bytes),
                     "X-Goog-Upload-Offset": "0",
                     "X-Goog-Upload-Command": "upload, finalize"},
            data=fileobj, timeout=timeout)
    except requests.RequestException:
        logger.exception("Gemini upload: send failed")
        return None, None, "that take didn't finish uploading to the coach"
    if done.status_code != 200:
        logger.error("Gemini upload %s — %s", done.status_code, done.text[:300])
        return None, None, "that take didn't finish uploading to the coach"
    try:
        info = (done.json() or {}).get("file") or {}
    except ValueError:                                   # pragma: no cover
        info = {}
    name, uri, state = info.get("name"), info.get("uri"), info.get("state")
    if not name or not uri:
        logger.error("Gemini upload: unreadable reply %s", done.text[:300])
        return None, None, "that take didn't finish uploading to the coach"
    return uri, name, None if state != "FAILED" else "the coach couldn't process that file"


def await_active(key, name, *, tries=20, every=2, timeout=15):
    """Block until an uploaded file is ACTIVE. Returns an error phrase or None.

    Audio is usually ACTIVE on arrival; video is not. The wait is bounded well
    inside the worker timeout on purpose — a request that hangs past it is
    killed with no reply at all, which the member reads as the app breaking
    rather than as a slow file.
    """
    for _ in range(tries):
        try:
            r = requests.get(f"{BASE}/{name}", params={"key": key}, timeout=timeout)
        except requests.RequestException:                # pragma: no cover
            logger.exception("Gemini file poll failed")
            return "lost track of that take while the coach was preparing it"
        if r.status_code != 200:
            logger.error("Gemini file poll %s — %s", r.status_code, r.text[:200])
            return "lost track of that take while the coach was preparing it"
        try:
            state = (r.json() or {}).get("state")
        except ValueError:                               # pragma: no cover
            state = None
        if state == "ACTIVE":
            return None
        if state == "FAILED":
            return "the coach couldn't process that file"
        time.sleep(every)
    return "that take was still being prepared when the coach had to answer — try it again"


def delete_file(key, name):
    """Remove an uploaded file. Best effort — never the reason a take fails.

    Google drops these after 48 hours anyway. Deleting straight after scoring
    means a member's recording isn't sitting on someone else's server for two
    days longer than the one request that needed it.
    """
    if not name:
        return
    try:
        requests.delete(f"{BASE}/{name}", params={"key": key}, timeout=15)
    except requests.RequestException:                    # pragma: no cover
        logger.warning("Gemini: could not delete %s", name)


def media_part(key, fileobj, mime, *, display_name="take"):
    """The generateContent part for this file, however big it is.

    Returns (part, uploaded_name, error). `uploaded_name` is set only when the
    file went up the Files API and is the caller's to delete once scored.
    """
    size = _size_of(fileobj)
    # Back to the start before anything reads it. `_size_of` restores the
    # position it found, but a caller that already touched the file would
    # otherwise send the model whatever was left — an empty take, reported as
    # a take the coach couldn't read.
    try:
        fileobj.seek(0)
    except (AttributeError, OSError):                    # pragma: no cover
        pass
    if size is not None and size > INLINE_MAX_BYTES:
        uri, name, err = upload_media(key, fileobj, mime, size, display_name=display_name)
        if err:
            return None, name, err
        err = await_active(key, name)
        if err:
            return None, name, err
        return {"file_data": {"mime_type": mime, "file_uri": uri}}, name, None
    return {"inline_data": {"mime_type": mime,
                            "data": base64.b64encode(fileobj.read()).decode()}}, None, None


def generate_content(kind, body, *, key, timeout, env_vars=(), label="Gemini"):
    """POST one generateContent, walking the chain past any model that isn't there.

    Returns (response, tried) — `response` is the first reply that was not a
    404, and `tried` is the model names used, newest last, for the log and the
    error body.

    404 is the ONE status worth retrying. It means "no such model for this
    key", which is a fact about our configuration and never about the member's
    upload. Every other status is a real answer about the request itself, and
    asking four models the same bad question doesn't get a better one — so a
    400, a 403 or a 429 stops the walk immediately.

    Raises requests.RequestException for the caller to handle, exactly as a
    bare requests.post would.
    """
    resp, tried = None, []
    for model in model_chain(kind, *env_vars, key=key):
        tried.append(model)
        resp = requests.post(f"{BASE}/models/{model}:generateContent",
                             params={"key": key}, json=body, timeout=timeout)
        if resp.status_code != 404:
            if resp.status_code == 200:
                _remember(kind, model)
            return resp, tried
        logger.warning("%s: model %s isn't available to this key — trying the next one", label, model)
        _forget(kind, model)
    return resp, tried


def _key():
    return getattr(settings, "GEMINI_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")


def _bill(user, note, count_daily=False):
    """Charge the AI minimum (PromptZ→cash) and route it to the owner.

    Returns what the member was ACTUALLY charged, which is 0 when a free daily
    prompt covered the run. It used to return the nominal cost either way, so a
    take paid for by the allowance still reported "-3 PromptZ spent" — the
    caller cannot state a price honestly if this lies about it.

    `count_daily` marks this as a genuine prompt run, so the tier's free daily
    allowance covers it before any paid balance is touched — the same rule
    AIChargeView applies. It defaults False because image and video generation
    run far more expensive models than the allowance is priced for; a flat text
    run like the vocal coach should pass True.
    """
    cost = ai_cost("standard")
    if not cost:
        return 0
    # Read the allowance before spending it: charge_ai_usage returns the same
    # money balance whether or not a free prompt was consumed.
    covered_free = False
    if count_daily:
        _, _, daily_left = daily_prompt_state(user)
        covered_free = daily_left > 0
    remaining = charge_ai_usage(user, cost, note=note, count_daily=count_daily)
    if remaining is None:
        return None
    if covered_free:
        # Nothing left the member's wallet, so nothing may arrive in the
        # owner's — otherwise the platform mints money out of an allowance.
        return 0
    credit_owner(user, cost, note)
    return cost


class GeminiImageView(APIView):
    """POST { prompt } → a generated image as a data URI. Synchronous."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        prompt = str((request.data or {}).get("prompt", "")).strip()
        if not prompt:
            return Response({"detail": "prompt required"}, status=status.HTTP_400_BAD_REQUEST)
        key = _key()
        if not key:
            return Response({"detail": "Image generation isn't configured — set GEMINI_API_KEY on the backend.", "image": None},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        cost = ai_cost("standard")
        if cost and not can_afford_ai(request.user, cost):
            return Response({"detail": "Not enough PromptZ / balance.", "cost_cents": cost}, status=status.HTTP_402_PAYMENT_REQUIRED)

        model = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image-preview")
        # Optional reference image (a data URL) — the output is generated to
        # resemble it (e.g. a cover/portrait drawn from the member's FaceZ photo).
        parts = [{"text": prompt}]
        reference = (request.data or {}).get("reference")
        if isinstance(reference, str) and reference.startswith("data:") and "," in reference:
            header, b64 = reference.split(",", 1)
            ref_mime = header.split(";")[0].split(":")[-1] or "image/jpeg"
            parts.insert(0, {"inlineData": {"mimeType": ref_mime, "data": b64}})
        try:
            r = requests.post(
                f"{BASE}/models/{model}:generateContent?key={key}",
                json={"contents": [{"parts": parts}],
                      "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}},
                timeout=90,
            )
            data = r.json()
            img, mime = None, "image/png"
            for part in (data.get("candidates") or [{}])[0].get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    img = inline["data"]; mime = inline.get("mimeType") or inline.get("mime_type") or mime
                    break
            if not img:
                detail = (data.get("error") or {}).get("message") or "No image returned."
                return Response({"detail": f"Gemini: {detail}"[:200], "image": None}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            return Response({"detail": f"Gemini error: {exc}"[:200], "image": None}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        cost = _bill(request.user, f"Image ConnectZ (Gemini)")
        return Response({"image": f"data:{mime};base64,{img}", "cost_cents": cost, "money": round(wallet_for(request.user).money_cents / 100, 2)})


class GeminiVideoView(APIView):
    """POST { prompt } → start a Veo video generation; returns an operation name
    to poll. Video gen is long-running (~1–2 min)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        prompt = str((request.data or {}).get("prompt", "")).strip()
        if not prompt:
            return Response({"detail": "prompt required"}, status=status.HTTP_400_BAD_REQUEST)
        key = _key()
        if not key:
            return Response({"detail": "Video generation isn't configured — set GEMINI_API_KEY on the backend.", "operation": None},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        cost = ai_cost("standard")
        if cost and not can_afford_ai(request.user, cost):
            return Response({"detail": "Not enough PromptZ / balance.", "cost_cents": cost}, status=status.HTTP_402_PAYMENT_REQUIRED)

        model = os.environ.get("GEMINI_VIDEO_MODEL", "veo-3.0-generate-preview")
        try:
            r = requests.post(
                f"{BASE}/models/{model}:predictLongRunning?key={key}",
                json={"instances": [{"prompt": prompt}]},
                timeout=60,
            )
            data = r.json()
            op = data.get("name")
            if not op:
                detail = (data.get("error") or {}).get("message") or "Could not start video generation."
                return Response({"detail": f"Veo: {detail}"[:200], "operation": None}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            return Response({"detail": f"Veo error: {exc}"[:200], "operation": None}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        cost = _bill(request.user, "Video ConnectZ (Veo)")
        return Response({"operation": op, "status": "pending", "cost_cents": cost})


class GeminiVideoStatusView(APIView):
    """POST { operation } → poll a Veo generation; returns { done, video_url }."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        op = str((request.data or {}).get("operation", "")).strip()
        key = _key()
        if not op or not key:
            return Response({"detail": "operation and GEMINI_API_KEY required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            r = requests.get(f"{BASE}/{op}?key={key}", timeout=30)
            data = r.json()
            if not data.get("done"):
                return Response({"done": False})
            resp = data.get("response") or {}
            uri = None
            samples = (resp.get("generateVideoResponse") or {}).get("generatedSamples") or resp.get("generatedSamples") or []
            if samples:
                uri = (samples[0].get("video") or {}).get("uri") or samples[0].get("uri")
            return Response({"done": True, "video_url": uri and f"{uri}&key={key}" if uri else None})
        except Exception as exc:
            return Response({"detail": f"Veo poll error: {exc}"[:200], "done": False}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
