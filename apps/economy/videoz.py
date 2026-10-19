"""Video ConnectZ — music, bio and promo videos, optionally built around the
member's own FaceZ photo.

Video is long-running (a minute or more) and expensive per second, so the
billing is shaped differently from the text writers:

  * the price is published by GET and stated before anything starts;
  * it is HELD when the render starts — PromptZ first, then cash, recorded
    exactly — and handed back in full if the render fails or never arrives;
  * it reaches the owner only when a video actually lands.

The finished file is downloaded HERE and stored as the member's own Upload,
served from our media route. The provider's link needs the API key appended,
and the endpoint this replaces handed that link — key included — to the
browser. The key never leaves the server now.

PRICE: `VIDEO_CONNECTZ_CENTS` (env). Veo is billed by the provider per second
of video, which is dollars per clip, not cents; the default is set so the
platform cannot lose money on a render while the real price is decided.

Lipsync to a member's track (StatZ, per the brief) needs a lipsync provider
this codebase has no account with, so it is not offered — no control appears
for a thing that cannot run.
"""
import base64
import logging
import os
import time
from datetime import timedelta

import requests
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .gemini import BASE, _key
from .catalog import over_char_limit
from .models import (Face, Transaction, Upload, VideoWork, is_platform_owner, membership_for,
                     wallet_for)
from .media import stable_media_url
from .views import credit_owner

logger = logging.getLogger(__name__)

