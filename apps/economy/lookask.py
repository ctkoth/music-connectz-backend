"""LookZMaxZ: ask a member to approve a reading of a photo of THEM (Corey's "build it").

Scoring somebody from a photo somebody else uploads stays out when they have no say. This is the
version where they do: the requester uploads the photo and names the person, and NOTHING is read
until that person sees the photo and approves it. Then it is read, the result becomes a share
(`LookShare`) from them to the requester, and they can take it down like any share.

* **Both are verified adults**, and a block either way refuses. The person in the photo must be
  verified because they are the one approving a looks reading of themselves.
* **The photo is held only while pending** — up to `EXPIRE_DAYS` — and deleted the moment the request
  is approved, declined, cancelled, expires or fails. Only the requester and the person in it can see it.
* **The requester pays**, at the price stated on their button, and only for a reading that came back:
  a decline, an expiry or an unreadable photo costs nothing.
* **Bounded:** one pending request per pair, `MAX_PENDING` in flight per requester, so it cannot be used
  to spam somebody with photos.
* **A decline tells nobody anything they can push on.** The requester sees "not approved" and no reason.
"""
import base64
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import lookmaxz as lm
from . import lookshare
from .attractivenessz_view import presentation_price
from .lookmaxz_view import _photo
from .models import LookRequest, LookShare, blocked_user_ids, charge_ai_usage, notify, profile_for

User = get_user_model()
EXPIRE_DAYS = 7
MAX_PENDING = 5
EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif",
       "image/heic": "heic", "image/heif": "heif"}

ASK_NOTE = ("Ask a member to approve a reading of a photo of them. Nothing is scored unless they say yes; they see "
            "the photo first, the result goes to both of you, and they can take it down. The photo is deleted as soon "
            "as they decide, or after {days} days. You pay only if it's read.")
APPROVE_NOTE = ("Approving reads this photo of you in LookZMaxZ — hair, skin, teeth and styling — and shows the result "
                "to you and @{who}. You can take it down any time. Declining deletes the photo; @{who} is only told "
                "it wasn't approved.")


def _adult(user):
    return bool(user and profile_for(user).verified_18plus)


def _drop_photo(req, status_, note=""):
    if req.photo:
        req.photo.delete(save=False)
    req.photo = ""
    req.status = status_
    req.note = note[:300]
    req.decided_at = timezone.now()
    req.save(update_fields=["photo", "status", "note", "decided_at"])


def expire_old(user):
    """Pending requests past EXPIRE_DAYS that touch `user` lose their photo. Run on every read."""
    cutoff = timezone.now() - timedelta(days=EXPIRE_DAYS)
    for req in LookRequest.objects.filter(Q(requester=user) | Q(subject=user), status="pending", created_at__lt=cutoff):
        _drop_photo(req, "expired")


def _row(req, viewer):
    out = {"id": req.id, "status": req.status, "requester": req.requester.username, "subject": req.subject.username,
           "created_at": req.created_at.isoformat(),
           "expires_at": (req.created_at + timedelta(days=EXPIRE_DAYS)).isoformat(),
           "share_token": req.share.token if req.share_id else None}
    if req.status == "failed":
        out["note"] = req.note
    if viewer.id == req.subject_id and req.status == "pending":
        out["approve_note"] = APPROVE_NOTE.format(who=req.requester.username)
    return out


