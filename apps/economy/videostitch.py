"""Video ConnectZ, stitched: a music video made of several shots, with the
member's OWN track laid over it.

A single Video ConnectZ render is one ~8 second clip with sound the model makes
up. That cannot market a song, so this joins 2-6 shots into one video and puts
the member's uploaded track under them.

Every shot is an ordinary `VideoWork` started by `videoz.start_render`, so it is
priced, held, refused and refunded by exactly the code a single clip uses. This
module owns only the project around them:

  * the price is shots x the clip price and is published BEFORE anything starts;
  * if any shot cannot start, the shots already started are refunded and nothing
    is charged;
  * a shot that fails while rendering is refunded on its own and left out; the
    video is built from the shots that landed, and the screen says how many;
  * the track is the member's own upload, never anyone else's;
  * the join runs on the polling request that sees the last shot land, guarded
    by a claim so two overlapping polls do not both run ffmpeg.

If the join itself fails the shots have already been delivered and paid for, so
they stay in the member's renders as clips; there is no refund for work that
exists, and the error says so.
"""
import logging
import os
import shutil
import subprocess
import tempfile
import time

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import over_char_limit
from .media import stable_media_url
from .models import Face, Upload, VideoStitch, VideoWork, membership_for, wallet_for
from .videoz import (ASPECTS, CLIP_SECONDS, ROYALTY_PCT, _key, poll, price_cents, refund,
                     start_render)

logger = logging.getLogger(__name__)

MIN_SHOTS, MAX_SHOTS = 2, 6
CLAIM_STALE_SECONDS = 240
FFMPEG_TIMEOUT = 200
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus", ".webm")
WHAT_YOU_GET = (f"One video of up to {MAX_SHOTS * CLIP_SECONDS} seconds: your shots, joined in order, "
                "with YOUR track playing under them from the second you pick. The sound the model makes "
                "for each shot is replaced by your track. A shot that fails is refunded and left out.")


