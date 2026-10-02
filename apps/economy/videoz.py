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
from .models import Face, Transaction, Upload, VideoWork, membership_for, wallet_for
from .media import stable_media_url
from .views import credit_owner

logger = logging.getLogger(__name__)

ROYALTY_PCT = 10
GIVE_UP_AFTER = timedelta(minutes=20)
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


def price_cents():
    try:
        return max(1, int(os.environ.get("VIDEO_CONNECTZ_CENTS", "400")))
    except ValueError:
        return 400


def _models():
    env = os.environ.get("GEMINI_VIDEO_MODEL", "").strip()
    return ([env] if env else []) + [m for m in MODELS if m != env]


@transaction.atomic
def hold(user, cost):
    """Take `cost` (PromptZ first, then cash) and say exactly how, or None."""
    w = type(wallet_for(user)).objects.select_for_update().get(pk=wallet_for(user).pk)
    if (w.promptz or 0) + w.money_cents < cost:
        return None
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
    if work.status != VideoWork.STATUS_PENDING:
        return
    w = type(wallet_for(work.user)).objects.select_for_update().get(pk=wallet_for(work.user).pk)
    w.promptz = (w.promptz or 0) + work.held_promptz
    w.money_cents += work.held_cash
    w.save(update_fields=["promptz", "money_cents", "updated_at"])
    Transaction.objects.create(user=work.user, kind=Transaction.KIND_REWARD, amount_cents=work.held_cash,
                               dev_tax_cents=0,
                               note=(f"Video ConnectZ refund — {why}" +
                                     (f" · {work.held_promptz}🏷️" if work.held_promptz else ""))[:200])
    work.status, work.error = VideoWork.STATUS_FAILED, why[:200]
    work.save(update_fields=["status", "error"])


def _work_dict(w, request):
    return {"id": w.id, "kind": w.kind, "label": KINDS.get(w.kind, {}).get("label", w.kind), "prompt": w.prompt,
            "aspect": w.aspect, "status": w.status, "error": w.error, "face_id": w.face_id,
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
            "promptz": w.promptz or 0, "money_cents": w.money_cents,
            "can_afford": (w.promptz or 0) + w.money_cents >= cost,
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
        key = _key()
        if not key:
            return Response({"detail": "Video ConnectZ isn't switched on — the backend is missing GEMINI_API_KEY."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        cost = price_cents()
        held = hold(request.user, cost)
        if held is None:
            return Response({"detail": "Not enough PromptZ or balance for a video.", "price_cents": cost},
                            status=status.HTTP_402_PAYMENT_REQUIRED)
        work = VideoWork.objects.create(user=request.user, kind=kind, prompt=prompt, aspect=aspect, face=face,
                                        held_promptz=held[0], held_cash=held[1])
        instance = {"prompt": f"{KINDS[kind]['ask']} {prompt}"}
        if face:
            try:
                face.image.open("rb")
                raw = face.image.read()
                face.image.close()
                ext = os.path.splitext(face.image.name)[1].lower()
                instance["image"] = {"bytesBase64Encoded": base64.b64encode(raw).decode("ascii"),
                                     "mimeType": "image/png" if ext == ".png" else "image/jpeg"}
            except Exception:
                refund(work, "your FaceZ photo couldn't be read")
                return Response({"detail": "Your FaceZ photo couldn't be read. Nothing was charged."},
                                status=status.HTTP_400_BAD_REQUEST)
        body = {"instances": [instance], "parameters": {"aspectRatio": aspect}}
        op, last = "", None
        try:
            for model in _models():
                last = requests.post(f"{BASE}/models/{model}:predictLongRunning", params={"key": key},
                                     json=body, timeout=60)
                if last.status_code != 404:
                    op = (last.json() or {}).get("name", "") if last.status_code == 200 else ""
                    break
        except requests.RequestException:
            logger.exception("Video ConnectZ: could not reach Veo")
        if not op:
            logger.error("Video ConnectZ: start failed %s — %s", getattr(last, "status_code", 0),
                         getattr(last, "text", "")[:300])
            refund(work, "the video service refused the request")
            return Response({"detail": "The video service didn't take that one. Your PromptZ/balance is back — "
                                       "try rewording it."}, status=status.HTTP_502_BAD_GATEWAY)
        work.operation = op
        work.save(update_fields=["operation"])
        return Response(_work_dict(work, request), status=status.HTTP_201_CREATED)


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
    if timezone.now() - work.created_at > GIVE_UP_AFTER:
        refund(work, "it never finished")
        return
    key = _key()
    if not key or not work.operation:
        return
    try:
        data = requests.get(f"{BASE}/{work.operation}", params={"key": key}, timeout=20).json()
    except (requests.RequestException, ValueError):
        return  # transient — the next poll asks again
    if not data.get("done"):
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
    try:
        r = requests.get(uri, params={"key": key}, timeout=120)
        r.raise_for_status()
    except requests.RequestException:
        return  # try the download again on the next poll
    with transaction.atomic():
        work = VideoWork.objects.select_for_update().get(pk=work.pk)
        if work.status != VideoWork.STATUS_PENDING:
            return
        up = Upload(user=work.user, name=f"video-connectz-{work.id}.mp4", size_bytes=len(r.content),
                    content_type="video/mp4")
        up.file.save(up.name, ContentFile(r.content), save=False)
        up.save()
        work.upload, work.status = up, VideoWork.STATUS_DONE
        work.save(update_fields=["upload", "status"])
    credit_owner(work.user, work.held_promptz + work.held_cash, f"Video ConnectZ — {work.kind} video")
