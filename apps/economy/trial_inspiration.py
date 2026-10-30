"""Inspiration at the free door: one take heard against a song the visitor wants to sound like.

The member feature (`matchref.py`) is the product's most persuasive comparison — "here is exactly
what separates you from that record" — and until now a stranger could not have it: the trial refused
anything but a scored take. This opens it, under the rules the door already lives by.

* **It spends the SAME free take, not an extra one.** A comparison is one model call that reads two
  recordings, so it is dearer than a scored take; making it a separate allowance would double what a
  stranger can cost us. The door's own gate (`trial.trial_gate`) refuses it for the same three reasons
  in the same words — this browser's takes are used, this address is busy, the day's ceiling is met —
  and the screen says BEFORE the press that it uses the free take.
* **The take is the visitor's own performance, always a file.** A link on the take side would let the
  free take be spent scoring somebody else's video, which is the reference listen the door has always
  refused. The REFERENCE is a file or a YouTube link; a post, an upload or a diary page is a member's
  and is never read here, whatever ids the request carries.
* **It is one comparison function.** `matchref.run_match` is what the member's endpoint calls, so what
  the coach is asked, the deadline, the failure sentences and the whitelist on the reply cannot drift
  between the two doors.
* **Nothing is saved as the visitor's.** No share card, no claim token, no history: a gap to somebody
  else's record is not a measurement of them, and there is nothing a later account could claim. The
  row it writes is the door's ledger — the address ceiling and the global cap count rows, and a model
  call that left none would be money spent off the books — and carries only the headline numbers.
* **A failed run spends nothing.** A comparison the coach could not read writes no row; an unscorable
  one (silence, the wrong file) is written as `scored=False`, which counts against the address and the
  day but not against the visitor's own free take — the rule `TrialTake.scored` exists for.
"""
import secrets

from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import matchref
from .gemini import _key
from .instruments import profile_for_app, scores_for
from .models import TRIAL_MAX_MB, TrialTake
from .trial import takes_left, trial_gate

NOTE = ("This uses one of your free takes on this coach — the same one a scored take would, so you "
        "choose which to spend it on. Nothing is saved: your take and the reference are read for this "
        "comparison and then dropped.")
TAKE_NEEDED = "Record or attach your own take first — the free comparison is your performance against a reference."
REFERENCE_NEEDED = "Add the reference: upload a track, or paste a YouTube link."
TOO_BIG = "That file is too big for a free run — keep it under {mb}MB."
NOT_MEDIA = "That isn't audio or video. Use m4a, mp3, wav, ogg or mp4."


def inspiration_offer(app_key):
    """What the trial's GET publishes about this, so the control renders only what is true and
    states what it spends before it is pressed. Keys are added to that answer, never changed."""
    return {
        "offered": bool(_key()),
        "feature": matchref.LABEL,
        "uses_free_take": True,
        "note": NOTE,
        "notice": matchref.NOTICE,
        "eq_note": matchref.EQ_NOTE,
        "reference_sources": ["file", "link"],
        "link_window_seconds": matchref.LINK_WINDOW_SECONDS,
        "link_note": matchref.LINK_NOTE,
        "link_sources": matchref.LINK_SOURCES,
        "max_mb": TRIAL_MAX_MB,
        "scores": scores_for(app_key),
    }


def _file_slot(f):
    ctype = (getattr(f, "content_type", "") or "").lower()
    return matchref._Slot(f, ctype)


class TrialInspirationView(APIView):
    """POST /api/<key>/trial/inspiration/ — one take against one reference, no account."""

    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]
    app_key = "singz"

    def post(self, request):
        ip, anon_id, blocked = trial_gate(request)
        if blocked:
            return blocked
        take_file = request.FILES.get("take")
        if not take_file:
            return Response({"detail": TAKE_NEEDED}, status=status.HTTP_400_BAD_REQUEST)
        take = _file_slot(take_file)

        ref_file = request.FILES.get("reference")
        if ref_file:
            ref = _file_slot(ref_file)
        else:
            url = request.data.get("reference_url")
            if url in (None, ""):
                return Response({"detail": REFERENCE_NEEDED}, status=status.HTTP_400_BAD_REQUEST)
            link, why = matchref.classify_link(url)
            if why:
                return Response({"detail": why, "link_unsupported": True, "side": "reference"},
                                status=status.HTTP_400_BAD_REQUEST)
            ref = matchref._Slot(None, "video/mp4", link=link)

        for side in (take, ref):
            if side.link is not None:
                continue
            if not side.ctype.startswith(("audio/", "video/")) or not side.mime:
                return Response({"detail": NOT_MEDIA}, status=status.HTTP_400_BAD_REQUEST)
            if side.file.size == 0:
                return Response({"detail": "One of those files is empty. Nothing was used."},
                                status=status.HTTP_400_BAD_REQUEST)
            if side.file.size > TRIAL_MAX_MB * 1024 * 1024:
                return Response({"detail": TOO_BIG.format(mb=TRIAL_MAX_MB)},
                                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        if not _key():
            return Response({"detail": "The coach isn't available right now. Nothing was used."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        genre = str(request.data.get("genre") or "unspecified")[:60]
        out, failed = matchref.run_match(self.app_key, take, ref, genre)
        if failed is not None:
            if (failed.data or {}).get("unscorable"):
                TrialTake.objects.create(
                    token=secrets.token_urlsafe(24), app_key=self.app_key, ip=ip, anon_id=anon_id,
                    result={"inspiration": True}, scored=False)
                failed.data = {**failed.data, "trial": True, "takes_left": takes_left(anon_id)}
            return failed

        overall = out.get("overall") or {}
        TrialTake.objects.create(
            token=secrets.token_urlsafe(24), app_key=self.app_key, ip=ip, anon_id=anon_id,
            result={"inspiration": True, "closeness": out.get("closeness"),
                    "take": overall.get("take"), "reference": overall.get("reference")},
            scored=True)
        return Response({
            **out, "match": True, "trial": True, "saved": False, "reference": True,
            "feature": matchref.LABEL, "cost_cents": 0, "uses_free_take": True,
            "eq_note": matchref.EQ_NOTE, "lyric_note": matchref.LYRIC_NOTE, "genre": genre,
            "label": profile_for_app(self.app_key)["label"],
            "sources": {"take": take.describe(), "reference": ref.describe()},
            "takes_left": takes_left(anon_id),
        }, status=status.HTTP_201_CREATED)