def ffmpeg_exe():
    """The system ffmpeg, else the static one bundled by imageio-ffmpeg (Render's
    python runtime has no system ffmpeg), else None."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:                                       # pragma: no cover
        return None


def is_audio(up):
    return (up.content_type or "").startswith("audio/") or os.path.splitext(up.name or "")[1].lower() in AUDIO_EXTS


def _dict(st, request):
    works = {w.id: w for w in VideoWork.objects.filter(pk__in=st.shot_order)}
    rows = [works[i] for i in st.shot_order if i in works]
    return {
        "id": st.id, "status": st.status, "error": st.error if st.status == VideoStitch.STATUS_FAILED else "",
        "aspect": st.aspect, "track_id": st.track_id, "track_start": st.track_start,
        "total": len(rows),
        "rendered": sum(1 for w in rows if w.status == VideoWork.STATUS_DONE),
        "rendering": sum(1 for w in rows if w.status == VideoWork.STATUS_PENDING),
        "failed": sum(1 for w in rows if w.status == VideoWork.STATUS_FAILED),
        "shots": [{"id": w.id, "prompt": w.prompt, "status": w.status} for w in rows],
        "video_url": stable_media_url(st.upload, request) if st.upload_id else None,
        "created_at": st.created_at.isoformat(), "royalty_pct": ROYALTY_PCT,
    }


def _fail(st, why):
    VideoStitch.objects.filter(pk=st.pk, status=VideoStitch.STATUS_PENDING).update(
        status=VideoStitch.STATUS_FAILED, error=why[:200], claim="")
    st.status, st.error = VideoStitch.STATUS_FAILED, why[:200]


def _join(st, clips):
    """ffmpeg: concat `clips` (Upload rows), lay the track over them. Returns bytes."""
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("the server has no video tool installed")
    with tempfile.TemporaryDirectory() as tmp:
        names = []
        for i, up in enumerate(clips):
            path = os.path.join(tmp, f"clip{i}.mp4")
            up.file.open("rb")
            try:
                with open(path, "wb") as fh:
                    fh.write(up.file.read())
            finally:
                up.file.close()
            names.append(path)
        listing = os.path.join(tmp, "list.txt")
        with open(listing, "w") as fh:
            fh.write("".join(f"file '{n}'\n" for n in names))
        audio = os.path.join(tmp, "track" + (os.path.splitext(st.track.name)[1] or ".mp3"))
        st.track.file.open("rb")
        try:
            with open(audio, "wb") as fh:
                fh.write(st.track.file.read())
        finally:
            st.track.file.close()
        total = len(clips) * CLIP_SECONDS
        out = os.path.join(tmp, "out.mp4")
        cmd = [exe, "-y", "-f", "concat", "-safe", "0", "-i", listing,
               "-ss", str(st.track_start), "-i", audio,
               "-map", "0:v:0", "-map", "1:a:0", "-shortest",
               "-af", f"afade=t=out:st={max(0, total - 1.5)}:d=1.5",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]
        proc = subprocess.run(cmd, capture_output=True, timeout=FFMPEG_TIMEOUT)
        if proc.returncode != 0 or not os.path.exists(out):
            logger.error("Video stitch %s: ffmpeg failed: %s", st.pk, proc.stderr[-400:].decode("utf-8", "replace"))
            raise RuntimeError("the shots could not be joined")
        with open(out, "rb") as fh:
            return fh.read()


def advance(st):
    """Move a pending stitch forward: poll its shots, and join once none is pending."""
    if st.status != VideoStitch.STATUS_PENDING:
        return
    works = {w.id: w for w in VideoWork.objects.filter(pk__in=st.shot_order)}
    for w in works.values():
        if w.status == VideoWork.STATUS_PENDING:
            poll(w)
            w.refresh_from_db()
    if any(w.status == VideoWork.STATUS_PENDING for w in works.values()):
        return
    landed = [works[i] for i in st.shot_order
              if i in works and works[i].status == VideoWork.STATUS_DONE and works[i].upload_id]
    if not landed:
        return _fail(st, "None of the shots rendered, and every one was refunded.")
    if not st.track_id:
        return _fail(st, "Your track is no longer there. The shots are kept in your renders as clips.")
    # One request joins; an overlapping poll sees the claim and leaves it alone.
    now = int(time.time())
    won = VideoStitch.objects.filter(pk=st.pk, status=VideoStitch.STATUS_PENDING).filter(
        Q(claim="") | Q(claim__lt=str(now - CLAIM_STALE_SECONDS))).update(claim=str(now))
    if not won:
        return
    try:
        data = _join(st, [w.upload for w in landed])
    except Exception as exc:
        why = str(exc) if isinstance(exc, RuntimeError) else "the shots could not be joined"
        return _fail(st, f"{why[:100].capitalize()}. The shots are paid for and kept in your renders as clips.")
    with transaction.atomic():
        row = VideoStitch.objects.select_for_update().get(pk=st.pk)
        if row.status != VideoStitch.STATUS_PENDING:
            return
        up = Upload(user=st.user, name=f"music-video-{st.pk}.mp4", size_bytes=len(data), content_type="video/mp4")
        up.file.save(up.name, ContentFile(data), save=False)
        up.save()
        row.upload, row.status, row.error, row.claim = up, VideoStitch.STATUS_DONE, "", ""
        row.save(update_fields=["upload", "status", "error", "claim"])
    st.refresh_from_db()


class VideoStitchView(APIView):
    """GET: what a stitched video costs, your tracks and past videos. POST: start one."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        w = wallet_for(request.user)
        clip = price_cents()
        tracks = [{"id": u.id, "name": u.name, "size_bytes": u.size_bytes}
                  for u in Upload.objects.filter(user=request.user, missing_since__isnull=True)[:80] if is_audio(u)]
        return Response({
            "configured": bool(_key()), "can_join": bool(ffmpeg_exe()),
            "min_shots": MIN_SHOTS, "max_shots": MAX_SHOTS, "clip_seconds": CLIP_SECONDS,
            "clip_price_cents": clip,
            "prices": {str(n): n * clip for n in range(MIN_SHOTS, MAX_SHOTS + 1)},
            "what_you_get": WHAT_YOU_GET,
            "promptz": w.promptz or 0, "money_cents": w.money_cents,
            "aspects": list(ASPECTS), "tracks": tracks,
            "faces": [{"id": f.id, "url": request.build_absolute_uri(f.image.url)}
                      for f in Face.objects.filter(owner=request.user).exclude(image="")[:30]],
            "royalty_pct": ROYALTY_PCT,
            "videos": [_dict(s, request) for s in VideoStitch.objects.filter(user=request.user)[:10]],
        })

    def post(self, request):
        d = request.data or {}
        user = request.user
        track = Upload.objects.filter(pk=d.get("track_id") or 0, user=user).first()
        if not track or not is_audio(track):
            return Response({"detail": "Pick one of your own uploaded tracks."}, status=status.HTTP_400_BAD_REQUEST)
        look = " ".join(str(d.get("look", "") or "").split())[:300]
        shots = [" ".join(str(x or "").split()) for x in (d.get("shots") or [])][:MAX_SHOTS + 1]
        shots = [x for x in shots if x]
        if not (MIN_SHOTS <= len(shots) <= MAX_SHOTS):
            return Response({"detail": f"A stitched video needs {MIN_SHOTS} to {MAX_SHOTS} shots."},
                            status=status.HTTP_400_BAD_REQUEST)
        tier = membership_for(user).tier
        for text in shots + [look]:
            cap = over_char_limit(text, tier)
            if cap:
                return Response({"detail": f"Your tier writes up to {cap:,} characters here.", "char_limit": cap},
                                status=status.HTTP_400_BAD_REQUEST)
        aspect = str(d.get("aspect", "16:9"))
        if aspect not in ASPECTS:
            return Response({"detail": "16:9 or 9:16."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            start = max(0, min(int(d.get("track_start") or 0), 3600))
        except (TypeError, ValueError):
            start = 0
        face = None
        if d.get("face_id"):
            face = Face.objects.filter(pk=d.get("face_id"), owner=user).first()
            if not face:
                return Response({"detail": "Only your own FaceZ photos can be used."}, status=status.HTTP_400_BAD_REQUEST)
        if not ffmpeg_exe():
            return Response({"detail": "Joining shots isn't available on the server yet. Nothing was charged."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        clip = price_cents()
        total = clip * len(shots)
        w = wallet_for(user)
        if (w.promptz or 0) + w.money_cents < total:
            return Response({"detail": f"Not enough PromptZ or balance for {len(shots)} shots.",
                             "price_cents": total}, status=status.HTTP_402_PAYMENT_REQUIRED)
        started = []
        for i, text in enumerate(shots, 1):
            prompt = f"{look + '. ' if look else ''}Shot {i} of {len(shots)}: {text}"
            work, refusal = start_render(user, "music", prompt, aspect, face)
            if refusal is not None:
                for done in started:                        # all or nothing at the start
                    refund(done, "another shot couldn't start")
                refusal.data = {**refusal.data, "refunded": True,
                                "detail": f"{refusal.data.get('detail', 'A shot could not start.')} "
                                          "Nothing was charged."}
                return refusal
            started.append(work)
        st = VideoStitch.objects.create(user=user, track=track, track_start=start, aspect=aspect,
                                        shot_order=[x.id for x in started])
        st.shots.set(started)
        return Response(_dict(st, request), status=status.HTTP_201_CREATED)


class VideoStitchDetailView(APIView):
    """GET — where a stitched video is; polls its shots and joins them when the last lands."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        st = VideoStitch.objects.select_related("track", "user").filter(pk=pk, user=request.user).first()
        if not st:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        advance(st)
        st.refresh_from_db()
        return Response(_dict(st, request))
