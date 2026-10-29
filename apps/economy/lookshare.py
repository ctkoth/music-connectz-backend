"""LookZMaxZ: invite somebody to get THEIR OWN reading, and let them choose to show it.

Corey: a woman asked if she was a 10/10 and he wanted to get her score and show her. Rating her
from a photo HE uploads stays out — the app cannot tell whether she agreed, and that is the line
the reading is built on (self-only, verified adults, nothing stored). What gets him there is the
other way round:

* **The invite** (`/rate/<handle>`, a public page): she is told what it is, that it is 18+ and
  verified, that she rates her own photo, that nothing is kept, and that sharing it back is her
  choice. Joining from it credits the inviter like any invite (`?ref=`).
* **The share** is hers to make. A reading answers with `share` — a SERVER-SIGNED snapshot of what
  the coach said (`snapshot`), valid for a day — and only that token can become a `LookShare`, so a
  share can never carry a number the coach did not give (the same rule `ScoreShare` follows).
  It holds numbers and words, never the photo, and leaves out the opt-in sectors (proportions,
  physique) and Body: a body read is the part most likely to hurt passed around.
* **Who sees it** is who she names (or any verified adult with the link, if she names nobody), and
  she can delete it at any time. Viewing is adults-only for the same reason the reading is.
"""
import secrets

from django.contrib.auth import get_user_model
from django.core import signing
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import lookmaxz as lm
from .models import LookShare, notify, profile_for

User = get_user_model()
SALT = "mcz.lookshare"
MAX_AGE = 24 * 3600

SHARE_NOTE = ("Only if you want to: share this reading with one person, or with any verified adult who has "
              "the link. They see the numbers and the coach's words — never your photo. Delete it any time.")
INVITE_WHAT = ("@{handle} invited you to get your own LookZMaxZ reading: you upload a photo of yourself, the "
               "coach scores your hair, skin, teeth and styling 1-10 and says how to lift each. It's 18+ with an "
               "ID check, your photo is kept nowhere, and the result is yours — you choose whether @{handle} sees it.")
INVITE_RULE = ("Nobody can rate you from a photo they upload. The only way @{handle} sees a score is if you get "
               "your own and share it.")
INVITE_SHARE = "Get your own LookZMaxZ reading — it's yours, and you choose who sees it."


def _adult(user):
    return bool(user and user.is_authenticated and profile_for(user).verified_18plus)


def snapshot(payload):
    """What a share may carry: the asked-for photo sectors' numbers and the coach's words."""
    sectors = {}
    for k, s in (payload.get("sectors") or {}).items():
        meta = lm.SECTORS.get(k) or {}
        if k not in lm.PHOTO_SECTORS or meta.get("opt_in"):
            continue
        sectors[k] = {"label": meta.get("label", k), "emoji": meta.get("emoji", ""), "score": s.get("score"),
                      "factors": {f: {"label": lab, "score": (s.get("scores") or {}).get(f)}
                                  for f, lab in meta.get("factors", {}).items()}}
    return {"overall": payload.get("overall"), "verdict": payload.get("verdict", ""),
            "working": list(payload.get("working") or [])[:5], "photo_quality": payload.get("photo_quality"),
            "sectors": sectors, "caveat": lm.CAVEAT, "scale": lm.SCALE}


def sign(user, payload):
    return signing.dumps({"u": user.id, "r": snapshot(payload)}, salt=SALT, compress=True)


def _view(share, viewer):
    return {"token": share.token, "username": share.user.username,
            "to": share.to_user.username if share.to_user_id else None,
            "mine": share.user_id == viewer.id, "created_at": share.created_at.isoformat(),
            **share.payload}


class LookShareView(APIView):
    """GET your shares (made and received); POST {reading, to?} to make one from a signed reading."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _adult(request.user):
            return Response({"mine": [], "to_me": [], "note": SHARE_NOTE})
        mine = LookShare.objects.filter(user=request.user).select_related("user", "to_user")[:20]
        to_me = LookShare.objects.filter(to_user=request.user).select_related("user", "to_user")[:20]
        return Response({"mine": [_view(s, request.user) for s in mine],
                         "to_me": [_view(s, request.user) for s in to_me], "note": SHARE_NOTE})

    def post(self, request):
        if not _adult(request.user):
            return Response({"detail": "Sharing a reading is for verified adults."}, status=status.HTTP_403_FORBIDDEN)
        try:
            data = signing.loads(str(request.data.get("reading") or ""), salt=SALT, max_age=MAX_AGE)
        except signing.SignatureExpired:
            return Response({"detail": "That reading is over a day old — get a fresh one to share."},
                            status=status.HTTP_400_BAD_REQUEST)
        except signing.BadSignature:
            return Response({"detail": "Only a reading the coach gave you can be shared."},
                            status=status.HTTP_400_BAD_REQUEST)
        if data.get("u") != request.user.id:
            return Response({"detail": "Only the person in the reading can share it."},
                            status=status.HTTP_403_FORBIDDEN)
        to = None
        handle = str(request.data.get("to") or "").strip().lstrip("@")
        if handle:
            to = User.objects.filter(username__iexact=handle).first()
            if not to:
                return Response({"detail": f"No member called @{handle}."}, status=status.HTTP_404_NOT_FOUND)
            if to.id == request.user.id:
                return Response({"detail": "That's you — leave it blank to share by link."},
                                status=status.HTTP_400_BAD_REQUEST)
            if not _adult(to):
                return Response({"detail": f"@{to.username} hasn't verified they're an adult, so they can't "
                                           "see a reading. Nothing was shared."}, status=status.HTTP_400_BAD_REQUEST)
        share = LookShare.objects.create(token=secrets.token_hex(12), user=request.user, to_user=to,
                                         payload=data.get("r") or {})
        if to:
            notify(to, "system", f"@{request.user.username} shared their LookZMaxZ reading with you.",
                   actor=request.user, item_id=f"lookshare:{share.token}")
        return Response(_view(share, request.user), status=status.HTTP_201_CREATED)


class LookShareDetailView(APIView):
    """GET one share (owner, the named member, or any verified adult if it names nobody); DELETE yours."""
    permission_classes = [IsAuthenticated]

    def _find(self, token):
        return LookShare.objects.select_related("user", "to_user").filter(token=str(token)[:32]).first()

    def get(self, request, token):
        share = self._find(token)
        allowed = share and (share.user_id == request.user.id or (
            _adult(request.user) and (share.to_user_id in (None, request.user.id))))
        if not allowed:
            # One answer for "gone", "not yours" and "not an adult": a share's existence is not public.
            return Response({"detail": "That reading isn't shared with you, or was taken down."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(_view(share, request.user))

    def delete(self, request, token):
        share = self._find(token)
        if not share or share.user_id != request.user.id:
            return Response({"detail": "Only the person in the reading can take it down."},
                            status=status.HTTP_404_NOT_FOUND)
        share.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LookInviteView(APIView):
    """GET /lookmaxz/invite/<handle>/ — the words on the public invite page. Open logged-out."""
    permission_classes = [AllowAny]

    def get(self, request, handle):
        who = User.objects.filter(username__iexact=str(handle)[:40]).first()
        if not who:
            return Response({"detail": "No member by that name."}, status=status.HTTP_404_NOT_FOUND)
        h = who.username
        return Response({"username": h, "what": INVITE_WHAT.format(handle=h), "rule": INVITE_RULE.format(handle=h),
                         "share_text": INVITE_SHARE, "link": f"/rate/{h}"})
