"""DistributeZ — import a PostZ into a release: pull the audio out of a video
(true mp3 320k via server ffmpeg) and populate lyrics from the description, an
AI ghostwriter (Corey), or a credited collaborator's lyric post.

The transcode needs ffmpeg on the host. When it's missing the endpoint returns a
clean 503 so the client can show "server transcoder not enabled yet" rather than
half-doing it in the browser.
"""
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

from django.core.files.base import ContentFile

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import limits_for
from .models import Post, Upload, membership_for, storage_used_bytes

MB = 1024 * 1024


def _has_ffmpeg():
    return bool(shutil.which("ffmpeg"))


def _upload_dict(u, request):
    return {
        "id": u.id,
        "name": u.name,
        "content_type": u.content_type,
        "url": request.build_absolute_uri(u.file.url) if u.file else None,
    }


class TranscodeView(APIView):
    """POST {url} — extract the audio track from a (video) URL and store it as a
    real mp3 320k upload. 503 when ffmpeg isn't installed on the server."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        url = str((request.data or {}).get("url", "")).strip()
        if not url:
            return Response({"detail": "url required"}, status=status.HTTP_400_BAD_REQUEST)
        if not _has_ffmpeg():
            return Response(
                {"detail": "Server transcoder not enabled yet — ffmpeg isn't installed on the host.",
                 "code": "transcode_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        m = membership_for(request.user)
        lim = limits_for(m.tier)
        src_path = out_path = None
        try:
            # Pull the source to a temp file (URL may be our own media host).
            fd, src_path = tempfile.mkstemp(suffix=".src")
            os.close(fd)
            urllib.request.urlretrieve(url, src_path)
            out_path = src_path + ".mp3"
            # -vn drops video; keep stereo (L/R); constant 320k bitrate.
            proc = subprocess.run(
                ["ffmpeg", "-y", "-i", src_path, "-vn", "-ac", "2", "-b:a", "320k", out_path],
                capture_output=True, timeout=120,
            )
            if proc.returncode != 0 or not os.path.exists(out_path):
                return Response(
                    {"detail": "Transcode failed — the source may not contain an audio track."},
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            size = os.path.getsize(out_path)
            if size > lim["upload_mb"] * MB:
                return Response(
                    {"detail": f"Extracted audio exceeds your {lim['upload_mb']}MB per-upload limit."},
                    status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )
            if storage_used_bytes(request.user) + size > lim["storage_mb"] * MB:
                return Response(
                    {"detail": f"Extracted audio would exceed your {lim['storage_mb']}MB storage quota."},
                    status=status.HTTP_409_CONFLICT,
                )
            with open(out_path, "rb") as fh:
                content = fh.read()
            u = Upload.objects.create(
                user=request.user, name="distributez-track.mp3",
                size_bytes=size, content_type="audio/mpeg",
            )
            u.file.save("distributez-track.mp3", ContentFile(content), save=True)
            return Response({"upload": _upload_dict(u, request), "bitrate": "320k"}, status=status.HTTP_201_CREATED)
        except (urllib.error.URLError, ValueError, OSError) as exc:
            return Response({"detail": f"Couldn't fetch/transcode the source: {exc}"[:200]},
                            status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except subprocess.TimeoutExpired:
            return Response({"detail": "Transcode timed out — try a shorter clip."},
                            status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        finally:
            for p in (src_path, out_path):
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass


class LyricsView(APIView):
    """POST {source, description, collaborator_post_id, prompt} — return lyrics to
    prefill a release. source ∈ {description, ai, collaborator}."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        d = request.data or {}
        source = str(d.get("source", "description")).lower()
        description = str(d.get("description", "")).strip()

        if source == "collaborator":
            pid = d.get("collaborator_post_id")
            post = Post.objects.filter(pk=pid).select_related("author").first() if pid else None
            if not post:
                return Response({"detail": "collaborator post not found"}, status=status.HTTP_404_NOT_FOUND)
            # Prefer explicit lyrics on an album item, else the post description.
            lyrics = ""
            for it in (post.items or []):
                if it.get("lyrics"):
                    lyrics = it["lyrics"]
                    break
            lyrics = lyrics or post.description or ""
            return Response({"lyrics": lyrics, "source": "collaborator", "ghostwriter": post.author.username})

        if source == "ai":
            prompt = str(d.get("prompt", "")).strip() or description or "an original song"
            lyrics = self._ai_lyrics(prompt)
            if lyrics is None:
                return Response(
                    {"detail": "AI ghostwriter unavailable — set ANTHROPIC_API_KEY on the backend.",
                     "code": "ai_unavailable"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            return Response({"lyrics": lyrics, "source": "ai", "ghostwriter": "Corey (AI)"})

        # Default: straight from the post description.
        return Response({"lyrics": description, "source": "description", "ghostwriter": ""})

    def _ai_lyrics(self, prompt):
        try:
            import anthropic
        except ImportError:
            return None
        try:
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model="claude-opus-4-8",
                max_tokens=900,
                system=("You are Corey / K-Oth ghostwriting song lyrics for a Music ConnectZ member. "
                        "Write complete, original, performable lyrics (verses, hook/chorus, labeled). "
                        "Match the vibe of the brief. Lyrics only — no commentary."),
                messages=[{"role": "user", "content": f"Write lyrics for: {prompt}"}],
            )
            return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip() or None
        except Exception:
            return None
