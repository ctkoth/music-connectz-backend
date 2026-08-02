"""DistributeZ — import a PostZ into a release: pull the audio out of a video
(true mp3 320k) and populate lyrics from the description, an AI ghostwriter
(Corey), or a credited collaborator's lyric post.

The transcode runs on local ffmpeg when the host has it and on Modal when it
doesn't — see economy/transcode.py. Render's Python image ships without
ffmpeg, which is why this endpoint answered 503 in production from the day it
shipped; Modal is what makes it actually work up there. With neither
configured it still refuses cleanly, but now with a route rather than a wall.
"""
from django.core.files.base import ContentFile

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import transcode as transcoder
from .catalog import limits_for
from .models import Post, Upload, membership_for, storage_used_bytes
from .nextstep import refusal

MB = 1024 * 1024


def _has_ffmpeg():
    """Kept as a name because other modules and tests reach for it."""
    return transcoder.has_local_ffmpeg()


def _upload_dict(u, request):
    return {
        "id": u.id,
        "name": u.name,
        "content_type": u.content_type,
        "url": request.build_absolute_uri(u.file.url) if u.file else None,
    }


class TranscodeView(APIView):
    """POST {url} — extract the audio track from a (video) URL and store it as a
    real mp3 320k upload.

    Runs on whichever backend the deployment has: local ffmpeg, else Modal.
    503 only when it has neither.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        url = str((request.data or {}).get("url", "")).strip()
        if not url:
            return Response({"detail": "url required"}, status=status.HTTP_400_BAD_REQUEST)
        if not transcoder.available():
            return Response(
                refusal(
                    "Server transcoder isn't switched on yet.",
                    why=("This host has no ffmpeg and no Modal token, so there's "
                         "nowhere to run the conversion."),
                    action="/api/economy/uploads/", label="Upload the audio instead",
                    code="transcode_unavailable",
                ),
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        m = membership_for(request.user)
        lim = limits_for(m.tier)
        try:
            content = transcoder.to_mp3(url, bitrate="320k")
        except transcoder.TranscodeFailed as exc:
            return Response({"detail": str(exc)[:200]},
                            status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except transcoder.TranscodeUnavailable as exc:
            return Response(
                refusal(str(exc)[:200],
                        why="The transcoder is configured but couldn't be reached.",
                        action="/api/economy/uploads/",
                        label="Upload the audio instead",
                        code="transcode_unavailable"),
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Quotas are checked on the result, not the source: a 2GB video can
        # carry three minutes of audio, and refusing it on the input size
        # would turn a legal upload into a paywall.
        size = len(content)
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
        u = Upload.objects.create(
            user=request.user, name="distributez-track.mp3",
            size_bytes=size, content_type="audio/mpeg",
        )
        u.file.save("distributez-track.mp3", ContentFile(content), save=True)
        return Response(
            {"upload": _upload_dict(u, request), "bitrate": "320k",
             "backend": transcoder.backend()},
            status=status.HTTP_201_CREATED,
        )


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
