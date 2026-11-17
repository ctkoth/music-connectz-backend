"""Share anything a maker made, so every app's work gets the social bar.

Corey: every app needs karma, reactions, ratings, comments, sharing and "open in any other
app". The bar (`SocialView`, frontend `SocialBar.jsx`) already does all five for any item
kind registered in `social.ITEM_KINDS`. What the makers lacked was an item other members
are ALLOWED to see: a picture, video, manga page, written piece or FileZ file is its
maker's alone.

So the rule is one press: the maker shares it (`POST /api/economy/sharez/`), which mints an
unguessable token, and `shared:<token>` becomes an item like any post — openable at
`/x/<token>` by anyone with the link, with the bar under it. Unsharing deletes the row and
the link stops working. Nothing is shared by default, nothing is shared by anybody but its
maker, and what the public page shows is only the thing itself and its title.
"""
import secrets

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import GeneratedImage, MangaPage, SentenceWork, SharedItem, Upload, VideoWork

# Where each kind's work can be opened next, for everybody who opens it (cross-pollination).
OPENS = {
    "image": [("Edit a copy in ImageZ", "imagez"), ("Use it in VideoZ", "videoz")],
    "upload": [("Open it in ImageZ", "imagez"), ("Use it in VideoZ", "videoz")],
    "video": [("Edit a copy in VideoZ", "videoz"), ("Grab a frame in ImageZ", "imagez")],
    "manga": [("Touch it up in ImageZ", "imagez"), ("Motion comic in VideoZ", "videoz")],
    "sentence": [("Write one like it in Sentence ConnectZ", "sentenceconnectz")],
}
LABEL = {"upload": "file", "image": "picture", "video": "video", "manga": "manga page", "sentence": "piece"}
WHO = "Anyone with the link can open it and react, rate and comment. Unshare any time and the link stops working."


def _media(u, request):
    if not u or u.missing_since:
        return ""
    from .views import _upload_dict
    return _upload_dict(u, request).get("url") or ""


def _source(kind, ref, owner=None):
    """The made thing, or None — and only the owner's own when `owner` is given."""
    model = {"upload": Upload, "image": GeneratedImage, "video": VideoWork, "manga": MangaPage, "sentence": SentenceWork}.get(kind)
    if not model:
        return None
    qs = model.objects.filter(pk=ref)
    if owner is not None:
        qs = qs.filter(user=owner)
    obj = qs.first()
    if kind == "video" and obj and obj.status != VideoWork.STATUS_DONE:
        return None
    return obj


def payload(item, request):
    """What the public page shows: the thing, its title, who made it, and where it opens."""
    obj = _source(item.kind, item.ref)
    if obj is None:
        return None
    out = {"kind": item.kind, "label": LABEL[item.kind], "owner": item.owner.username, "token": item.token,
           "item": f"shared:{item.token}", "media": "", "media_kind": "", "text": "", "title": "",
           "opens": [{"label": a, "tab": t, "target": ""} for a, t in OPENS[item.kind]]}
    if item.kind == "upload":
        out.update(title=obj.name, media=_media(obj, request), media_kind=(obj.content_type or "").split("/")[0])
    elif item.kind == "image":
        out.update(title=(obj.prompt or "Picture")[:120], media=_media(obj.upload, request), media_kind="image")
    elif item.kind == "video":
        out.update(title=(obj.prompt or "Video")[:120], media=_media(obj.upload, request), media_kind="video")
    elif item.kind == "manga":
        out.update(title=obj.title or "Manga page", media=obj.page_image or next((p.get("image") for p in obj.panels or [] if p.get("image")), ""),
                   media_kind="image", text="\n".join(f'{d["who"]}: {d["line"]}' for p in obj.panels or [] for d in p.get("dialogue") or [])[:4000])
    elif item.kind == "sentence":
        out.update(title=(obj.topic or "Piece")[:120], text=obj.text[:20000])
    if item.kind in ("image", "video", "manga"):
        out["ai_made"] = True   # AI-made work says so wherever it is shown
    return out


def owner_of(token):
    """For social.ITEM_KINDS: (exists, owner)."""
    it = SharedItem.objects.select_related("owner").filter(token=token).first()
    if not it or _source(it.kind, it.ref) is None:
        return False, None
    return True, it.owner


class ShareZView(APIView):
    """POST {kind, ref} shares your own work and answers its link; GET ?kind=&ref= says whether it is shared."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        it = SharedItem.objects.filter(owner=request.user, kind=request.query_params.get("kind"),
                                       ref=_int(request.query_params.get("ref"))).first()
        return Response({"shared": bool(it), "token": it.token if it else "", "who": WHO,
                         "item": f"shared:{it.token}" if it else ""})

    def post(self, request):
        kind = str((request.data or {}).get("kind") or "")
        ref = _int((request.data or {}).get("ref"))
        if kind not in SharedItem.KINDS or not ref:
            return Response({"detail": "Share what? Pick one of your own pieces."}, status=status.HTTP_400_BAD_REQUEST)
        if _source(kind, ref, owner=request.user) is None:
            return Response({"detail": "Only your own finished work can be shared."}, status=status.HTTP_404_NOT_FOUND)
        it, _ = SharedItem.objects.get_or_create(owner=request.user, kind=kind, ref=ref,
                                                 defaults={"token": secrets.token_urlsafe(12)})
        return Response({"shared": True, "token": it.token, "item": f"shared:{it.token}", "path": f"/x/{it.token}", "who": WHO})


class ShareZDetailView(APIView):
    """GET /api/economy/sharez/<token>/ — the shared thing, open to anyone with the link.
    DELETE — the owner unshares it."""

    def get_permissions(self):
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    def get(self, request, token):
        it = SharedItem.objects.select_related("owner").filter(token=token).first()
        data = payload(it, request) if it else None
        if not data:
            return Response({"detail": "This link isn't shared any more."}, status=status.HTTP_404_NOT_FOUND)
        return Response(data)

    def delete(self, request, token):
        n, _ = SharedItem.objects.filter(owner=request.user, token=token).delete()
        if not n:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"shared": False})


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0
