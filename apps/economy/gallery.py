"""A member's gallery: the images in their PUBLIC posts, newest first.

Nothing is stored for it. A gallery is a view of posts, so every image in it already
has its likes, ratings, comments, shares and other-app doors on the post it came from,
and each tile links there. Only public posts count, for every viewer including the
member themselves: the gallery is what a visitor sees, and an image in a members-only
or join-to-see post would leak past the wall it sits behind.

An under-18 member's gallery is empty to anyone not signed in, the same line the public
battle and lesson pages draw: inside the app it shows as usual.
"""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from django.contrib.auth import get_user_model

from .models import Post, is_minor

MAX_IMAGES = 60
_SCAN = 300  # posts read per request; a gallery is a page, not an archive


def images_of(post):
    """Every image a post carries, in the order it shows them. Deduplicated."""
    out, seen = [], set()

    def add(url):
        url = str(url or "").strip()
        if url and url not in seen:
            seen.add(url)
            out.append(url)

    if str(post.media_type or "").startswith("image"):
        add(post.media_url)
    for it in (post.items or []):
        if isinstance(it, dict) and str(it.get("type") or "").startswith("image"):
            add(it.get("url"))
    return out


def gallery_for(user, request=None):
    signed_in = bool(request and getattr(request.user, "is_authenticated", False))
    if is_minor(user) and not signed_in:
        return []
    tiles = []
    posts = (Post.objects.filter(author=user, visibility="public")
             .only("id", "title", "media_type", "media_url", "items", "created_at")
             .order_by("-created_at")[:_SCAN])
    for p in posts:
        for url in images_of(p):
            tiles.append({"url": url, "post_id": p.id, "title": p.title,
                          "created_at": p.created_at.isoformat()})
            if len(tiles) >= MAX_IMAGES:
                return tiles
    return tiles


class GalleryView(APIView):
    """GET /api/economy/gallery/<username>/ — open logged-out, like the public profile."""
    permission_classes = [AllowAny]

    def get(self, request, username):
        # By account, not Profile: a Profile row is made lazily, and a member who never
        # opened a screen that makes one still has posts.
        u = get_user_model().objects.filter(username__iexact=str(username)[:150]).first()
        if not u:
            return Response({"detail": "profile not found"}, status=404)
        resp = Response({"username": u.username, "images": gallery_for(u, request),
                         "max": MAX_IMAGES})
        # The answer differs for a signed-in viewer (a minor's gallery), so no shared cache.
        resp["Cache-Control"] = "private"
        resp["Vary"] = "Authorization"
        return resp
