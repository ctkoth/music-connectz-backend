"""A link to a member's upload that does not expire.

The app STORES the URLs it hands out. `uploadWork.js` uploads a blob, takes
the `url` that comes back, and writes it into `Post.media_url` and into the
post's `items` — where it stays for the life of the post. CollabZ, BattleZ,
DirectZ and OCC all do the same with the same shape.

That is fine while `Upload.file.url` is a plain path. It stops being fine the
moment uploads move to a bucket, which is exactly the move that makes them
survive a deploy: `S3_QUERYSTRING_AUTH` defaults ON and `S3_URL_EXPIRE` to an
hour, so `file.url` is a SIGNED url. Storing one means every post's audio and
video goes dead sixty minutes after it is posted — the same "this recording
won't load" the missing-file bug produced, with a different cause and no
missing file. Turning on durable storage would have broken playback for
everyone, and the fix for losing music would have looked like a new bug.

So nothing persists a storage URL any more. What is stored is this route, and
this route resolves the address FRESHLY on every request: a new signature each
time on a bucket, the plain media path on local disk. A link a member shares,
or a post from two years ago, keeps working because the signing happens when
somebody asks, not when somebody uploads.

There is a second reason, and it is worse. Every one of those columns is
`max_length=500` and every writer truncates to it (`str(...)[:500]`). A signed
S3 URL is routinely longer than that — the query string alone carries the
credential, the date, the expiry, the signed headers and a 64-character
signature. So the stored link would not merely have expired; it would have been
cut in half on the way in, and been wrong from the first second.

Two details:

* The filename is IN the path, last. `upload_behind()` and `take_bytes_for()`
  find the Upload behind a post's media by the tail of its URL — MEDIA_URL
  differs between disk, Render and a CDN, so a whole-URL comparison matches in
  exactly one environment. Ending this route with the stored basename means
  every one of those lookups keeps working untouched, and the coach still
  finds the take on a post.
* No trailing slash, for the same reason: `rsplit("/", 1)[-1]` of a path that
  ends in one is the empty string, and the tail lookups would all miss.

It is unauthenticated, like the `/media/` route it replaces. Adding auth here
would break the thing it exists for — `<audio src>` sends no Authorization
header — so this is the same exposure as before and not a step down from it.
"""
import os

from django.http import HttpResponseRedirect
from django.urls import reverse
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Upload


def stable_media_url(upload, request=None):
    """The address to hand out for `upload` — and the only one safe to store.

    Absolute when a request is given, because the frontend is on another origin
    and a relative path would resolve against it.
    """
    if not upload or not getattr(upload, "file", None) or not upload.file.name:
        return ""
    path = reverse("economy-media-file",
                   args=[upload.pk, os.path.basename(upload.file.name)])
    return request.build_absolute_uri(path) if request is not None else path


class MediaFileView(APIView):
    """Resolve an upload to wherever its bytes actually are, right now."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, pk, filename):
        up = Upload.objects.filter(pk=pk).only("id", "file").first()
        # The id and the name have to agree. The id alone would let anybody
        # walk the range and collect every filename on the platform; requiring
        # the name means a link is only usable by somebody who was given it,
        # which is the property the old `/media/` path had for free.
        if not up or not up.file or os.path.basename(up.file.name) != filename:
            return Response({"detail": "That file isn't here."},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            target = up.file.url
        except Exception:                                # pragma: no cover
            # A storage backend that can't even name the file. Nothing to
            # redirect to, and a 500 here would be blamed on the player.
            return Response({"detail": "That file isn't here."},
                            status=status.HTTP_404_NOT_FOUND)
        return HttpResponseRedirect(target)
