"""A member puts back a file the server lost, from the copy their own device kept.

The server's upload storage was temporary for a while (erased on every deploy), so rows outlived their bytes. The frontend now keeps a copy of
every upload on the member's own device, and this is the other half: the member sends that copy back and it goes behind the SAME row, under the
SAME stored name, so every post, master and link that already points at the file plays again with nothing re-attached.

The rules, each one because the alternative is worse:

- **Only the member's own file, and only one that is actually gone.** A file that is still in storage is refused (409): restore must never be a
  way to swap the bytes behind a live post. "Gone" is the row's `missing_since`, or storage saying it is not there (this asks, like the
  member-facing check does, rather than trusting a stale mark in either direction).
- **The same size as the original, to the byte.** The row recorded how many bytes were uploaded; a copy of the same file is that many. A
  different size is a different file, and putting it behind somebody's post would change what the post says. Refused (400) with both numbers.
- **The same stored name.** Media addresses carry the stored file name, so a storage that quietly picked another name for the write would leave
  every existing link dead while reporting success. If the name is not the one asked for, the write is undone and the answer is 503.
- **Quota still applies.** A lost file stopped counting against storage; putting it back counts again, and the member's plan decides whether it
  fits, with the same sentence an upload gets.
- **Said only when it is true.** 200 only for a file storage now holds at the recorded size; otherwise it is removed and the answer is 503 and
  nothing changed.
"""
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import limits_for
from .models import membership_for, storage_used_bytes, mark_upload_found

MB = 1024 * 1024


def _is_gone(up):
    if up.missing_since:
        return True
    try:
        return not (up.file.name and up.file.storage.exists(up.file.name))
    except Exception:
        return False        # storage cannot answer: not "gone", so nothing is replaced on a guess


class UploadRestoreView(APIView):
    """POST /api/economy/uploads/<pk>/restore/ with multipart `file`: put a lost file back behind its own row."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        from .views import _storage_summary, _stored_intact, _upload_dict

        up = request.user.uploads.filter(pk=pk).first()
        if up is None:
            return Response({"detail": "That file isn't yours, or was deleted."}, status=status.HTTP_404_NOT_FOUND)
        f = request.FILES.get("file")
        if not f:
            return Response({"detail": "file (multipart) required"}, status=status.HTTP_400_BAD_REQUEST)
        if not _is_gone(up):
            return Response({"detail": "That file is still on the server, so there is nothing to restore."}, status=status.HTTP_409_CONFLICT)
        if f.size != up.size_bytes:
            return Response({"detail": f"That isn't the same file: yours is {f.size} bytes and the original was {up.size_bytes}. "
                                       "Only a copy of the same recording can be put back, so nothing was changed."},
                            status=status.HTTP_400_BAD_REQUEST)
        m = membership_for(request.user)
        lim = limits_for(m.tier)
        if storage_used_bytes(request.user) + f.size > lim["storage_mb"] * MB:
            return Response({"detail": f"putting it back would exceed your {lim['storage_mb']}MB storage quota", **_storage_summary(request.user, m.tier)},
                            status=status.HTTP_409_CONFLICT)

        storage, name = up.file.storage, up.file.name
        try:
            if storage.exists(name):                   # a partial or wrong-size leftover under the same name
                storage.delete(name)
            saved = storage.save(name, f)
        except Exception:
            saved = None
        if saved != name:
            try:
                if saved:
                    storage.delete(saved)
            except Exception:
                pass
            return Response({"detail": "That didn't save on our side, so nothing was changed. Please try again."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not _stored_intact(up):
            try:
                storage.delete(name)
            except Exception:
                pass
            return Response({"detail": "That didn't save on our side, so nothing was changed. Please try again."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        mark_upload_found(up)
        up.refresh_from_db()
        return Response({"upload": _upload_dict(up, request), **_storage_summary(request.user, m.tier)}, status=status.HTTP_200_OK)
