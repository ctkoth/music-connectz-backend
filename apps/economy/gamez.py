"""GameZ 🎮 — games members build in OCC, and play here.

The tab has existed in `occ_spec.py` since the taxonomy was written, and
`EXPORT_ROUTES["game"]` has routed to `gamez:mine` the whole time. Nothing was
behind either. This is the thing they were pointing at.

Three rules it inherits rather than invents:

**The taxonomy has one home.** Genres and subgenres are validated against
`occ_spec.GAME_GENRES` — the same 17/99 the spec already defines. A `choices=`
list on the model would have been a second copy, and a second copy is how
seventeen advertised languages ended up with twelve runners.

**Assets ride the storage a member already has.** A `GameAsset` is a join to
`Upload`, so sprites and audio count against `storage_used_bytes()` and the tier
cap that sells it. A parallel file table would mean game assets quietly didn't.

**Playable is computed, never asserted.** `Game.playable` reads the bundle, not
the status field. A Play button offered on a status with no file behind it is a
button that lies.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import limits_for
from .models import (
    MB,
    Game,
    GameAsset,
    OccFile,
    Upload,
    membership_for,
    normalize_occ_path,
    storage_used_bytes,
)
from .occ_spec import GAME_GENRES, GAME_GENRE_KEYS, GAME_SUBGENRES, genre_of

MAX_TITLE_CHARS = 160
MAX_DESCRIPTION_CHARS = 4_000


def clean_genre(genre, subgenre):
    """Resolve a (genre, subgenre) pair against the spec's taxonomy.

    Returns the pair to store. A subgenre alone is enough — `genre_of` already
    exists to find its parent, so a client that sends only "Metroidvania" gets
    filed under Action-Adventure rather than refused for not repeating itself.
    Anything unrecognised is dropped rather than rejected: a game with no genre
    is fine, a 400 because someone typed a genre we don't list is not.
    """
    sub = str(subgenre or "").strip()
    top = str(genre or "").strip().lower()
    if sub and sub in GAME_SUBGENRES:
        return genre_of(sub) or (top if top in GAME_GENRE_KEYS else ""), sub
    if top in GAME_GENRE_KEYS:
        return top, ""
    return "", ""


def game_dict(game, request=None):
    """One game, in the shape the client renders."""
    bundle_url = ""
    if game.bundle:
        bundle_url = game.bundle.url
        if request is not None:
            bundle_url = request.build_absolute_uri(bundle_url)
    return {
        "id": game.id,
        "title": game.title,
        "genre": game.genre,
        "subgenre": game.subgenre,
        "description": game.description,
        "project": game.project,
        "status": game.status,
        # Computed from the bundle, so this is never True with nothing to play.
        "playable": game.playable,
        "entry": game.entry,
        "bundle_url": bundle_url if game.playable else "",
        "bundle_mb": round(game.bundle_bytes / MB, 2),
        "build_detail": game.build_detail,
        "built_at": game.built_at.isoformat() if game.built_at else None,
        "plays": game.plays,
        "files": OccFile.objects.filter(user_id=game.user_id,
                                        project=game.project).count(),
        # `.all()`, not `.select_related("upload")` — a select_related on the
        # related manager builds a fresh queryset and throws away the
        # `assets__upload` prefetch the callers set up, turning the list view
        # into a query per game plus one per asset.
        "assets": [{"id": a.id, "path": a.path, "name": a.upload.name,
                    "bytes": a.upload.size_bytes}
                   for a in game.assets.all()],
        "item_key": game.item_key,
        "shared": bool(game.shared_post_id),
        "created_at": game.created_at.isoformat(),
        "updated_at": game.updated_at.isoformat(),
        # Nothing here is a dead end: the code opens in OCC, the build runs
        # there, and a shared game is a post like any other.
        "open_in": "occ", "target": "occ:filez",
    }


class GamezView(APIView):
    """GET your games and the taxonomy; POST to start one."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        games = Game.objects.filter(user=request.user).prefetch_related(
            "assets__upload")
        tier = membership_for(request.user).tier
        cap_mb = limits_for(tier)["storage_mb"]
        used_mb = storage_used_bytes(request.user) / MB
        return Response({
            "games": [game_dict(g, request) for g in games],
            # Served, not hardcoded on the client — same reason the OCC tabs are.
            "genres": [{"key": k, "name": n, "emoji": e, "subgenres": subs}
                       for k, n, e, subs in GAME_GENRES],
            "tier": tier,
            "storage_mb": round(cap_mb, 2),
            "storage_used_mb": round(used_mb, 2),
            "storage_left_mb": round(max(0, cap_mb - used_mb), 2),
            "max_title_chars": MAX_TITLE_CHARS,
            # Said up front rather than discovered at build time.
            "note": ("Games here are web games — HTML, JavaScript and WebAssembly. "
                     "They build in the sandbox and play in the app. Unity and "
                     "Unreal projects aren't built here."),
        })

    def post(self, request):
        d = request.data or {}
        title = str(d.get("title", "")).strip()
        if not title:
            return Response({"detail": "Give the game a title."},
                            status=status.HTTP_400_BAD_REQUEST)
        genre, subgenre = clean_genre(d.get("genre"), d.get("subgenre"))
        game = Game.objects.create(
            user=request.user,
            title=title[:MAX_TITLE_CHARS],
            genre=genre, subgenre=subgenre,
            description=str(d.get("description", ""))[:MAX_DESCRIPTION_CHARS],
            project=str(d.get("project") or "main")[:80],
        )
        return Response(game_dict(game, request), status=status.HTTP_201_CREATED)


