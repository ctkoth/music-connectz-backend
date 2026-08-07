"""A finished collab becomes one post, belonging to everyone who made it.

This is the shape the whole app was built toward. An artist arrives with a
song and needs a cover and a music video. A designer puts up the cover. A
videographer puts up the video. What ships is not three posts and an argument
about credit — it is ONE post, carrying one of each, owned by all three.

Two things make that true rather than decorative:

**Credit is derived, not typed.** Who brought what comes from the file
exchange, because that is the only record that actually knows. The person who
uploaded the image contributed the image. Nobody assigns it, so nobody can
misassign it.

**Ownership follows contribution.** `owns_post` counts contributors, so every
check that meant "is this yours" now means it for all of them — the designer's
own work does not read as somebody else's on their own screen.

And what a deal is LOOKING for is published, so the designer who could take it
can find it. A collab nobody can discover is a collab between people who
already knew each other.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .collab_files import on_deal, seed_v1
from .models import CollabDeal, Post, PostContributor, notify
from .postz import _post_dict, create_post

# The slots a deal can be looking to fill, and the skill that usually fills one.
# Offered as a starting point, never enforced — a producer who wants to shoot
# their own video should not be argued with by a dropdown.
NEED_SLOTS = [
    {"slot": "audio", "label": "A song", "skill": "Independent Artist"},
    {"slot": "image", "label": "Cover art", "skill": "Designer"},
    {"slot": "video", "label": "A music video", "skill": "Videographer"},
    {"slot": "text", "label": "Lyrics or a script", "skill": "Ghost Writer"},
]


def contributions(deal):
    """{slot: username} — who brought each piece, from the files themselves.

    The LATEST version of a slot wins, because that is the one that ships. A
    cover replaced by a better cover is credited to whoever made the one people
    will actually see.
    """
    out = {}
    for f in deal.files.select_related("uploader").order_by("version"):
        slot = (f.media_type or "").lower()
        if slot in ("audio", "video", "image"):
            out[slot] = f.uploader.username
    return out


def slot_urls(deal):
    """{slot: url} for the latest version of each slot."""
    out = {}
    for f in deal.files.order_by("version"):
        slot = (f.media_type or "").lower()
        if slot in ("audio", "video", "image"):
            out[slot] = f.url
    return out


def open_needs(deal):
    """What the deal still wants, minus what has already arrived."""
    have = set(contributions(deal))
    if deal.lyrics:
        have.add("text")
    return [n for n in (deal.needs or []) if n.get("slot") not in have]


class CollabNeedsView(APIView):
    """GET what this deal is looking for; PATCH to change it.

    A deal that doesn't say what it needs can only be joined by someone who
    already knows the person who started it.
    """

    permission_classes = [IsAuthenticated]

    def _deal(self, request, pk, owner_only=False):
        deal = CollabDeal.objects.select_related("initiator").filter(pk=pk).first()
        if not deal:
            return None
        if owner_only:
            return deal if deal.initiator_id == request.user.id else None
        return deal if on_deal(request.user, deal) else None

    def get(self, request, pk):
        deal = CollabDeal.objects.filter(pk=pk).first()
        if not deal:
            return Response({"detail": "deal not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            "needs": deal.needs or [],
            "open": open_needs(deal),
            "filled": contributions(deal),
            "slots": NEED_SLOTS,
        })

    def patch(self, request, pk):
        deal = self._deal(request, pk, owner_only=True)
        if not deal:
            return Response({"detail": "Only whoever started the deal can change what it needs."},
                            status=status.HTTP_403_FORBIDDEN)
        raw = (request.data or {}).get("needs")
        if not isinstance(raw, list):
            return Response({"detail": "needs must be a list of {slot, skill}."},
                            status=status.HTTP_400_BAD_REQUEST)
        valid = {n["slot"] for n in NEED_SLOTS}
        cleaned, seen = [], set()
        for n in raw[:8]:
            if not isinstance(n, dict):
                continue
            slot = str(n.get("slot", "")).lower()
            if slot not in valid or slot in seen:
                continue
            seen.add(slot)
            cleaned.append({"slot": slot, "skill": str(n.get("skill", ""))[:60]})
        deal.needs = cleaned
        deal.save(update_fields=["needs"])
        return Response({"needs": deal.needs, "open": open_needs(deal), "slots": NEED_SLOTS})


class CollabPostView(APIView):
    """POST /api/economy/collab/<pk>/post/ — publish the deal as one shared post."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        deal = CollabDeal.objects.select_related("initiator").filter(pk=pk).first()
        if not deal or not on_deal(request.user, deal):
            return Response({"detail": "deal not found"}, status=status.HTTP_404_NOT_FOUND)
        existing = Post.objects.filter(source_deal=deal).first()
        if existing:
            # Two posts of one collab would split its ratings and its credit.
            return Response(
                {"detail": "This collab is already posted.",
                 **_post_dict(existing, request)},
                status=status.HTTP_409_CONFLICT,
            )
        seed_v1(deal)
        urls = slot_urls(deal)
        if not urls and not deal.lyrics:
            return Response(
                {"detail": "There's nothing to post yet — put the work up first.",
                 "open": open_needs(deal)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        who = contributions(deal)
        # Everyone on the deal is credited. Those who brought a slot are named
        # with it; the rest are still on it, because being on a deal that
        # shipped is a contribution even when it wasn't a file.
        contributors = [{"username": u, "slot": s} for s, u in sorted(who.items())]
        named = {c["username"] for c in contributors}
        for p in (deal.participants or []):
            u = p.get("username")
            if u and u not in named:
                contributors.append({"username": u, "slot": ""})
                named.add(u)

        d = request.data or {}
        title = str(d.get("title") or deal.title or "Collab")[:160]
        items = []
        for slot in ("audio", "video", "image"):
            if urls.get(slot):
                items.append({"url": urls[slot], "type": slot,
                              "title": f"{title} ({slot})"[:160], "lyrics": ""})
        if deal.lyrics:
            items.append({"url": "", "type": "text",
                          "title": f"{title} (script)"[:160], "lyrics": deal.lyrics})

        post, info, err = create_post(request.user, {
            "title": title,
            "description": str(d.get("description") or deal.description or ""),
            "media_type": "audio" if urls.get("audio") else ("video" if urls.get("video") else ""),
            "media_url": urls.get("audio") or urls.get("video") or "",
            "items": items,
            "genre": d.get("genre", ""),
            "visibility": d.get("visibility", "public"),
            "allow_in_playlists": d.get("allow_in_playlists", True),
        })
        if err:
            return Response(err[0], status=err[1])

        post.contributors = contributors
        post.source_deal = deal
        post.save(update_fields=["contributors", "source_deal"])
        # The same fact as indexed rows, so the feed can find a member's
        # private collab posts without scanning JSON.
        from django.contrib.auth import get_user_model as _gum
        _User = _gum()
        by_name = {u.username: u for u in
                   _User.objects.filter(username__in=[c["username"] for c in contributors])}
        PostContributor.objects.bulk_create(
            [PostContributor(post=post, user=by_name[c["username"]], slot=c["slot"])
             for c in contributors if c["username"] in by_name],
            ignore_conflicts=True,
        )

        # Tell the people it now belongs to. Finding out your work was
        # published by seeing it in the feed is not being told.
        from django.contrib.auth import get_user_model
        User = get_user_model()
        for c in contributors:
            if c["username"] == request.user.username:
                continue
            u = User.objects.filter(username=c["username"]).first()
            if u:
                notify(u, "post",
                       f"@{request.user.username} posted '{post.title}' — you're credited"
                       + (f" for the {c['slot']}." if c["slot"] else "."),
                       actor=request.user, item_id=f"post:{post.id}")

        return Response({**_post_dict(post, request), **info,
                         "contributors": contributors},
                        status=status.HTTP_201_CREATED)
