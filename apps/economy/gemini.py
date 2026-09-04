"""Gemini generation for Image ConnectZ (image) + Video ConnectZ (Veo video).

Uses Google's Generative Language REST API. Charges the AI-cost minimum (PromptZ
first, then cash) like the rest of the AI suite. Every endpoint 503s cleanly
when GEMINI_API_KEY isn't configured, so the client falls back gracefully.

Model names are env-overridable since Google revises them often — and, since
one of those revisions took the Boss Take coach down mid-promotion, they are
CHAINS rather than single names. See MODEL_CHAINS below.
"""
import logging
import os

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
    # Text in, AUDIO out — KeyConnectZ's server voice, for the languages a
    # phone has no voice of its own for. A separate chain because the TTS
    # models are separate names: asking gemini-2.5-flash for
    # responseModalities:["AUDIO"] is a 400, not a fallback.
    "tts": (
        "gemini-2.5-flash-preview-tts",
        "gemini-2.5-pro-preview-tts",
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
