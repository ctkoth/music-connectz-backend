"""PlaylistZ — one running order across Music ConnectZ AND every distributor.

A member's catalogue is scattered: some of it is a post here, the rest is on
Spotify, YouTube, SoundCloud, Bandcamp. Every existing way to share "the set"
forces a choice of one platform and abandons the others. A playlist here mixes
them, in the order the member meant.

Two rules make it a junction instead of a terminus:

* **Every row says where it opens.** A post row carries `open_in` for the app
  and a `/p/<id>` link that works with no account; an outside row carries the
  distributor URL and its provider. Nothing in a playlist is a name you can't
  follow.
* **An outside link tallies like a profile link.** The same LinkCounter that
  counts clicks on a member's ProfileZ links counts these, so a playlist plays
  into reach and the +5⚡ click reward instead of leaking that value off to a
  page nobody here can measure.

Ratings and comments are NOT reimplemented. A playlist's `item_key` is
`playlist:<id>`, which is exactly the id space SocialView already serves, so it
gets RateZ and a comment thread by reusing what exists.
"""
from django.db import transaction
from django.db.models import Max
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import over_char_limit
from .links import safe_browsing_check
from .models import (
    PLAYLIST_MAX_ITEMS,
    LinkCounter,
    Playlist,
    PlaylistItem,
    Post,
    blocked_user_ids,
    can_view_post,
    item_rating_median,
    link_provider,
    membership_for,
)

VISIBILITIES = {"public", "restricted", "private"}


def can_view_playlist(pl, user):
    """Mirrors can_view_post exactly — one visibility rule, not two."""
    if pl.owner_id == getattr(user, "id", None):
        return True
    if pl.visibility == "public":
        return True
    if pl.visibility == "restricted":
        return bool(user and user.is_authenticated)
    return False


def item_dict(it, request=None):
    """One row, always carrying somewhere to go.

    A playlist that shows you a track and gives you no way to open it is a
    read-only surface, which is an unfinished one.
    """
    out = {
        "id": it.id,
        "position": it.position,
        "kind": it.kind,
        "title": it.title,
        "artist": it.artist,
        "added_at": it.added_at.isoformat(),
    }
    if it.kind == PlaylistItem.KIND_POST:
        post = it.post
        out.update({
            "post_id": it.post_id,
            # A post can be deleted out from under a playlist. Say so rather
            # than rendering a blank row the owner can't explain.
            "available": bool(post),
            "author": post.author.username if post else "",
            "media_type": post.media_type if post else "",
            "media_url": post.media_url if post else "",
            "rating": item_rating_median(f"post:{post.id}") if post else None,
            "open_in": "social:post",
            "url": f"/p/{it.post_id}" if post and post.visibility == "public" else "",
        })
    else:
        counter = LinkCounter.objects.filter(url=it.url).first()
        out.update({
            "url": it.url,
            "provider": it.provider,
            "available": True,
            # The same tally a ProfileZ link gets. A click from a playlist is
            # worth exactly what a click from a profile is worth.
            "clicks": counter.clicks if counter else 0,
            "safe": counter.safe if counter else True,
            "open_in": "external",
        })
    return out


def playlist_dict(pl, request=None, with_items=True):
    user = getattr(request, "user", None)
    items = list(pl.items.select_related("post", "post__author")) if with_items else []
    posts = sum(1 for i in items if i.kind == PlaylistItem.KIND_POST)
    out = {
        "id": pl.id,
        "owner": pl.owner.username,
        "mine": bool(user and user.is_authenticated and pl.owner_id == user.id),
        "title": pl.title,
        "description": pl.description,
        "cover_url": pl.cover_url,
        "visibility": pl.visibility,
        # RateZ and the comment thread ride on the existing item id space.
        "item_key": pl.item_key,
        "rating": item_rating_median(pl.item_key),
        "count": pl.items.count() if not with_items else len(items),
        "post_count": posts,
        "link_count": (len(items) - posts) if with_items else None,
        "created_at": pl.created_at.isoformat(),
        "updated_at": pl.updated_at.isoformat(),
    }
    if with_items:
        out["items"] = [item_dict(i, request) for i in items]
    return out


def _clean_visibility(raw, fallback="public"):
    v = str(raw or "").lower()
    return v if v in VISIBILITIES else fallback


