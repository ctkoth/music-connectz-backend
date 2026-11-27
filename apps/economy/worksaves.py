"""StatZ work autosave: a screen's unsaved work, kept on the member's account by itself.

A row is one document of one app: the JSON that screen needs to put its work back (a draft, an episode's arrangement, a
set of settings). Pictures and sound are not in here. A screen that has them keeps those as ordinary uploads and names
them inside `data`, so a row stays small and the storage stays where a member can see it.

Writing is StatZ's: keeping work for someone is an automation, and automations are StatZ's (CLAUDE.md). Reading is not:
a member who lapses still gets their own work back, so a lapse never turns into a loss. The sample does not count, so a
15-minute window cannot leave a copy behind.

A write is stamped like a DAW session: a copy older than the one on the account is refused, so a device that was offline
cannot overwrite newer work it never saw. Its own copy stays on the device, and the member decides what to do with it.
"""
import json
import re

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import TIER_DEBUG, TIER_STATZ, WorkSave, membership_for

# A closed list: an app opts in by name, so this table cannot become general storage.
APPS = ("animez", "sentenceconnectz", "sentencez", "journalz", "mixconnectz", "postz")
MAX_WORKS_PER_APP = 50
MAX_JSON_BYTES = 1_000_000
NAME_MAX = 120
_WID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
WHO = "Kept on your account so it is still there if this device is lost. StatZ keeps it automatically."


def is_statz(user):
    return membership_for(user).tier in (TIER_STATZ, TIER_DEBUG)


def _summary(r):
    return {"app": r.app, "wid": r.wid, "name": r.name, "updated": r.updated_ms}


class WorkSavesView(APIView):
    """GET the member's kept work for one app (summaries only)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        app = str(request.query_params.get("app") or "")
        if app not in APPS:
            return Response({"detail": "That app doesn't keep work on your account."}, status=status.HTTP_400_BAD_REQUEST)
        rows = WorkSave.objects.filter(owner=request.user, app=app).order_by("-updated_ms")
        return Response({"works": [_summary(r) for r in rows], "who": WHO, "limit": MAX_WORKS_PER_APP,
                         "statz": is_statz(request.user)})


class WorkSaveDetailView(APIView):
    """GET one kept work in full; PUT saves it (StatZ); DELETE removes the copy on the account."""

    permission_classes = [IsAuthenticated]

    def get(self, request, app, wid):
        r = WorkSave.objects.filter(owner=request.user, app=app, wid=wid).first()
        if r is None:
            return Response({"detail": "That work isn't on your account."}, status=status.HTTP_404_NOT_FOUND)
        return Response({**_summary(r), "data": r.data})

    def put(self, request, app, wid):
        if app not in APPS:
            return Response({"detail": "That app doesn't keep work on your account."}, status=status.HTTP_400_BAD_REQUEST)
        if not _WID.match(wid):
            return Response({"detail": "That id isn't valid."}, status=status.HTTP_400_BAD_REQUEST)
        if not is_statz(request.user):
            return Response({"detail": "Keeping your work on your account automatically is a StatZ feature."},
                            status=status.HTTP_403_FORBIDDEN)
        d = request.data or {}
        data = d.get("data")
        if not isinstance(data, dict):
            return Response({"detail": "data (an object) required."}, status=status.HTTP_400_BAD_REQUEST)
        if len(json.dumps(data)) > MAX_JSON_BYTES:
            return Response({"detail": "That is too much to keep on your account."},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        try:
            stamp = int(d.get("updated"))
        except (TypeError, ValueError):
            return Response({"detail": "updated (ms) required."}, status=status.HTTP_400_BAD_REQUEST)
        name = " ".join(str(d.get("name") or "").split())[:NAME_MAX]
        row = WorkSave.objects.filter(owner=request.user, app=app, wid=wid).first()
        if row is None:
            held = WorkSave.objects.filter(owner=request.user, app=app).count()
            if held >= MAX_WORKS_PER_APP:
                return Response({"detail": f"You're keeping {held} of these on your account — remove one first."},
                                status=status.HTTP_409_CONFLICT)
            row = WorkSave(owner=request.user, app=app, wid=wid)
        elif stamp < row.updated_ms:
            return Response({"detail": "A newer copy of this is on your account.", "stored_updated": row.updated_ms},
                            status=status.HTTP_409_CONFLICT)
        row.name, row.data, row.updated_ms = name, data, stamp
        row.save()
        return Response(_summary(row))

    def delete(self, request, app, wid):
        WorkSave.objects.filter(owner=request.user, app=app, wid=wid).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