ROYALTY_PCT = 10
GIVE_UP_AFTER = timedelta(minutes=20)
# The photo's type from its extension. FaceZ accepts WebP, and labelling those bytes
# image/jpeg made Google reject the start and the member was told to reword.
_IMAGE_MIME = {".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
# How long an UNANSWERED status check may keep a render open. Google keeps a finished
# video for days, so an outage on our side or theirs is no reason to refund early.
HARD_GIVE_UP_AFTER = timedelta(hours=6)
# Veo 3 renders one fixed-length clip per request. Quoted from the provider's
# documentation and NOT checked against a live render (CI has no key), so if a
# real clip comes back a different length this is the one number to change —
# the screen reads it from GET rather than typing it.
CLIP_SECONDS = 8
# What the price buys, stated before the button. The sound is the model's own:
# the member's music is never mixed in (lipsync is not offered — see above).
WHAT_YOU_GET = (f"One clip of about {CLIP_SECONDS} seconds, with sound the model generates alongside the "
                "picture — it is not your track, and your music is not added. A render that fails or "
                "never arrives is refunded in full.")
# While one request is downloading a finished video it writes this + the epoch
# into `VideoWork.error` (empty on every pending row otherwise), so an
# overlapping poll sees the claim and does not fetch the same bytes. It lives in
# that column because the model is not ours to change from here; `_work_dict`
# never shows it. A claim older than CLAIM_STALE_SECONDS belongs to a request
# that died, and is taken over — the download itself times out at 120s.
FETCH_CLAIM = "fetching:"
CLAIM_STALE_SECONDS = 180
ASPECTS = ("16:9", "9:16")
MODELS = ("veo-3.0-fast-generate-001", "veo-3.0-generate-001", "veo-3.0-generate-preview")
KINDS = {
    "music": {"label": "Music video", "emoji": "🎬",
              "ask": "A cinematic music video shot: performance energy, dynamic camera, lighting that moves with the beat."},
    "bio": {"label": "Bio video", "emoji": "🪪",
            "ask": "A personal artist bio piece: intimate, documentary feel, the artist in their world."},
    "promo": {"label": "Promo video", "emoji": "📣",
              "ask": "A short promotional clip for a release or show: bold, punchy, made to stop a scroll."},
}


# Corey's call: a video costs 2 PromptZ a clip (a stitched one, 2 per shot), not
# hundreds. This is BELOW what the provider charges per clip, so every render is a
# subsidy; VIDEO_CONNECTZ_CENTS raises it without a deploy of code.
DEFAULT_PRICE = 2


def price_cents():
    try:
        return max(1, int(os.environ.get("VIDEO_CONNECTZ_CENTS", str(DEFAULT_PRICE))))
    except ValueError:
        return DEFAULT_PRICE


def _auth(key):
    return {"x-goog-api-key": key}


def _models():
    env = os.environ.get("GEMINI_VIDEO_MODEL", "").strip()
    return ([env] if env else []) + [m for m in MODELS if m != env]


@transaction.atomic
def hold(user, cost):
    """Take `cost` (PromptZ first, then cash) and say exactly how, or None."""
    w = type(wallet_for(user)).objects.select_for_update().get(pk=wallet_for(user).pk)
    if (w.promptz or 0) + w.money_cents < cost:
        if not is_platform_owner(user):
            return None
        # The owner pays the provider directly: render with nothing held. Zero
        # held means a refund hands back zero, and LogZ still shows the render.
        Transaction.objects.create(user=user, kind=Transaction.KIND_SPEND, amount_cents=0, dev_tax_cents=0,
                                   note="Video ConnectZ — owner, balance short, not charged")
        return 0, 0
    p = min(w.promptz or 0, cost)
    c = cost - p
    w.promptz -= p
    w.money_cents -= c
    w.save(update_fields=["promptz", "money_cents", "updated_at"])
    Transaction.objects.create(user=user, kind=Transaction.KIND_SPEND, amount_cents=-c, dev_tax_cents=0,
                               note=(f"Video ConnectZ — held while it renders" + (f" · {p}🏷️" if p else ""))[:200])
    return p, c


@transaction.atomic
def refund(work, why):
    """Hand a held price back — once.

    The guard used to be `work.status` on the CALLER'S instance. Every GET reads
    the row fresh and then polls it, so two requests could each hold a copy that
    still said "pending", and each refunded: cash minted by polling. The row is
    locked and re-read here, so the answer to "is this still pending?" comes from
    the database at the moment of the refund. Lock order is the work row and then
    the wallet, the same as the success path in `poll`.
    """
    row = VideoWork.objects.select_for_update().filter(pk=work.pk).first()
    if row is None or row.status != VideoWork.STATUS_PENDING:
        # Somebody else already refunded it, or the video landed and was paid
        # for. Say so on the caller's copy too, so it doesn't go on believing.
        if row is not None:
            work.status, work.error = row.status, row.error
        return
    w = type(wallet_for(row.user)).objects.select_for_update().get(pk=wallet_for(row.user).pk)
    w.promptz = (w.promptz or 0) + row.held_promptz
    w.money_cents += row.held_cash
    w.save(update_fields=["promptz", "money_cents", "updated_at"])
    Transaction.objects.create(user=row.user, kind=Transaction.KIND_REWARD, amount_cents=row.held_cash,
                               dev_tax_cents=0,
                               note=(f"Video ConnectZ refund — {why}" +
                                     (f" · {row.held_promptz}🏷️" if row.held_promptz else ""))[:200])
    row.status, row.error = VideoWork.STATUS_FAILED, why[:200]
    row.save(update_fields=["status", "error"])
    work.status, work.error = row.status, row.error


def _claim_download(work):
    """Claim the right to fetch this render's bytes. The marker, or None.

    One conditional UPDATE, so of any number of overlapping polls exactly one
    gets a row count of 1. A claim old enough to belong to a dead request is
    taken over with a second conditional UPDATE on the exact stale value.
    """
    now = int(time.time())
    marker = f"{FETCH_CLAIM}{now}"
    pending = VideoWork.objects.filter(pk=work.pk, status=VideoWork.STATUS_PENDING)
    if pending.filter(error="").update(error=marker):
        return marker
    current = pending.values_list("error", flat=True).first() or ""
    if current.startswith(FETCH_CLAIM):
        try:
            age = now - int(current[len(FETCH_CLAIM):])
        except ValueError:
            age = CLAIM_STALE_SECONDS + 1
        if age > CLAIM_STALE_SECONDS and pending.filter(error=current).update(error=marker):
            return marker
    return None


def _release_download(work, marker):
    """Give the claim back — only if it is still ours and the render still pending."""
    VideoWork.objects.filter(pk=work.pk, status=VideoWork.STATUS_PENDING, error=marker).update(error="")


def _upstream_message(resp):
    """The provider's own words for why it refused, lower-cased, for READING only.

    It is never forwarded to the member: it is a third party's text and can carry
    a project number or a quota name. We read it to decide whose fault this was.
    """
    if resp is None:
        return ""
    try:
        msg = ((resp.json() or {}).get("error") or {}).get("message") or ""
    except Exception:
        msg = ""
    return str(msg or getattr(resp, "text", "") or "").lower()


# Words that mean the PROVIDER refused the content, as against refusing us.
_WORDING_WORDS = ("safety", "responsible ai", "violat", "sensitive", "prohibited", "policy", "blocked",
                  "not allowed", "inappropriate", "celebrit", "copyright")
_OUR_END_WORDS = ("api key", "api_key", "quota", "billing", "permission", "credential", "not enabled",
                  "unauthenticated", "rate limit")


def start_failure(resp):
    """(reason, sentence for the screen, short text stored on the failed work).

    Every failed start used to answer "try rewording it" — including when OUR key
    or quota was the problem, which sends a member off to rewrite a good
    description. Whose fault it was is a fact about the status code first:

      429 / 401 / 403 / 404 / 5xx / no answer at all — ours (key, quota, outage,
          a model name that has gone). Nothing the member can fix.
      400 — it depends what it says: the content (reword), the photo, or an
          invalid key that Google reports as a 400.
    """
    code = getattr(resp, "status_code", 0)
    msg = _upstream_message(resp)
    kept = "Nothing was charged — your PromptZ/balance is back."
    ours = ("unavailable",
            f"The video service is unavailable at our end right now. {kept} Try again in a little while.",
            "the video service is unavailable")
    if code in (0, 401, 403, 404, 429) or code >= 500 or code == 200:
        return ours
    if code == 400:
        if any(w in msg for w in _OUR_END_WORDS):
            return ours
        if any(w in msg for w in _WORDING_WORDS):
            return ("wording",
                    f"The video service wouldn't make that one. {kept} Try rewording the description.",
                    "the description was refused")
        if "image" in msg or "photo" in msg:
            return ("photo",
                    f"The video service couldn't use that photo. {kept} Try a different FaceZ photo, "
                    "or make the video without one.",
                    "the photo wasn't accepted")
    return ("unknown",
            f"The video service didn't accept that request. {kept} Try again, and if it keeps happening "
            "change the description.",
            "the video service refused the request")


def _work_dict(w, request):
    return {"id": w.id, "kind": w.kind, "label": KINDS.get(w.kind, {}).get("label", w.kind), "prompt": w.prompt,
            "aspect": w.aspect, "status": w.status,
            # A pending row's `error` is the download claim (see FETCH_CLAIM),
            # never something to show; a reason exists only once it has failed.
            "error": w.error if w.status == VideoWork.STATUS_FAILED else "",
            "face_id": w.face_id,
            "video_url": stable_media_url(w.upload, request) if w.upload_id else None,
            "price_cents": w.held_promptz + w.held_cash, "created_at": w.created_at.isoformat(),
            "royalty_pct": ROYALTY_PCT}


class VideoView(APIView):
    """GET: kinds, price, your faces and renders. POST: start one."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        w = wallet_for(request.user)
        cost = price_cents()
        return Response({
            "configured": bool(_key()),
            "kinds": [{"key": k, "label": v["label"], "emoji": v["emoji"]} for k, v in KINDS.items()],
            "aspects": list(ASPECTS),
            "price_cents": cost,
            # What the price buys, for the line beside the button — before it is pressed.
            "what_you_get": WHAT_YOU_GET, "clip_seconds": CLIP_SECONDS,
            "promptz": w.promptz or 0, "money_cents": w.money_cents,
            "can_afford": is_platform_owner(request.user) or (w.promptz or 0) + w.money_cents >= cost,
            "faces": [{"id": f.id, "url": request.build_absolute_uri(f.image.url)}
                      for f in Face.objects.filter(owner=request.user).exclude(image="")[:30]],
            "royalty_pct": ROYALTY_PCT,
            "royalty_rule": f"Using one in DistributeZ, CollabZ or BattleZ pays K-Oth {ROYALTY_PCT}% of what you earn from it.",
            "works": [_work_dict(x, request) for x in VideoWork.objects.filter(user=request.user)[:20]],
        })

    def post(self, request):
        d = request.data or {}
        kind = str(d.get("kind", ""))
        prompt = str(d.get("prompt", "")).strip()
        aspect = str(d.get("aspect", "16:9"))
        if kind not in KINDS:
            return Response({"detail": "Pick a music, bio or promo video."}, status=status.HTTP_400_BAD_REQUEST)
        if not prompt:
            return Response({"detail": "Describe the video."}, status=status.HTTP_400_BAD_REQUEST)
        cap = over_char_limit(prompt, membership_for(request.user).tier)
        if cap:
            return Response({"detail": f"Your tier writes up to {cap:,} characters here — upgrade in MembershipZ for more.", "char_limit": cap},
                            status=status.HTTP_400_BAD_REQUEST)
        if aspect not in ASPECTS:
            return Response({"detail": "16:9 or 9:16."}, status=status.HTTP_400_BAD_REQUEST)
        face = None
        if d.get("face_id"):
            face = Face.objects.filter(pk=d.get("face_id"), owner=request.user).first()
            if not face:
                return Response({"detail": "Only your own FaceZ photos can be used."}, status=status.HTTP_400_BAD_REQUEST)
        work, refusal = start_render(request.user, kind, prompt, aspect, face)
        if refusal is not None:
            return refusal
        return Response(_work_dict(work, request), status=status.HTTP_201_CREATED)


def start_render(user, kind, prompt, aspect, face=None):
    """Hold the price and start ONE render. Returns (work, None) or (None, Response).

    Shared by the single-clip screen and the stitched music video, so a shot is
    priced, held, refused and refunded by exactly the same code as a clip.
    """
    key = _key()
    if not key:
        return None, Response({"detail": "Video ConnectZ isn't switched on — the backend is missing GEMINI_API_KEY."},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)
    cost = price_cents()
    held = hold(user, cost)
    if held is None:
        return None, Response({"detail": "Not enough PromptZ or balance for a video.", "price_cents": cost},
                        status=status.HTTP_402_PAYMENT_REQUIRED)
    work = VideoWork.objects.create(user=user, kind=kind, prompt=prompt, aspect=aspect, face=face,
                                    held_promptz=held[0], held_cash=held[1])
    instance = {"prompt": f"{KINDS[kind]['ask']} {prompt}"}
    if face:
        try:
            face.image.open("rb")
            raw = face.image.read()
            face.image.close()
            ext = os.path.splitext(face.image.name)[1].lower()
            instance["image"] = {"bytesBase64Encoded": base64.b64encode(raw).decode("ascii"),
                                 "mimeType": _IMAGE_MIME.get(ext, "image/jpeg")}
        except Exception:
            refund(work, "your FaceZ photo couldn't be read")
            return None, Response({"detail": "Your FaceZ photo couldn't be read. Nothing was charged."},
                            status=status.HTTP_400_BAD_REQUEST)
    body = {"instances": [instance], "parameters": {"aspectRatio": aspect}}
    op, last = "", None
    try:
        for model in _models():
            # The key rides in a header, never the query string: `requests`
            # puts the URL in every connection error it raises, and
            # `logger.exception` below writes those to the log.
            last = requests.post(f"{BASE}/models/{model}:predictLongRunning",
                                 headers=_auth(key), json=body, timeout=60)
            if last.status_code != 404:
                op = (last.json() or {}).get("name", "") if last.status_code == 200 else ""
                break
    except requests.RequestException:
        logger.exception("Video ConnectZ: could not reach Veo")
        last = None
    if not op:
        logger.error("Video ConnectZ: start failed %s — %s", getattr(last, "status_code", 0),
                     getattr(last, "text", "")[:300])
        reason, sentence, stored = start_failure(last)
        refund(work, stored)
        return None, Response({"detail": sentence, "reason": reason, "refunded": True},
                        status=status.HTTP_502_BAD_GATEWAY)
    work.operation = op
    work.save(update_fields=["operation"])
    return work, None


class VideoDetailView(APIView):
    """GET — where a render is; finishes it (download, store, bill) when ready."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        work = VideoWork.objects.filter(pk=pk, user=request.user).first()
        if not work:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if work.status == VideoWork.STATUS_PENDING:
            poll(work)
            work.refresh_from_db()
        return Response(_work_dict(work, request))


def poll(work):
    # GIVE_UP_AFTER is when we stop expecting it, not when we stop LOOKING. It used
    # to refund on the clock before asking the provider anything, so a member who
    # closed the tab for twenty-one minutes lost a render Google had finished and
    # got their money back for something that existed — the owner unpaid, the
    # video gone. The provider is asked first, every time. Only a render that is
    # still not done past the limit is refunded, and an unanswered question waits
    # (up to HARD_GIVE_UP_AFTER) rather than being read as "it never finished".
    age = timezone.now() - work.created_at
    expired = age > GIVE_UP_AFTER
    key = _key()
    if not key or not work.operation:
        if age > HARD_GIVE_UP_AFTER:
            refund(work, "it never finished")
        return
    try:
        data = requests.get(f"{BASE}/{work.operation}", headers=_auth(key), timeout=20).json()
    except (requests.RequestException, ValueError):
        if age > HARD_GIVE_UP_AFTER:
            refund(work, "it never finished")
        return  # transient — the next poll asks again
    if not data.get("done"):
        if expired:
            refund(work, "it never finished")
        return
    if data.get("error"):
        refund(work, str((data["error"] or {}).get("message", "the render failed"))[:120])
        return
    resp = data.get("response") or {}
    samples = ((resp.get("generateVideoResponse") or {}).get("generatedSamples")
               or resp.get("generatedSamples") or [])
    uri = samples and ((samples[0].get("video") or {}).get("uri") or samples[0].get("uri"))
    if not uri:
        refund(work, "no video came back (it may have been filtered)")
        return
    # Claim the download BEFORE making it. The member's screen polls and so can
    # a second tab; each used to see "done" and each fetched the whole video,
    # keeping one. Only the request that wins the claim goes for the bytes.
    marker = _claim_download(work)
    if not marker:
        return  # another request is already fetching this one
    try:
        try:
            r = requests.get(uri, headers=_auth(key), timeout=120)
            r.raise_for_status()
        except requests.RequestException:
            return  # the claim is released below, so the next poll tries again
        with transaction.atomic():
            work = VideoWork.objects.select_for_update().get(pk=work.pk)
            if work.status != VideoWork.STATUS_PENDING:
                return
            up = Upload(user=work.user, name=f"video-connectz-{work.id}.mp4", size_bytes=len(r.content),
                        content_type="video/mp4")
            up.file.save(up.name, ContentFile(r.content), save=False)
            up.save()
            work.upload, work.status, work.error = up, VideoWork.STATUS_DONE, ""
            work.save(update_fields=["upload", "status", "error"])
    finally:
        _release_download(work, marker)
    credit_owner(work.user, work.held_promptz + work.held_cash, f"Video ConnectZ — {work.kind} video")