class PlaylistsView(APIView):
    """GET the playlists I can see; POST creates one."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        blocked = blocked_user_ids(request.user)
        qs = (Playlist.objects.select_related("owner")
              .exclude(owner_id__in=blocked)
              .exclude(visibility="private")[:200])
        mine = Playlist.objects.select_related("owner").filter(owner=request.user)
        seen, out = set(), []
        for pl in list(mine) + list(qs):
            if pl.id in seen or not can_view_playlist(pl, request.user):
                continue
            seen.add(pl.id)
            out.append(playlist_dict(pl, request, with_items=False))
        return Response({"playlists": out})

    def post(self, request):
        d = request.data or {}
        title = str(d.get("title", "")).strip()
        if not title:
            return Response({"detail": "Give the playlist a name."},
                            status=status.HTTP_400_BAD_REQUEST)
        description = str(d.get("description", "") or "")
        cap = over_char_limit(description, membership_for(request.user).tier)
        if cap:
            return Response(
                {"detail": f"That description is over your {cap:,}-character limit — upgrade in MembershipZ for more room.",
                 "char_limit": cap},
                status=status.HTTP_400_BAD_REQUEST,
            )
        pl = Playlist.objects.create(
            owner=request.user, title=title[:160], description=description,
            cover_url=str(d.get("cover_url", ""))[:600],
            visibility=_clean_visibility(d.get("visibility")),
        )
        return Response(playlist_dict(pl, request), status=status.HTTP_201_CREATED)


class PlaylistDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        pl = Playlist.objects.select_related("owner").filter(pk=pk).first()
        if not pl or not can_view_playlist(pl, request.user):
            return Response({"detail": "playlist not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(playlist_dict(pl, request))

    def patch(self, request, pk):
        pl = Playlist.objects.filter(pk=pk, owner=request.user).first()
        if not pl:
            return Response({"detail": "playlist not found"}, status=status.HTTP_404_NOT_FOUND)
        d = request.data or {}
        changed = []
        if isinstance(d.get("title"), str) and d["title"].strip():
            pl.title = d["title"].strip()[:160]
            changed.append("title")
        if isinstance(d.get("description"), str):
            cap = over_char_limit(d["description"], membership_for(request.user).tier)
            if cap:
                return Response(
                    {"detail": f"That description is over your {cap:,}-character limit — upgrade in MembershipZ for more room.",
                     "char_limit": cap},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            pl.description = d["description"]
            changed.append("description")
        if isinstance(d.get("cover_url"), str):
            pl.cover_url = d["cover_url"][:600]
            changed.append("cover_url")
        if d.get("visibility"):
            pl.visibility = _clean_visibility(d["visibility"], pl.visibility)
            changed.append("visibility")
        if changed:
            pl.save(update_fields=changed + ["updated_at"])
        return Response(playlist_dict(pl, request))

    def delete(self, request, pk):
        pl = Playlist.objects.filter(pk=pk, owner=request.user).first()
        if not pl:
            return Response({"detail": "playlist not found"}, status=status.HTTP_404_NOT_FOUND)
        pl.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlaylistItemsView(APIView):
    """POST adds a row — either a Music ConnectZ post or an outside link."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        pl = Playlist.objects.filter(pk=pk, owner=request.user).first()
        if not pl:
            return Response({"detail": "playlist not found"}, status=status.HTTP_404_NOT_FOUND)
        if pl.items.count() >= PLAYLIST_MAX_ITEMS:
            return Response({"detail": f"A playlist holds {PLAYLIST_MAX_ITEMS} tracks. Start another one.",
                             "max_items": PLAYLIST_MAX_ITEMS},
                            status=status.HTTP_400_BAD_REQUEST)

        d = request.data or {}
        kind = str(d.get("kind", "")).lower()
        if kind not in (PlaylistItem.KIND_POST, PlaylistItem.KIND_LINK):
            # Infer rather than refuse: a client that sent one of the two
            # obvious fields has already said which it meant.
            kind = PlaylistItem.KIND_POST if d.get("post_id") else PlaylistItem.KIND_LINK

        nxt = (pl.items.aggregate(m=Max("position"))["m"] or 0) + 1
        title = str(d.get("title", "") or "")[:200]
        artist = str(d.get("artist", "") or "")[:160]

        if kind == PlaylistItem.KIND_POST:
            post = Post.objects.select_related("author").filter(pk=d.get("post_id") or 0).first()
            if not post:
                return Response({"detail": "That post doesn't exist."},
                                status=status.HTTP_400_BAD_REQUEST)
            if not can_view_post(post, request.user):
                # You can't smuggle a post you can't see into a public playlist.
                return Response({"detail": "You can't add a post you can't view."},
                                status=status.HTTP_403_FORBIDDEN)
            item = PlaylistItem.objects.create(
                playlist=pl, position=nxt, kind=kind, post=post,
                title=title or post.title, artist=artist or post.author.username,
            )
        else:
            url = str(d.get("url", "")).strip()[:600]
            if not url.startswith(("http://", "https://")):
                return Response({"detail": "Paste a full link, starting with https://"},
                                status=status.HTTP_400_BAD_REQUEST)
            # Best-effort scan, same as ProfileZ links. A key-less deploy treats
            # links as unscanned rather than claiming they were checked.
            safe, threat = safe_browsing_check(url)
            if not safe:
                return Response({"detail": f"That link is flagged ({threat}) — it can't be added.",
                                 "threat": threat},
                                status=status.HTTP_400_BAD_REQUEST)
            LinkCounter.objects.get_or_create(
                owner=request.user, url=url,
                defaults={"safe": safe, "scanned": bool(threat) or safe, "threat": threat},
            )
            item = PlaylistItem.objects.create(
                playlist=pl, position=nxt, kind=kind, url=url,
                provider=link_provider(url), title=title, artist=artist,
            )

        pl.save(update_fields=["updated_at"])
        return Response({"item": item_dict(item, request), "count": pl.items.count()},
                        status=status.HTTP_201_CREATED)


class PlaylistItemDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk, item_pk):
        pl = Playlist.objects.filter(pk=pk, owner=request.user).first()
        if not pl:
            return Response({"detail": "playlist not found"}, status=status.HTTP_404_NOT_FOUND)
        item = pl.items.filter(pk=item_pk).first()
        if not item:
            return Response({"detail": "track not found"}, status=status.HTTP_404_NOT_FOUND)
        item.delete()
        pl.save(update_fields=["updated_at"])
        return Response({"count": pl.items.count()})


class PlaylistReorderView(APIView):
    """POST {order: [item_id, ...]} — the running order is the whole point."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        pl = Playlist.objects.filter(pk=pk, owner=request.user).first()
        if not pl:
            return Response({"detail": "playlist not found"}, status=status.HTTP_404_NOT_FOUND)
        raw = (request.data or {}).get("order") or []
        ids = []
        for x in raw:
            try:
                ids.append(int(x))
            except (TypeError, ValueError):
                continue
        owned = {i.id: i for i in pl.items.all()}
        with transaction.atomic():
            pos = 0
            for item_id in ids:
                item = owned.pop(item_id, None)
                if item is None:
                    continue
                pos += 1
                item.position = pos
                item.save(update_fields=["position"])
            # Anything the client didn't mention keeps its relative order at the
            # end, so a partial order can never drop a track off the list.
            for item in sorted(owned.values(), key=lambda i: (i.position, i.id)):
                pos += 1
                item.position = pos
                item.save(update_fields=["position"])
        pl.save(update_fields=["updated_at"])
        return Response(playlist_dict(pl, request))


class PublicPlaylistView(APIView):
    """GET /api/playlistz/<pk>/ — a shared playlist, no account needed.

    Same rule as a shared post: public opens for anyone, restricted is
    members-only, private answers 404 rather than confirming it exists.
    """

    permission_classes = [AllowAny]

    def get(self, request, pk):
        pl = Playlist.objects.select_related("owner").filter(pk=pk).first()
        if not pl or not can_view_playlist(pl, request.user):
            return Response({"detail": "playlist not found"}, status=status.HTTP_404_NOT_FOUND)
        data = playlist_dict(pl, request)
        # A stranger gets the running order and the links. Ownership flags and
        # the comment thread stay behind the login.
        data.pop("mine", None)
        data["public"] = True
        return Response(data)
