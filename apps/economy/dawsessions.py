"""DAW sessions that follow a member to another device (opt-in, per session).

A session is made and autosaved in the browser (`src/daw/store.js`), so another device never saw it.
This is the second copy a member chooses to keep on their account. Three decisions:

- **The audio is ordinary uploads.** Each source is an `Upload` under the member's own storage quota,
  so its cost is the quota they already have (said on the control before it is pressed, in MB), it
  shows in FileZ, and nothing here is a second price or a second store. A tier says how MUCH (storage),
  never whether.
- **The server keeps no opinion about the session's contents.** The editor's own `cleanSession` owns the
  shape; this checks only that it is a bounded JSON object and that every sound it names is one of the
  caller's own uploads (so a request cannot attach somebody else's file).
- **Last edit wins, by the client's clock stamp** (`updated`, ms). A write older than what is stored is
  refused with 409 and the stored stamp, so a device that was offline cannot silently bury a newer edit.

Removing the cloud copy removes the uploads it made, unless another cloud session of the member still
names one (a copy made in another DAW shares sources). It never touches the device's own copy.
"""
import json

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DawSession, Upload

MAX_SESSIONS = 200
MAX_JSON_BYTES = 2_000_000
SID_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
WHO = ("Kept on your account so it opens on your other devices. The sound counts against your storage "
       "and shows in FileZ. Nobody else sees it.")


def _sid_ok(sid):
    return 0 < len(sid) <= 60 and all(c in SID_OK for c in sid)


def _summary(r):
    s = r.data if isinstance(r.data, dict) else {}
    return {"id": r.sid, "app": r.app, "name": r.name, "updated": r.updated_ms,
            "genre": str(s.get("genre") or "")[:40], "key": str(s.get("key") or "")[:12], "bpm": s.get("bpm"),
            "skills": s.get("skills") if isinstance(s.get("skills"), list) else []}


def _delete_unshared_audio(user, row):
    mine = {int(v) for v in (row.audio or {}).values() if str(v).isdigit()}
    if not mine:
        return
    for other in DawSession.objects.filter(owner=user).exclude(pk=row.pk):
        mine -= {int(v) for v in (other.audio or {}).values() if str(v).isdigit()}
    for u in Upload.objects.filter(user=user, pk__in=mine):
        try:
            u.file.delete(save=False)
        except Exception:
            pass
        u.delete()


class DawSessionsView(APIView):
    """GET the member's cloud sessions (summaries only)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = list(DawSession.objects.filter(owner=request.user))
        return Response({"sessions": [_summary(r) for r in rows], "who": WHO, "limit": MAX_SESSIONS})


class DawSessionDetailView(APIView):
    """GET one in full with where each sound can be fetched; PUT saves it; DELETE removes the cloud copy."""

    permission_classes = [IsAuthenticated]

    def get(self, request, sid):
        from .views import _upload_dict
        r = DawSession.objects.filter(owner=request.user, sid=sid).first()
        if not r:
            return Response({"detail": "That session isn't on your account."}, status=status.HTTP_404_NOT_FOUND)
        ids = [int(v) for v in (r.audio or {}).values() if str(v).isdigit()]
        ups = {u.id: u for u in Upload.objects.filter(user=request.user, pk__in=ids)}
        audio = {}
        for src, uid in (r.audio or {}).items():
            u = ups.get(int(uid)) if str(uid).isdigit() else None
            audio[src] = ({"id": u.id, "url": _upload_dict(u, request)["url"], "missing": bool(u.missing_since),
                           "size_bytes": u.size_bytes} if u else {"id": None, "url": None, "missing": True, "size_bytes": 0})
        return Response({**_summary(r), "session": r.data, "audio": audio})

    def put(self, request, sid):
        if not _sid_ok(sid):
            return Response({"detail": "That session id isn't valid."}, status=status.HTTP_400_BAD_REQUEST)
        d = request.data or {}
        session = d.get("session")
        if not isinstance(session, dict) or not isinstance(session.get("sources", {}), dict):
            return Response({"detail": "session (an object) required."}, status=status.HTTP_400_BAD_REQUEST)
        if len(json.dumps(session)) > MAX_JSON_BYTES:
            return Response({"detail": "That session's arrangement is too large to keep on your account."},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        try:
            stamp = int(d.get("updated"))
        except (TypeError, ValueError):
            return Response({"detail": "updated (ms) required."}, status=status.HTTP_400_BAD_REQUEST)
        raw = d.get("audio") if isinstance(d.get("audio"), dict) else {}
        wanted = {}
        for src in session.get("sources", {}):
            v = raw.get(src)
            if str(v).isdigit():
                wanted[str(src)] = int(v)
        owned = set(Upload.objects.filter(user=request.user, pk__in=set(wanted.values())).values_list("id", flat=True))
        audio = {k: v for k, v in wanted.items() if v in owned}
        row = DawSession.objects.filter(owner=request.user, sid=sid).first()
        if row is None and DawSession.objects.filter(owner=request.user).count() >= MAX_SESSIONS:
            return Response({"detail": f"You're keeping {MAX_SESSIONS} sessions on your account — remove one first."},
                            status=status.HTTP_409_CONFLICT)
        if row is not None and stamp < row.updated_ms:
            return Response({"detail": "A newer version of this session is on your account.", "stored_updated": row.updated_ms},
                            status=status.HTTP_409_CONFLICT)
        if row is None:
            row = DawSession(owner=request.user, sid=sid)
        row.app = str(d.get("app") or "")[:30]
        row.name = " ".join(str(session.get("name") or "").split())[:60]
        row.data, row.audio, row.updated_ms = session, audio, stamp
        row.save()
        return Response(_summary(row))

    def delete(self, request, sid):
        row = DawSession.objects.filter(owner=request.user, sid=sid).first()
        if row:
            _delete_unshared_audio(request.user, row)
            row.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
