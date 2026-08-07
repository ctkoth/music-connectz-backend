"""The work going back and forth on a deal.

A collab is a file exchange. The starter puts up v1; the collaborator
downloads it, does their part, and puts up v2. Until now a deal carried exactly
one `media_url` and no way to hand anything back, so the actual work happened in
DMs and the deal only held the money — which is half a collaboration tool.

Three rules:

**Everyone on the deal can download every version.** That is the point. A file
you can see the name of but not open is not a handoff.

**Everyone on the deal can upload the next version.** Not just the starter —
the person doing the work is usually the one who isn't.

**Versions are never overwritten.** An escrowed deal exists so it can be shown
what was delivered and when; a v2 replacing v1 in place would destroy the only
record of that. v1 stays, forever, next to v2.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CollabDeal, CollabFile


def file_dict(f, me=None):
    return {
        "id": f.id,
        "version": f.version,
        "url": f.url,
        "name": f.name,
        "media_type": f.media_type,
        "note": f.note,
        "uploader": f.uploader.username,
        "mine": bool(me and f.uploader_id == me.id),
        # Spelled out rather than implied. Every participant may open every
        # version — that is what makes this a handoff and not a display case.
        "can_download": True,
        "created_at": f.created_at.isoformat(),
    }


def on_deal(user, deal):
    """Anyone on the deal — the starter or a named participant."""
    return (deal.initiator_id == user.id
            or any(p.get("username") == user.username for p in (deal.participants or [])))


def seed_v1(deal):
    """The deal's own media IS version 1.

    Created lazily so deals made before file exchange existed still show their
    original work as v1 rather than starting an empty history beside it.
    """
    if not deal.media_url or deal.files.exists():
        return None
    return CollabFile.objects.create(
        deal=deal, uploader=deal.initiator, version=1, url=deal.media_url,
        name=(deal.title or "version 1")[:255], media_type=deal.media_type,
        note="The work this deal started from.",
    )


class CollabFilesView(APIView):
    """GET every version on a deal; POST adds the next one."""

    permission_classes = [IsAuthenticated]

    def _deal(self, request, pk):
        deal = CollabDeal.objects.select_related("initiator").filter(pk=pk).first()
        return deal if deal and on_deal(request.user, deal) else None

    def get(self, request, pk):
        deal = self._deal(request, pk)
        if not deal:
            return Response({"detail": "deal not found"}, status=status.HTTP_404_NOT_FOUND)
        seed_v1(deal)
        rows = deal.files.select_related("uploader").all()
        files = [file_dict(f, request.user) for f in rows]
        return Response({
            "files": files,
            "latest": files[-1] if files else None,
            "next_version": (files[-1]["version"] + 1) if files else 1,
            # Uploading a version is free and moves no resource. Said plainly,
            # because every other button here that touches one states its price.
            "cost": None,
            "note": "Everyone on this deal can download every version and upload the next.",
        })

    def post(self, request, pk):
        deal = self._deal(request, pk)
        if not deal:
            return Response({"detail": "deal not found"}, status=status.HTTP_404_NOT_FOUND)
        url = str((request.data or {}).get("url", "")).strip()[:500]
        if not url:
            return Response({"detail": "There's no file here — upload it first, then send the URL."},
                            status=status.HTTP_400_BAD_REQUEST)
        seed_v1(deal)
        last = deal.files.order_by("-version").first()
        f = CollabFile.objects.create(
            deal=deal, uploader=request.user,
            version=(last.version + 1) if last else 1,
            url=url,
            name=str((request.data or {}).get("name", "") or "")[:255],
            media_type=str((request.data or {}).get("media_type", "") or "")[:24],
            note=str((request.data or {}).get("note", "") or ""),
        )
        return Response(file_dict(f, request.user), status=status.HTTP_201_CREATED)


class CollabFileDetailView(APIView):
    """DELETE a version you uploaded — while it's still the newest one."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, pk, file_id):
        deal = CollabDeal.objects.filter(pk=pk).first()
        if not deal or not on_deal(request.user, deal):
            return Response({"detail": "deal not found"}, status=status.HTTP_404_NOT_FOUND)
        f = deal.files.filter(pk=file_id).first()
        if not f:
            return Response({"detail": "version not found"}, status=status.HTTP_404_NOT_FOUND)
        if f.uploader_id != request.user.id:
            return Response({"detail": "That version isn't yours to remove."},
                            status=status.HTTP_403_FORBIDDEN)
        if deal.files.filter(version__gt=f.version).exists():
            # Somebody has already built on it. Pulling it now would leave the
            # next version answering a question nobody can read.
            return Response(
                {"detail": "Someone has already worked from that version, so it stays."},
                status=status.HTTP_409_CONFLICT,
            )
        f.delete()
        return Response({"deleted": True})