class LookAskView(APIView):
    """GET the requests you sent and received; POST {to, photo | photo_url} to ask."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        price = presentation_price(request.user)
        if not price["verified"]:
            return Response({"sent": [], "received": [], "note": ASK_NOTE.format(days=EXPIRE_DAYS)})
        expire_old(request.user)
        sent = LookRequest.objects.filter(requester=request.user).select_related("requester", "subject", "share")[:20]
        got = LookRequest.objects.filter(subject=request.user).select_related("requester", "subject", "share")[:20]
        return Response({"sent": [_row(r, request.user) for r in sent],
                         "received": [_row(r, request.user) for r in got],
                         "note": ASK_NOTE.format(days=EXPIRE_DAYS), "cost_cents": price["cost_cents"],
                         "affordable": price["affordable"], "max_pending": MAX_PENDING})

    def post(self, request):
        price = presentation_price(request.user)
        if not price["verified"]:
            return Response({"detail": "Asking for a reading is for verified adults."}, status=status.HTTP_403_FORBIDDEN)
        handle = str(request.data.get("to") or "").strip().lstrip("@")
        to = User.objects.filter(username__iexact=handle).first() if handle else None
        if not to:
            return Response({"detail": "Name the member in the photo — they're the one who approves it."},
                            status=status.HTTP_400_BAD_REQUEST)
        if to.id == request.user.id:
            return Response({"detail": "For a photo of you, use Read my photo above."}, status=status.HTTP_400_BAD_REQUEST)
        if to.id in blocked_user_ids(request.user):
            return Response({"detail": "You can't send that request."}, status=status.HTTP_403_FORBIDDEN)
        if not _adult(to):
            return Response({"detail": f"@{to.username} hasn't verified they're an adult, so they can't approve a "
                                       "reading. Send them your invite link instead."}, status=status.HTTP_400_BAD_REQUEST)
        if not price["affordable"]:
            return Response({"detail": f"A reading costs {price['cost_cents']} 🏷️ and today's free prompts are spent — "
                                       "you pay when it's read, so you need it now."}, status=status.HTTP_402_PAYMENT_REQUIRED)
        expire_old(request.user)
        pending = LookRequest.objects.filter(requester=request.user, status="pending")
        if pending.filter(subject=to).exists():
            return Response({"detail": f"You already have a request waiting with @{to.username}."},
                            status=status.HTTP_400_BAD_REQUEST)
        if pending.count() >= MAX_PENDING:
            return Response({"detail": f"You have {MAX_PENDING} requests waiting — wait for an answer or cancel one."},
                            status=status.HTTP_400_BAD_REQUEST)
        _, state = lookshare_state(request.user)
        photo, ctype, refused = _photo(request, state)
        if refused:
            return refused
        ctype = (ctype or "").split(";")[0].strip().lower()
        if not ctype.startswith("image/"):
            return Response({"detail": "That isn't a photo."}, status=status.HTTP_400_BAD_REQUEST)
        req = LookRequest(requester=request.user, subject=to, content_type=ctype)
        req.photo.save(f"ask.{EXT.get(ctype, 'jpg')}", ContentFile(photo.read()), save=False)
        req.save()
        notify(to, "system", f"@{request.user.username} asked you to approve a LookZMaxZ reading of a photo of you.",
               actor=request.user, item_id=f"lookask:{req.id}")
        return Response(_row(req, request.user), status=status.HTTP_201_CREATED)


def lookshare_state(user):
    from .lookmaxz_view import _state
    return _state(user)


class LookAskOneView(APIView):
    """GET the photo (requester or subject, while pending); POST {decision} as the subject; DELETE to cancel."""
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def _get(self, request, pk):
        req = LookRequest.objects.select_related("requester", "subject").filter(pk=pk).first()
        if not req or request.user.id not in (req.requester_id, req.subject_id):
            return None
        expire_old(request.user)
        req.refresh_from_db()
        return req

    def get(self, request, pk):
        req = self._get(request, pk)
        if not req or req.status != "pending" or not req.photo:
            return Response({"detail": "That request isn't waiting any more."}, status=status.HTTP_404_NOT_FOUND)
        with req.photo.open("rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        return Response({"id": req.id, "data_url": f"data:{req.content_type};base64,{data}"})

    def delete(self, request, pk):
        req = self._get(request, pk)
        if not req or req.requester_id != request.user.id or req.status != "pending":
            return Response({"detail": "Only a waiting request you sent can be cancelled."}, status=status.HTTP_404_NOT_FOUND)
        _drop_photo(req, "cancelled")
        return Response(status=status.HTTP_204_NO_CONTENT)

    def post(self, request, pk):
        req = self._get(request, pk)
        if not req or req.subject_id != request.user.id or req.status != "pending":
            return Response({"detail": "Only the person in the photo can answer, and only while it's waiting."},
                            status=status.HTTP_404_NOT_FOUND)
        decision = str(request.data.get("decision") or "").lower()
        if decision == "decline":
            _drop_photo(req, "declined")
            return Response(_row(req, request.user))
        if decision != "approve":
            return Response({"detail": "Approve or decline."}, status=status.HTTP_400_BAD_REQUEST)
        if str(request.data.get("confirm_self", "")).lower() not in ("true", "1", "yes"):
            return Response({"detail": "Confirm it's a photo of you and that you want it read."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not _adult(req.subject) or not _adult(req.requester):
            _drop_photo(req, "failed", "One of you is no longer verified as an adult, so it wasn't read.")
            return Response({**_row(req, request.user), "detail": req.note}, status=status.HTTP_403_FORBIDDEN)
        if req.requester_id in blocked_user_ids(request.user):
            _drop_photo(req, "declined")
            return Response(_row(req, request.user))
        price = presentation_price(req.requester)
        if not price["affordable"]:
            # Kept waiting: the requester can top up, and she can approve again.
            return Response({"detail": f"@{req.requester.username} can't cover the reading right now. It's still "
                                       "waiting — nothing was read."}, status=status.HTTP_402_PAYMENT_REQUIRED)
        with req.photo.open("rb") as f:
            payload, why = lm.rate_looks(f, req.content_type, list(lm.DEFAULT_SECTORS))
        if payload is None:
            return Response({"detail": f"Couldn't read it right now — {why}. It's still waiting; nothing was charged."},
                            status=status.HTTP_502_BAD_GATEWAY)
        if payload["unreadable"]:
            _drop_photo(req, "failed", f"The photo couldn't be read: {payload['unreadable']} Nothing was charged.")
            notify(req.requester, "system", f"Your LookZMaxZ request to @{req.subject.username} couldn't be read. "
                   "Nothing was charged.", actor=req.subject, item_id=f"lookask:{req.id}")
            return Response(_row(req, request.user))
        charge_ai_usage(req.requester, price["cost_cents"], note=f"LookZMaxZ reading approved by @{req.subject.username}",
                        count_daily=True)
        share = LookShare.objects.create(token=lookshare.new_token(), user=req.subject, to_user=req.requester,
                                         payload=lookshare.snapshot(payload))
        req.share = share
        req.save(update_fields=["share"])
        _drop_photo(req, "approved")
        notify(req.requester, "system", f"@{req.subject.username} approved your LookZMaxZ request — the reading is "
               "in LookZMaxZ under Shared with you.", actor=req.subject, item_id=f"lookshare:{share.token}")
        return Response({**_row(req, request.user), "share": lookshare.view_of(share, request.user)})
