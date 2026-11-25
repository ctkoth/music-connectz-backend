"""Steps from the member's phone and watch, read through Android's Health Connect and sent here by the Android app.

A web page (and a Trusted Web Activity, which is Chrome) cannot read a watch or Health Connect, so the Android app
carries a small native screen that does. The server's side is four things and nothing else:

* **Pair**: the signed-in member asks for a short code (`pair`), valid ten minutes, single use.
* **Link**: the phone app exchanges the code for a long token (`link`). Only its hash is kept.
* **Steps**: the phone sends whole days (`steps`), authenticated by that token, never by the member's login.
* **Read / unlink**: the member sees their own days and can unlink, which deletes every one of them (`state`).

What it deliberately does NOT do — the substance rule's whole point: steps are reported by a device the server cannot
check, so they **pay nothing and move no rating, level, badge, XP or leaderboard**. A step total that earned anything
would be the first thing someone shakes a phone to farm. They are shown to the member who owns them and to nobody
else (`test_healthsync` fails if another module reads `StepDay`). Weight on a bar is not here either: no watch can
sense it, so it stays what the member logs.
"""
import hashlib
import secrets
from datetime import date, timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import ratelimit

from .clientip import client_ip
from .models import HealthLink, StepDay

CODE_MINUTES = 10
CODE_LEN = 8
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L: it is read off one screen and typed on another
MAX_DAYS_PER_SYNC = 14
MAX_STEPS_PER_DAY = 200_000  # beyond what a person can walk; a bigger number is a bug or a lie, not a record
SHOW_DAYS = 14
SOURCE_NOTE = ("Steps come from Health Connect on your phone, which combines your phone and any watch that writes to it. "
               "They are your device's count, not checked by us, so they pay nothing and change no rating.")
TOKEN_HEADER = "HTTP_X_HEALTH_TOKEN"
LINK_FAIL_KIND = "healthlink"


def _h(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def new_code():
    return "".join(secrets.choice(_ALPHABET) for _ in range(CODE_LEN))


def clean_days(raw, today=None):
    """[{day, steps}] -> [(date, int)] for the days that are real. Junk rows are dropped, never guessed at or clamped
    into a plausible number: a made-up step count is the substance rule's failure case."""
    today = today or timezone.localdate()
    out = {}
    for row in (raw if isinstance(raw, list) else [])[:MAX_DAYS_PER_SYNC * 2]:
        if not isinstance(row, dict):
            continue
        try:
            d = date.fromisoformat(str(row.get("day"))[:10])
            n = int(row.get("steps"))
        except (TypeError, ValueError):
            continue
        if n < 0 or n > MAX_STEPS_PER_DAY or d > today + timedelta(days=1) or d < today - timedelta(days=MAX_DAYS_PER_SYNC):
            continue
        out[d] = n  # a later row for the same day wins
    return sorted(out.items())[-MAX_DAYS_PER_SYNC:]


def state_for(user):
    link = HealthLink.objects.filter(user=user).first()
    linked = bool(link and link.token_hash)
    days = list(StepDay.objects.filter(user=user).order_by("-day")[:SHOW_DAYS]) if linked else []
    return {
        "linked": linked,
        "last_sync_at": link.last_sync_at.isoformat() if linked and link.last_sync_at else None,
        "days": [{"day": d.day.isoformat(), "steps": d.steps} for d in days],
        "note": SOURCE_NOTE,
        "needs": "The Android app. A website cannot read Health Connect, so linking happens in the app.",
        "code_minutes": CODE_MINUTES,
        "pays": False,
    }


class HealthStateView(APIView):
    def get(self, request):
        return Response(state_for(request.user))

    def delete(self, request):
        """Unlink and delete every day. The phone's token stops working at once; the data is gone, not hidden."""
        StepDay.objects.filter(user=request.user).delete()
        HealthLink.objects.filter(user=request.user).delete()
        return Response(state_for(request.user))


class HealthPairView(APIView):
    def post(self, request):
        code = new_code()
        link, _ = HealthLink.objects.get_or_create(user=request.user)
        link.code_hash = _h(code)
        link.code_expires = timezone.now() + timedelta(minutes=CODE_MINUTES)
        link.save(update_fields=["code_hash", "code_expires"])
        return Response({"code": code, "minutes": CODE_MINUTES,
                         "how": "Open the Android app, choose Link steps, and type this code."})


class HealthLinkView(APIView):
    """The phone swaps a pairing code for its token. Open to the logged out because the phone has no login; the code
    is the proof, and wrong guesses are counted per connection so the code cannot be walked."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        ip = client_ip(request)
        if ratelimit.failures(LINK_FAIL_KIND, ip) >= ratelimit.PER_IDENTIFIER:
            return Response({"detail": "Too many wrong codes. Wait a few minutes and ask for a new one."},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)
        code = str(request.data.get("code") or "").strip().upper().replace(" ", "").replace("-", "")
        link = HealthLink.objects.filter(code_hash=_h(code), code_expires__gt=timezone.now()).first() if code else None
        if not link:
            ratelimit.note_failure(LINK_FAIL_KIND, ip)
            return Response({"detail": "That code is wrong or has run out. Ask for a new one in BodieZ."},
                            status=status.HTTP_400_BAD_REQUEST)
        token = secrets.token_urlsafe(32)
        link.token_hash, link.linked_at = _h(token), timezone.now()
        link.code_hash, link.code_expires = "", None
        link.save(update_fields=["token_hash", "linked_at", "code_hash", "code_expires"])
        return Response({"token": token})


class HealthStepsView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        token = request.META.get(TOKEN_HEADER, "")
        link = HealthLink.objects.filter(token_hash=_h(token)).first() if token else None
        if not link:
            return Response({"detail": "This phone is not linked. Link it again from BodieZ."},
                            status=status.HTTP_401_UNAUTHORIZED)
        days = clean_days(request.data.get("days"))
        for d, n in days:
            StepDay.objects.update_or_create(user_id=link.user_id, day=d, defaults={"steps": n})
        link.last_sync_at = timezone.now()
        link.save(update_fields=["last_sync_at"])
        return Response({"saved": len(days)})
