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
from .media import stable_media_url
from .models import LookShare, Upload, notify, profile_for

User = get_user_model()
SALT = "mcz.lookshare"
MAX_AGE = 24 * 3600

SHARE_NOTE = ("Only if you want to: share this reading with one person, or with any verified adult who has "
              "the link. They see the numbers and the coach's words, and your photo only if you kept it and tick "
              "Show my photo. Delete it any time.")
INVITE_WHAT = ("@{handle} invited you to get your own LookZMaxZ reading: you upload a photo of yourself, the "
               "coach scores your hair, skin, teeth and styling 1-10 and says how to lift each. It's 18+ with an "
               "ID check, your photo is kept only if you choose, and the result is yours — you choose whether @{handle} sees it.")
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


def sign(user, payload, photo=None):
    """`photo` is the Upload the member chose to keep with this reading (or None). Only its id
    rides in the signature, so a share can only ever show a photo the reading was made from."""
    data = {"u": user.id, "r": snapshot(payload)}
    if photo is not None:
        data["p"] = photo.id
    return signing.dumps(data, salt=SALT, compress=True)


def photo_url(share, request=None):
    """The kept photo's address, or "" when none was shown or the owner has since deleted it."""
    pid = (share.payload or {}).get("photo_upload_id")
    if not pid:
        return ""
    up = Upload.objects.filter(pk=pid, user_id=share.user_id, missing_since__isnull=True).first()
    return stable_media_url(up, request) if up else ""


def new_token():
    return secrets.token_hex(12)


def view_of(share, viewer, request=None):
    body = {k: v for k, v in (share.payload or {}).items() if k != "photo_upload_id"}
    return {"token": share.token, "username": share.user.username,
            "to": share.to_user.username if share.to_user_id else None,
            "mine": share.user_id == viewer.id, "created_at": share.created_at.isoformat(),
            **body, "photo_url": photo_url(share, request)}


class LookShareView(APIView):
    """GET your shares (made and received); POST {reading, to?} to make one from a signed reading."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _adult(request.user):
            return Response({"mine": [], "to_me": [], "note": SHARE_NOTE})
        mine = LookShare.objects.filter(user=request.user).select_related("user", "to_user")[:20]
        to_me = LookShare.objects.filter(to_user=request.user).select_related("user", "to_user")[:20]
        return Response({"mine": [view_of(s, request.user, request) for s in mine],
                         "to_me": [view_of(s, request.user, request) for s in to_me], "note": SHARE_NOTE})

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
        payload = dict(data.get("r") or {})
        if data.get("p") and str(request.data.get("show_photo", "")).lower() in ("1", "true", "yes", "on"):
            if Upload.objects.filter(pk=data["p"], user=request.user).exists():
                payload["photo_upload_id"] = data["p"]
        share = LookShare.objects.create(token=new_token(), user=request.user, to_user=to, payload=payload)
        if to:
            notify(to, "system", f"@{request.user.username} shared their LookZMaxZ reading with you.",
                   actor=request.user, item_id=f"lookshare:{share.token}")
        return Response(view_of(share, request.user, request), status=status.HTTP_201_CREATED)


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
        return Response(view_of(share, request.user, request))

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


POST_NOTE = ("Post your reading to PostZ: the numbers and the coach's words, and your photo if it is kept with this "
             "reading and you tick it. Only the person in the reading can post it. Free.")


def post_text(payload):
    """The post, built from the stored snapshot — nothing the request sends reaches it."""
    def n(v):
        return "—" if v is None else (str(int(v)) if float(v).is_integer() else f"{v:.1f}")
    lines = [f"Overall {n(payload.get('overall'))}/10"]
    lines.append(" · ".join(f"{s.get('emoji', '')} {s.get('label', k)} {n(s.get('score'))}"
                            for k, s in (payload.get("sectors") or {}).items()))
    if payload.get("verdict"):
        lines.append(payload["verdict"])
    lines.append("AI-read from a photo I chose — hair, skin, teeth and styling, never face shape or body. "
                 "One photo, not a verdict on me.")
    return "\n\n".join(x for x in lines if x)


class LookSharePostView(APIView):
    """POST lookmaxz/share/<token>/post/ {visibility}: the person in the reading posts it to PostZ."""
    permission_classes = [IsAuthenticated]

    def get(self, request, token):
        return Response({"note": POST_NOTE})

    def post(self, request, token):
        from .postz import create_post
        share = LookShare.objects.filter(token=str(token)[:32], user=request.user).first()
        if not share:
            return Response({"detail": "Only the person in the reading can post it."}, status=status.HTTP_404_NOT_FOUND)
        if not _adult(request.user):
            return Response({"detail": "Posting a reading is for verified adults."}, status=status.HTTP_403_FORBIDDEN)
        vis = str(request.data.get("visibility") or "public").lower()
        body = {"title": "My LookZMaxZ reading", "visibility": vis, "description": post_text(share.payload)}
        if str(request.data.get("photo", "")).lower() in ("1", "true", "yes", "on"):
            url = photo_url(share, request)
            if url:
                body.update({"media_url": url, "media_type": "image"})
        post, _info, err = create_post(request.user, body)
        if err:
            body, code = err
            return Response(body, status=code)
        return Response({"post_id": post.id, "visibility": post.visibility, "url": f"/p/{post.id}"},
                        status=status.HTTP_201_CREATED)


KEEP_NOTE = ("Keep my photo: stored as one of your uploads (it counts toward your storage, and you can delete it any "
             "time), so you can show it with this reading when you share or post it. Off unless you tick it.")


def keep_photo(user, data, content_type):
    """(Upload, "") or (None, reason): the photo the member just had read, kept because they asked.

    Goes through the coach's own `keep_take`, so the same per-file and storage limits apply and a
    photo that does not fit is still read, just not kept."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    from .takekeep import keep_take
    ext = {"image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(content_type, "jpg")
    up, why = keep_take(user, SimpleUploadedFile(f"lookzmaxz.{ext}", data, content_type=content_type))
    return up, why.replace("It was still scored.", "It was still read.")
