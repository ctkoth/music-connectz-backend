"""Gemini generation for Image ConnectZ (image). Video lives in videoz.py.

Uses Google's Generative Language REST API. Charges the AI-cost minimum (PromptZ
first, then cash) like the rest of the AI suite. Every endpoint 503s cleanly
when GEMINI_API_KEY isn't configured, so the client falls back gracefully.

Model names are env-overridable since Google revises them often — and, since
one of those revisions took the Boss Take coach down mid-promotion, they are
CHAINS rather than single names. See MODEL_CHAINS below.
"""
import base64
import binascii
import logging
import os
import time

import requests
from django.conf import settings
from django.core.files.base import ContentFile

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import imagez
from .catalog import ai_cost
from .media import stable_media_url
from .models import (GeneratedImage, Upload, can_afford_ai, charge_ai_usage,
                     daily_prompt_covers, daily_prompt_state, wallet_for)
from .views import credit_owner

# Mapping is deliberately small: these are the only MIME types Gemini's image
# models return. An unlisted one still saves — just under a generic name —
# rather than 500ing on a format we didn't expect.
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def _image_dict(work, request=None):
    up = work.upload
    return {
        "id": work.id, "prompt": work.prompt, "created_at": work.created_at,
        "kind": work.kind, "upload_id": up.id if up else None,
        # None when the file itself was later removed from the uploads screen —
        # the record still says what was made, same as MasterWork.
        "url": stable_media_url(up, request) if up else None,
    }

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
            r = requests.get(f"{BASE}/models", params={"pageSize": 200},
                             headers=_auth(key), timeout=20)
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
                             headers=_auth(key), json=body, timeout=timeout)
        if resp.status_code != 404:
            if resp.status_code == 200:
                _remember(kind, model)
            return resp, tried
        logger.warning("%s: model %s isn't available to this key — trying the next one", label, model)
        _forget(kind, model)
    return resp, tried


def _key():
    return getattr(settings, "GEMINI_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")


def _auth(key):
    """The key goes in a header, never in the URL.

    `?key=` put the API key in every request line, and `requests` writes the
    request line into the message of the exceptions it raises ("Max retries
    exceeded with url: /v1beta/models/…:generateContent?key=AIza…"). Several
    callers log those and one used to return them to the member, so a DNS blip
    could print part of the key into a log or a response. The header is the
    documented alternative and is not part of any exception message.
    """
    return {"x-goog-api-key": key}


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
        covered_free = daily_prompt_covers(cost) and daily_left > 0
    remaining = charge_ai_usage(user, cost, note=note, count_daily=count_daily)
    if remaining is None:
        return None
    if covered_free:
        # Nothing left the member's wallet, so nothing may arrive in the
        # owner's — otherwise the platform mints money out of an allowance.
        return 0
    credit_owner(user, cost, note)
    return cost


# What Image ConnectZ tells a member when Gemini fails. Fixed sentences: the
# exception text and Google's error body stay in the log.
IMAGE_DOWN = "The image service didn't answer — nothing was charged."
IMAGE_EMPTY = ("The image service didn't return a picture for that. Nothing was charged — "
               "try different wording, or try again in a little while.")


