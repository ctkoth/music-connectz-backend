"""Keep a live BodieZ session on screen while other apps are open.

A workout is the one thing a member does with other apps in the way: the metronome, a chord chart, a playlist, a
message from the person they are training with. Leaving BodieZ used to leave the session behind — its rest clock was
a screen they could no longer see, and a rest that ends in another app ends unseen.

The session itself has always lived on the server (an open `BodieZSession`), and the shell can keep an app mounted
while another is in front (`recordingHold.js` on the client). This module is the number that goes with the
choice, and nothing else:

* **A tier says how OFTEN, never whether.** Free 3, Premium 6, StatZ 12 sessions a rolling 24 hours
  (`catalog.TIER_LIMITS["bodiez_float"]`, Corey's numbers). The session, its rest clock and its beep run in BodieZ at
  every tier; what a tier buys is how many sessions a day are kept running on screen over other apps. Past the number
  the session is untouched — the member reopens BodieZ and it is exactly where they left it.
* **A session counts once.** Pressing it again on the same session is free (`already`), so a member who turns the bar
  off and on is not charged twice. The count is rows with `floated_at` set, not a counter — nothing to drift, and the
  window is rolling because a calendar day would hand a New York member a fresh allowance at 7pm UTC.
* **Stated before the press.** `state()` serves used / left / the next tier's number, so the control can say
  "2 of 3 left today" BEFORE it is pressed (the cost/gain rule: a limit is a price). It costs no ⚡, 🍥 or 🏷️.
* **Refusing writes nothing.** A refused press leaves `floated_at` null and charges nothing.
* **Only a live session.** Finished sessions, backfilled ones and other members' sessions are not eligible.
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import limits_for
from .models import BodieZSession, membership_for

WINDOW_HOURS = 24
TIERS = ("free", "premium", "statz")


def cap_for(user):
    """This member's number: an int, or None for unlimited."""
    return limits_for(membership_for(user).tier).get("bodiez_float")


def used_since(user, now=None):
    now = now or timezone.now()
    return BodieZSession.objects.filter(
        user=user, floated_at__gte=now - timedelta(hours=WINDOW_HOURS)).count()


def _next_number(user):
    """What the NEXT plan up allows (None = unlimited), or False when the member is already on the top one."""
    tier = membership_for(user).tier
    if tier == "free":
        return limits_for("premium").get("bodiez_float")
    if tier == "premium":
        return limits_for("statz").get("bodiez_float")
    return False


def state(user, session=None):
    """The whole price of the control, for the screen to read before anything is pressed."""
    cap = cap_for(user)
    used = used_since(user)
    already = bool(session is not None and session.floated_at)
    left = None if cap is None else max(0, cap - used)
    nxt = _next_number(user)
    return {
        "limit": cap,                      # None = unlimited
        "used": used,
        "left": left,
        "unlimited": cap is None,
        "window_hours": WINDOW_HOURS,
        "already": already,                # this session is already on screen: pressing it again is free
        "can": already or cap is None or used < cap,
        "next_limit": nxt,                 # False on the top plan; None = unlimited
        # The live session this is about (None when nothing is open), so the shell can bring a kept session back
        # after a reload without loading BodieZ to find out.
        "session": ({"id": session.id, "floated": bool(session.floated_at)} if session is not None else None),
        "ladder": {t: limits_for(t).get("bodiez_float") for t in TIERS},
        "cost": "Free — no ⚡, 🍥 or 🏷️. It uses one of today's sessions on screen.",
        "note": ("The session, its rest clock and its beep keep running in BodieZ whatever this number is; "
                 "it only decides how many sessions a day stay on screen over other apps. "
                 "Turning it off and on again for the same session is not counted twice."),
    }


def _open_session(user):
    return BodieZSession.objects.filter(user=user, ended_at__isnull=True, backfilled=False).first()


class BodieZFloatStateView(APIView):
    """GET /api/economy/bodiez/float/ — the number, before the press. Includes the open session's own state."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(state(request.user, _open_session(request.user)))


class BodieZSessionFloatView(APIView):
    """POST /api/economy/bodiez/sessions/<id>/float/ — keep this live session on screen over other apps."""
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        sess = BodieZSession.objects.filter(id=session_id, user=request.user).first()
        if sess is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        if sess.ended_at or sess.backfilled:
            return Response({"detail": "Only a session you are logging right now can stay on screen."},
                            status=status.HTTP_409_CONFLICT)
        if not sess.floated_at:
            st = state(request.user, sess)
            if not st["can"]:
                nxt = st["next_limit"]
                more = ("" if nxt is False else
                        f" The next plan up keeps {'any number' if nxt is None else nxt} on screen a day.")
                return Response(
                    {"detail": f"You've kept {st['used']} of {st['limit']} sessions on screen in the last "
                               f"{WINDOW_HOURS} hours — your plan's number. Your session is untouched; open BodieZ to see "
                               f"it.{more} Nothing was charged.",
                     "float": st},
                    status=status.HTTP_403_FORBIDDEN)
            # Conditional, so two presses at once set it once and the second sees `already`.
            BodieZSession.objects.filter(id=sess.id, floated_at__isnull=True).update(floated_at=timezone.now())
            sess.refresh_from_db(fields=["floated_at"])
        return Response({"floated_at": sess.floated_at.isoformat(), "float": state(request.user, sess)})
