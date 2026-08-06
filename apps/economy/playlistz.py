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
from django.contrib.auth import get_user_model

from .models import (
    PLAYLIST_MAX_ITEMS,
    LinkCounter,
    Playlist,
    PlaylistCollaborator,
    PlaylistItem,
    Post,
    blocked_user_ids,
    can_add_to_playlist,
    can_view_post,
    item_rating_median,
    link_provider,
    membership_for,
    notify,
)

User = get_user_model()

VISIBILITIES = {"public", "restricted", "private"}


def can_view_playlist(pl, user):
    """Mirrors can_view_post, plus: a collaborator can always see the list they
    were invited onto, even when it is private."""
    if pl.owner_id == getattr(user, "id", None):
        return True
    if pl.visibility == "public":
        return True
    if pl.visibility == "restricted":
        return bool(user and user.is_authenticated)
    return can_add_to_playlist(pl, user)


def item_dict(it, request=None):
    """One row, always carrying somewhere to go.

    A playlist that shows you a track and gives you no way to open it is a
    read-only surface, which is an unfinished one.
    """
    user = getattr(request, "user", None)
    out = {
        "id": it.id,
        "position": it.position,
        "kind": it.kind,
        "title": it.title,
        "artist": it.artist,
        # Who put it in. On a shared list this is the answer to "who added
        # this?", and it's what decides who may take it back out.
        "added_by": it.added_by.username if it.added_by else "",
        "added_at": it.added_at.isoformat(),
    }
    if user is not None and getattr(user, "is_authenticated", False):
        out["can_remove"] = (it.playlist.owner_id == user.id
                             or it.added_by_id == user.id
                             or bool(it.post_id and it.post and it.post.author_id == user.id))
    if it.kind == PlaylistItem.KIND_POST:
        post = it.post
        # A public playlist can hold a members-only post, and the row copied
        # that post's TITLE at add time — so a restricted post's name was
        # readable by anyone with the share link. The row still holds its place
        # in the running order; it just stops saying what it is.
        readable = bool(post) and can_view_post(post, user)
        out.update({
            "post_id": it.post_id,
            # A post can be deleted out from under a playlist. Say so rather
            # than rendering a blank row the owner can't explain.
            "available": bool(post),
            "readable": readable,
            "author": post.author.username if readable else "",
            "media_type": post.media_type if readable else "",
            "media_url": post.media_url if readable else "",
            "rating": item_rating_median(f"post:{post.id}") if readable else None,
            "open_in": "social:post",
            "url": f"/p/{it.post_id}" if readable and post.visibility == "public" else "",
        })
        if post and not readable:
            out["title"] = "Members-only track"
            out["artist"] = ""
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
        "collaborators": [c.user.username for c in
                          pl.collaborators.select_related("user")],
        # The owner sequences; a collaborator contributes. Two people fighting
        # over the running order means last-save-wins on somebody's set list.
        "can_add": can_add_to_playlist(pl, user),
        "can_reorder": bool(user and getattr(user, "is_authenticated", False)
                            and pl.owner_id == user.id),
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
        # A private list you were invited onto is one of YOUR playlists too —
        # it would be absurd to be a collaborator on something you can't find.
        joined = (Playlist.objects.select_related("owner")
                  .filter(collaborators__user=request.user))
        seen, out = set(), []
        for pl in list(mine) + list(joined) + list(qs):
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
        pl = Playlist.objects.select_related("owner").filter(pk=pk).first()
        if not pl or not can_view_playlist(pl, request.user):
            return Response({"detail": "playlist not found"}, status=status.HTTP_404_NOT_FOUND)
        if not can_add_to_playlist(pl, request.user):
            return Response({"detail": "You're not a collaborator on this playlist."},
                            status=status.HTTP_403_FORBIDDEN)
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
            if post.author_id != request.user.id and not post.allow_in_playlists:
                return Response(
                    {"detail": f"@{post.author.username} has this track switched off for other people's playlists."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            item = PlaylistItem.objects.create(
                playlist=pl, position=nxt, kind=kind, post=post, added_by=request.user,
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
                playlist=pl, position=nxt, kind=kind, url=url, added_by=request.user,
                provider=link_provider(url), title=title, artist=artist,
            )

        pl.save(update_fields=["updated_at"])
        if pl.owner_id != request.user.id:
            notify(pl.owner, "system",
                   f"@{request.user.username} added a track to '{pl.title}' 🎵",
                   actor=request.user, item_id=pl.item_key)
        # Being picked up for someone else's set is reach. It is also how an
        # author learns the remove lever exists, which is the whole reason
        # opt-out works without an approval queue nobody would ever drain.
        if item.post_id and item.post.author_id != request.user.id:
            notify(item.post.author, "system",
                   f"@{request.user.username} added '{item.post.title}' to the playlist '{pl.title}' 🎵",
                   actor=request.user, item_id=pl.item_key)
        return Response({"item": item_dict(item, request), "count": pl.items.count()},
                        status=status.HTTP_201_CREATED)


class PlaylistItemDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk, item_pk):
        pl = Playlist.objects.select_related("owner").filter(pk=pk).first()
        if not pl or not can_view_playlist(pl, request.user):
            return Response({"detail": "playlist not found"}, status=status.HTTP_404_NOT_FOUND)
        item = pl.items.filter(pk=item_pk).first()
        if not item:
            return Response({"detail": "track not found"}, status=status.HTTP_404_NOT_FOUND)
        # Three people may remove a row, and only three:
        #   the playlist owner   — it's their list
        #   whoever added it     — they can take back what they put in
        #   the post's author    — their work, wherever it ended up
        # A collaborator deleting somebody else's track would make a shared
        # list a place to be sabotaged.
        allowed = {pl.owner_id, item.added_by_id}
        if item.post_id and item.post:
            allowed.add(item.post.author_id)
        if request.user.id not in allowed:
            return Response({"detail": "Only the playlist owner or the person who added it can remove this."},
                            status=status.HTTP_403_FORBIDDEN)
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


class PlaylistCollaboratorsView(APIView):
    """Who else can add to this playlist.

    Invite-only. POST {username} adds a seat, DELETE {username} takes it back —
    and a collaborator can DELETE themselves, because being stuck on somebody
    else's list with no way off is not a feature.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        pl = Playlist.objects.select_related("owner").filter(pk=pk).first()
        if not pl or not can_view_playlist(pl, request.user):
            return Response({"detail": "playlist not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            "owner": pl.owner.username,
            "collaborators": [
                {"username": c.user.username,
                 "invited_by": c.invited_by.username if c.invited_by else "",
                 "added_at": c.added_at.isoformat()}
                for c in pl.collaborators.select_related("user", "invited_by")
            ],
        })

    def post(self, request, pk):
        pl = Playlist.objects.select_related("owner").filter(pk=pk, owner=request.user).first()
        if not pl:
            return Response({"detail": "playlist not found"}, status=status.HTTP_404_NOT_FOUND)
        username = str((request.data or {}).get("username", "")).strip()
        user = User.objects.filter(username__iexact=username).first()
        if not user:
            return Response({"detail": f"No member called '{username}'."},
                            status=status.HTTP_400_BAD_REQUEST)
        if user.id == pl.owner_id:
            return Response({"detail": "You already own this playlist."},
                            status=status.HTTP_400_BAD_REQUEST)
        if user.id in blocked_user_ids(request.user):
            return Response({"detail": "You can't collaborate with that member."},
                            status=status.HTTP_403_FORBIDDEN)
        _, created = PlaylistCollaborator.objects.get_or_create(
            playlist=pl, user=user, defaults={"invited_by": request.user})
        if created:
            # An invitation nobody is told about is not an invitation.
            notify(user, "system",
                   f"@{request.user.username} added you to the playlist '{pl.title}' 🎵",
                   actor=request.user, item_id=pl.item_key)
        return Response(playlist_dict(pl, request), status=status.HTTP_201_CREATED)

    def delete(self, request, pk):
        pl = Playlist.objects.select_related("owner").filter(pk=pk).first()
        if not pl:
            return Response({"detail": "playlist not found"}, status=status.HTTP_404_NOT_FOUND)
        username = str((request.data or {}).get("username", "")
                       or request.query_params.get("username", "")).strip()
        # No username given means "take me off this list".
        target = (User.objects.filter(username__iexact=username).first()
                  if username else request.user)
        if not target:
            return Response({"detail": "unknown member"}, status=status.HTTP_400_BAD_REQUEST)
        if pl.owner_id != request.user.id and target.id != request.user.id:
            return Response({"detail": "Only the owner can remove another collaborator."},
                            status=status.HTTP_403_FORBIDDEN)
        PlaylistCollaborator.objects.filter(playlist=pl, user=target).delete()
        # Their tracks stay. They contributed them to this set, and pulling the
        # set apart because somebody left is the owner's call, not a side
        # effect — the rows are still individually removable.
        return Response(playlist_dict(pl, request))


class PostPlaylistAppearancesView(APIView):
    """GET /api/economy/postz/<pk>/playlists/ — where my post ended up.

    An author who can switch appearances off, and remove individual rows, still
    needs to be able to SEE where their work is. A control you can't aim is not
    control.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        post = Post.objects.filter(pk=pk, author=request.user).first()
        if not post:
            return Response({"detail": "post not found"}, status=status.HTTP_404_NOT_FOUND)
        rows = (PlaylistItem.objects
                .filter(post=post)
                .select_related("playlist", "playlist__owner", "added_by"))
        out = []
        for it in rows:
            pl = it.playlist
            if pl.owner_id == request.user.id:
                continue        # my own lists aren't "appearances"
            out.append({
                "item_id": it.id,
                "playlist_id": pl.id,
                "playlist": pl.title,
                "owner": pl.owner.username,
                "visibility": pl.visibility,
                "added_by": it.added_by.username if it.added_by else "",
                "added_at": it.added_at.isoformat(),
                # Where to go pull it, using the same endpoint the owner uses.
                "remove_url": f"/api/economy/playlistz/{pl.id}/items/{it.id}/",
            })
        return Response({
            "post": post.title,
            "allow_in_playlists": post.allow_in_playlists,
            "appearances": out,
        })


class MyAppearancesView(APIView):
    """GET /api/economy/playlistz/appearances/ — every playlist of someone
    else's that any of my posts is in, in one call.

    Per-post lookups would make this N requests for a member with a catalogue,
    and a panel nobody loads is a control nobody uses.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = (PlaylistItem.objects
                .filter(post__author=request.user)
                .exclude(playlist__owner=request.user)
                .select_related("playlist", "playlist__owner", "post", "added_by")
                .order_by("-added_at")[:200])
        out = []
        for it in rows:
            pl = it.playlist
            out.append({
                "item_id": it.id,
                "post_id": it.post_id,
                "post": it.post.title,
                "allow_in_playlists": it.post.allow_in_playlists,
                "playlist_id": pl.id,
                "playlist": pl.title,
                "owner": pl.owner.username,
                "visibility": pl.visibility,
                "added_by": it.added_by.username if it.added_by else "",
                "added_at": it.added_at.isoformat(),
            })
        return Response({"appearances": out})