def draw_image(key, parts, timeout=90):
    """One image generation call. Returns (base64_data, mime) or (None, None); never
    raises for a bad answer (Google's text is logged, never shown)."""
    model = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image-preview")
    try:
        r = requests.post(f"{BASE}/models/{model}:generateContent", headers={"x-goog-api-key": key},
                          json={"contents": [{"parts": parts}],
                                "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}},
                          timeout=timeout)
        data = r.json()
    except Exception:
        logger.exception("draw_image: the Gemini call failed")
        return None, None
    for part in (data.get("candidates") or [{}])[0].get("content", {}).get("parts", []):
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            return inline["data"], inline.get("mimeType") or inline.get("mime_type") or "image/png"
    logger.error("draw_image: no image — Gemini %s: %s", getattr(r, "status_code", 0),
                 str((data.get("error") or {}).get("message") or "no error message")[:300])
    return None, None


INSPIRATION_IMAGE_NOTE = ("Inspiration: pick a cover you love and the new one borrows its style, palette, "
                          "lighting and mood — never its people, text, logos or artwork. The picture is used "
                          "for this one image and isn't kept.")
INSPIRATION_WRAP = (
    "The attached image is INSPIRATION ONLY. Take from it the colour palette, lighting, composition, texture, "
    "mood and general style. Do NOT copy it, trace it, or reproduce any person, face, logo, lettering, brand or "
    "recognisable artwork from it. Make a new, original picture for this request: ")


def self_faces(user):
    """The member's FaceZ photos that may stand for THEM: theirs, not tagged as anyone else."""
    from django.db.models import Q
    from .models import Face
    return Face.objects.filter(owner=user).exclude(image="").filter(Q(tagged__isnull=True) | Q(tagged=user))


_FACE_MIME = {".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def face_reference(user, face_id):
    """(data URL, None) for one of the member's own faces, or (None, why)."""
    try:
        face = self_faces(user).filter(pk=int(face_id)).first()
    except (TypeError, ValueError):
        face = None
    if not face:
        return None, "Only your own FaceZ photo of yourself can be used — not one tagged as somebody else."
    try:
        with face.image.open("rb") as fh:
            raw = fh.read()
    except Exception:
        return None, "That FaceZ photo couldn't be read from storage. Pick another or upload one."
    ext = os.path.splitext(face.image.name)[1].lower()
    return f"data:{_FACE_MIME.get(ext, 'image/jpeg')};base64,{base64.b64encode(raw).decode()}", None


class GeminiImageView(APIView):
    """GET: images you've made. POST { prompt } → a generated image, kept."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        works = GeneratedImage.objects.filter(user=request.user).select_related("upload")[:30]
        _, _, daily_left = daily_prompt_state(request.user)
        allowance, _, _ = daily_prompt_state(request.user)
        return Response({"images": [_image_dict(w, request) for w in works],
                         # A picture is never covered by the daily free prompts (see _bill):
                         # saying "free today" here would be a price that turns into a bill.
                         "cost_cents": ai_cost("standard"), "free_today": False,
                         "cost_note": "Pictures aren't covered by the daily free prompts. A run that fails isn't charged.",
                         "daily_prompts": allowance, "daily_prompts_left": daily_left,
                         "configured": bool(_key()),
                         "inspiration_note": INSPIRATION_IMAGE_NOTE, **imagez.catalogue(),
                         # Saved FaceZ photos the member may use as their own likeness: theirs, and
                         # not tagged as somebody else.
                         "faces": [{"id": f.id, "name": f.name, "url": request.build_absolute_uri(f.image.url)}
                                   for f in self_faces(request.user)[:30]]})

    def post(self, request):
        data = request.data or {}
        prompt = str(data.get("prompt", "")).strip()[:1000]
        kind, style, mood, colours, words = imagez.clean_options(data)
        if not prompt and not kind:
            return Response({"detail": "Pick what it's for, or describe the picture."},
                            status=status.HTTP_400_BAD_REQUEST)
        likeness = str(data.get("reference_mode", "")).lower() == "me"
        if likeness:
            if not imagez.KINDS.get(kind, {}).get("likeness"):
                return Response({"detail": "Your photo can only be used on a picture that's of you — "
                                           "a profile picture, avatar, cover, thumbnail, post or flyer."},
                                status=status.HTTP_400_BAD_REQUEST)
            if str(data.get("confirm_self", "")).lower() not in ("1", "true", "yes", "on"):
                return Response({"detail": "Confirm the photo is of you. " + imagez.LIKENESS_NOTE},
                                status=status.HTTP_400_BAD_REQUEST)
            if data.get("face_id") not in (None, ""):
                ref, why = face_reference(request.user, data.get("face_id"))
                if why:
                    return Response({"detail": why}, status=status.HTTP_400_BAD_REQUEST)
                data = {**data, "reference": ref}
            if not data.get("reference"):
                return Response({"detail": "Pick your photo first."}, status=status.HTTP_400_BAD_REQUEST)
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
        inspiration = str((request.data or {}).get("inspiration", "")).lower() in ("1", "true", "yes", "on")
        if inspiration and not (request.data or {}).get("reference"):
            return Response({"detail": "Pick a picture for Inspiration first.", "image": None},
                            status=status.HTTP_400_BAD_REQUEST)
        if likeness:
            inspiration = False
        framed = imagez.build_prompt(prompt, kind, style, mood, colours, words)
        wrap = INSPIRATION_WRAP if inspiration else imagez.LIKENESS_WRAP if likeness else ""
        parts = [{"text": wrap + framed}]
        aspect = imagez.KINDS.get(kind, {}).get("aspect")
        reference = data.get("reference")
        if isinstance(reference, str) and reference.startswith("data:") and "," in reference:
            header, b64 = reference.split(",", 1)
            ref_mime = header.split(";")[0].split(":")[-1] or "image/jpeg"
            parts.insert(0, {"inlineData": {"mimeType": ref_mime, "data": b64}})
        try:
            # The key rides in a header, not the query string. `requests` names
            # the full URL in every connection error it raises, and this view
            # used to hand `str(exc)` to the member — so a dropped connection
            # printed part of GEMINI_API_KEY on their screen.
            # The frame shape rides in imageConfig where the model takes it. A model that
            # refuses the field answers without an image, so the same request goes once
            # more without it — the shape is also in the prompt, so it is still asked for.
            img, mime = None, "image/png"
            for with_aspect in ((True, False) if aspect else (False,)):
                config = {"responseModalities": ["IMAGE", "TEXT"]}
                if with_aspect:
                    config["imageConfig"] = {"aspectRatio": aspect}
                r = requests.post(
                    f"{BASE}/models/{model}:generateContent",
                    headers={"x-goog-api-key": key},
                    json={"contents": [{"parts": parts}], "generationConfig": config},
                    timeout=90,
                )
                data = r.json()
                for part in (data.get("candidates") or [{}])[0].get("content", {}).get("parts", []):
                    inline = part.get("inlineData") or part.get("inline_data")
                    if inline and inline.get("data"):
                        img = inline["data"]; mime = inline.get("mimeType") or inline.get("mime_type") or mime
                        break
                if img:
                    break
            if not img:
                # Google's own words are for the log, not the screen: they are a
                # third party's text and can carry a project number or quota name.
                logger.error("Image ConnectZ: no image — Gemini %s: %s", r.status_code,
                             str((data.get("error") or {}).get("message") or "no error message")[:300])
                return Response({"detail": IMAGE_EMPTY, "image": None}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception:
            logger.exception("Image ConnectZ: the Gemini call failed")
            return Response({"detail": IMAGE_DOWN, "image": None}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        cost = _bill(request.user, f"Image ConnectZ (Gemini)")

        # The spend is already charged above — a storage failure past this
        # point must not look like a refusal, so it's logged, never raised.
        # The member still gets their image in the response either way;
        # only the "kept" copy is at risk, and that's the half we can afford
        # to lose on a bad day, not the half we already billed for.
        work = None
        try:
            raw = base64.b64decode(img)
            name = f"image-connectz-{int(time.time() * 1000)}.{_EXT.get(mime, 'png')}"
            up = Upload(user=request.user, name=name, size_bytes=len(raw), content_type=mime)
            up.file.save(name, ContentFile(raw), save=False)
            up.save()
            label = imagez.KINDS.get(kind, {}).get("label", "")
            work = GeneratedImage.objects.create(user=request.user, kind=kind, upload=up,
                                                 prompt=prompt or label or "Image")
        except (binascii.Error, ValueError, OSError):
            logger.exception("Image ConnectZ: billed but couldn't save a kept copy")

        return Response({"image": f"data:{mime};base64,{img}", "work": _image_dict(work, request) if work else None,
                          "cost_cents": cost, "money": round(wallet_for(request.user).money_cents / 100, 2)})
