"""A member asks: which of MY files is actually still on the server?

FileZ lists every `Upload` row, and a row outlives its bytes — the container's
disk was rebuilt on every deploy until a disk was mounted, so rows from before
that still point at files that are not there. They rendered as ordinary players
that sat at 0:00 / 0:00 and read as "corrupt", which is a worse thing to tell a
member than the truth: the recording is GONE, and there is nothing to repair.

This is the member-facing half of `manage.py reconcile_uploads`, and it keeps
that command's rules rather than inventing its own:

- **Only something that WENT AND LOOKED may stamp `missing_since`.** This asks
  storage `exists()` for each file, which is looking. The list view that serves
  the mark never looks; a feed of files must not become a storage call per row.
- **It is the member's OWN files, on a press.** Not a read path, not a sweep of
  the platform, and capped (`LIMIT`) so one press is a bounded number of calls.
- **A backend that cannot answer is not a file that is gone.** An unreachable
  bucket marks nothing and the answer says how many could not be checked.
- **It CLEARS the mark for a file that came back**, so a restored file stops
  being called lost.
- **Nothing is deleted.** The row is the record of what was lost, and the member
  decides about it (the delete button frees nothing — a lost file is not counted
  against storage — but it tidies the list).
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Upload, mark_upload_found, mark_upload_missing

LIMIT = 500


def check_uploads(qs):
    """Ask storage about each upload in `qs`; stamp or clear. Returns the counts."""
    out = {"checked": 0, "present": 0, "gone": 0, "came_back": 0, "unreadable": 0, "newly_gone": []}
    for up in qs:
        if not up.file or not up.file.name:
            out["unreadable"] += 1
            continue
        try:
            there = up.file.storage.exists(up.file.name)
        except Exception:
            out["unreadable"] += 1
            continue
        out["checked"] += 1
        if there:
            out["present"] += 1
            if up.missing_since and mark_upload_found(up):
                out["came_back"] += 1
        else:
            out["gone"] += 1
            if mark_upload_missing(up):
                out["newly_gone"].append(up.pk)
    return out


class UploadCheckView(APIView):
    """POST: look for every one of the caller's files in storage and say which are gone."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        qs = request.user.uploads.all().order_by("-created_at")[:LIMIT]
        r = check_uploads(list(qs))
        r.pop("newly_gone", None)
        r["limit"] = LIMIT
        return Response(r)