class GameDetailView(APIView):
    """GET / PATCH / DELETE one game."""

    permission_classes = [IsAuthenticated]

    def _get(self, request, pk):
        return (Game.objects.filter(user=request.user, pk=pk)
                .prefetch_related("assets__upload").first())

    def get(self, request, pk):
        game = self._get(request, pk)
        if game is None:
            return Response({"detail": "No such game."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(game_dict(game, request))

    def patch(self, request, pk):
        game = self._get(request, pk)
        if game is None:
            return Response({"detail": "No such game."},
                            status=status.HTTP_404_NOT_FOUND)
        d = request.data or {}
        if "title" in d:
            title = str(d["title"]).strip()
            if not title:
                return Response({"detail": "A game needs a title."},
                                status=status.HTTP_400_BAD_REQUEST)
            game.title = title[:MAX_TITLE_CHARS]
        if "description" in d:
            game.description = str(d["description"])[:MAX_DESCRIPTION_CHARS]
        if "project" in d:
            game.project = str(d["project"] or "main")[:80]
        if "genre" in d or "subgenre" in d:
            game.genre, game.subgenre = clean_genre(
                d.get("genre", game.genre), d.get("subgenre", game.subgenre))
        game.save()
        return Response(game_dict(game, request))

    def delete(self, request, pk):
        game = self._get(request, pk)
        if game is None:
            return Response({"detail": "No such game."},
                            status=status.HTTP_404_NOT_FOUND)
        # The assets are Uploads and belong to the member, not the game — a
        # sprite they reused across two games shouldn't vanish because one was
        # deleted. Only the join goes, which cascades.
        game.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class GameAssetView(APIView):
    """POST an asset onto a game; DELETE one off it."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        game = Game.objects.filter(user=request.user, pk=pk).first()
        if game is None:
            return Response({"detail": "No such game."},
                            status=status.HTTP_404_NOT_FOUND)
        upload_file = request.FILES.get("file")
        if upload_file is None:
            return Response({"detail": "Attach a file."},
                            status=status.HTTP_400_BAD_REQUEST)

        # The same gate OccFile uses — this becomes a real path inside the
        # bundle, so it is checked here rather than trusted from the client.
        path = normalize_occ_path(request.data.get("path") or upload_file.name)
        if not path:
            return Response(
                {"detail": "That path isn't usable — give a relative path like "
                           "sprites/hero.png."},
                status=status.HTTP_400_BAD_REQUEST)

        tier = membership_for(request.user).tier
        limits = limits_for(tier)
        if upload_file.size > limits["upload_mb"] * MB:
            return Response(
                {"detail": f"That file is {upload_file.size / MB:.1f}MB — your "
                           f"tier uploads up to {limits['upload_mb']}MB."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        if storage_used_bytes(request.user) + upload_file.size > limits["storage_mb"] * MB:
            return Response(
                {"detail": f"That would take you past your {limits['storage_mb']}MB "
                           "of storage. Delete something, or a tier up carries more."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        upload = Upload.objects.create(
            user=request.user, file=upload_file, name=upload_file.name[:255],
            size_bytes=upload_file.size,
            content_type=(upload_file.content_type or "")[:120])
        asset, created = GameAsset.objects.update_or_create(
            game=game, path=path, defaults={"upload": upload})
        return Response(game_dict(game, request),
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def delete(self, request, pk):
        game = Game.objects.filter(user=request.user, pk=pk).first()
        if game is None:
            return Response({"detail": "No such game."},
                            status=status.HTTP_404_NOT_FOUND)
        path = normalize_occ_path(request.query_params.get("path"))
        deleted, _ = GameAsset.objects.filter(game=game, path=path).delete()
        if not deleted:
            return Response({"detail": "No asset at that path."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(game_dict(game, request))
