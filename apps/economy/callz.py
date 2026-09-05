"""CallZ — a paid 1:1 call, and the rate you see before it connects.

CallZ has been sold at StatZ and listed in `CLAUDE.md` as an open cost/gain
violation since that file was written, for the same reason: LessonZ's "CallZ"
was a delivery method on a booking, priced identically to remote or in-person.
There was no per-minute rate to state before a call because there was no call.

The rule this file exists to satisfy is one sentence long:

    the other member's rate has to be visible before it connects

so `GET callz/rate/<username>/` answers the whole question before anything
rings — their rate, your balance, and how many minutes you can afford — and
`ring` snapshots that rate onto the row so it cannot move under the caller
while they are talking.

WHO MAY CALL, AND WHO MAY BE CALLED, ARE DIFFERENT QUESTIONS.
Placing a call is the StatZ perk, as sold. RECEIVING one is not gated at all,
and that asymmetry is deliberate: gating both sides would mean, on a platform
with one StatZ member, that nobody can ever call anybody — the feature would
ship sold, built and unusable, which is the exact failure this whole run of
work has been unpicking. And the receiving side is the side that gets PAID.
Charging somebody a subscription for the privilege of being hired is backwards.

THE TRANSPORT IS PEER-TO-PEER AND THE SIGNALLING IS POLLED.
There is no ASGI server and no channels layer here — `render.yaml` runs
gunicorn — so there are no WebSockets to signal over. Both sides poll the call
row for the other's SDP and ICE. It costs a few seconds at connect and nothing
after that, because the media never touches this server. A STUN server is
enough for most networks; calls between two symmetric NATs need a TURN relay,
which is a paid service and is not configured, so `stun_only` says so out loud
rather than letting those calls fail as a mystery.
"""
import math

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.contrib.auth import get_user_model

from .models import (Call, TIER_STATZ, blocked_user_ids, membership_for,
                     pay_between, profile_for, wallet_for)
from .social import profile_skill_rate

User = get_user_model()

# A call nobody has polled for this long is over, whatever the row says. A
# browser that closes mid-call cannot end its own call, and escrow held forever
# because of that is money taken for a service that stopped.
CALL_STALE_SECONDS = 90

# The ceiling on one call's escrow. Not a limit on how long anyone may talk —
# the call rolls on and re-holds — it is a bound on how much of a member's
# balance a single answer can lock up.
MAX_ESCROW_MINUTES = 60

# What a member charges when they have priced no skills. Zero, and zero means
# free: a call with a member who has never named a price should connect, not
# refuse. It is their rate that makes it cost, and they have not set one.
DEFAULT_RATE_CENTS_PER_MIN = 0

# Public STUN. Free, no account, and it is all that is needed unless both ends
# are behind symmetric NAT.
ICE_SERVERS = [{"urls": ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"]}]


def rate_per_min_cents(user):
    """What one minute with this member costs, in cents.

    Derived from their cheapest priced skill per hour — `profile_skill_rate`
    already picks `min` on purpose, because a price gate asks "can I afford
    this person" and the honest answer is their cheapest skill, not their
    dearest. Rounded UP to the cent so a rate can never round to nothing.
    """
    per_hour = profile_skill_rate(profile_for(user))
    if not per_hour:
        return DEFAULT_RATE_CENTS_PER_MIN
    return max(1, math.ceil(per_hour / 60))


def cost_for_seconds(rate_per_min, seconds):
    """Prorated by the second, rounded up to the cent.

    Per-second rather than per-started-minute so a 20-second call costs 20
    seconds. Rounding up means the platform never owes a fraction it cannot
    pay, and the most it can ever cost somebody is one cent.
    """
    if rate_per_min <= 0 or seconds <= 0:
        return 0
    return math.ceil(rate_per_min * seconds / 60)


def _settle(call, reason=""):
    """End a live call, bill the seconds it ran, return the rest of the escrow.

    Idempotent: a call that is already ended settles to itself, so a caller and
    a callee both pressing End cannot bill twice.
    """
    if call.status not in (Call.STATUS_RINGING, Call.STATUS_LIVE):
        return call
    now = timezone.now()
    if call.status == Call.STATUS_RINGING:
        # Never answered. Nothing was ever held, so there is nothing to return.
        call.status = Call.STATUS_MISSED
        call.ended_at = now
        call.end_reason = reason or "not answered"
        call.save(update_fields=["status", "ended_at", "end_reason"])
        return call

    seconds = int((now - (call.started_at or now)).total_seconds())
    charged = min(call.held_cents, cost_for_seconds(call.rate_cents_per_min, seconds))
    refund = call.held_cents - charged

    with transaction.atomic():
        w = wallet_for(call.caller)
        if refund:
            # Back to the caller first. Escrow is their money until it is spent.
            w.money_cents += refund
            w.save(update_fields=["money_cents", "updated_at"])
        if charged:
            # Put it back before paying it out, so `pay_between` moves real
            # balance and both ledgers read the way every other payment does.
            w.refresh_from_db()
            w.money_cents += charged
            w.save(update_fields=["money_cents", "updated_at"])
            pay_between(call.caller, call.callee, charged,
                        f"CallZ · {seconds // 60}m {seconds % 60}s with {call.callee.username}")
        call.status = Call.STATUS_ENDED
        call.ended_at = now
        call.billed_seconds = seconds
        call.charged_cents = charged
        call.held_cents = 0
        call.end_reason = reason or "ended"
        call.save(update_fields=["status", "ended_at", "billed_seconds",
                                 "charged_cents", "held_cents", "end_reason"])
    return call


def sweep_stale(user):
    """Settle this member's calls that nothing has touched recently.

    Runs on read, like `settle_energy`. There is no cron here, and a call left
    `live` because a tab closed is money held for a service that stopped.
    """
    cutoff = timezone.now() - timezone.timedelta(seconds=CALL_STALE_SECONDS)
    stale = Call.objects.filter(status__in=(Call.STATUS_RINGING, Call.STATUS_LIVE)).filter(
        models_q_for(user)).filter(last_seen_at__lt=cutoff)
    for call in stale:
        _settle(call, reason="connection lost")


def models_q_for(user):
    from django.db.models import Q
    return Q(caller=user) | Q(callee=user)


def call_dict(call, me):
    """One call, from the point of view of whoever is looking at it."""
    mine = call.caller_id == me.id
    other = call.callee if mine else call.caller
    running = 0
    if call.status == Call.STATUS_LIVE and call.started_at:
        running = int((timezone.now() - call.started_at).total_seconds())
    return {
        "id": call.id,
        "status": call.status,
        "direction": "outgoing" if mine else "incoming",
        "other": other.username,
        "rate_cents_per_min": call.rate_cents_per_min,
        # What it has cost SO FAR, recomputed live — the running total belongs
        # on screen during the call, not only on the receipt.
        "elapsed_seconds": running or call.billed_seconds,
        "cost_cents": (cost_for_seconds(call.rate_cents_per_min, running)
                       if call.status == Call.STATUS_LIVE else call.charged_cents),
        "held_cents": call.held_cents,
        "charged_cents": call.charged_cents,
        "end_reason": call.end_reason,
        # The handshake. Each side reads the other's half.
        "offer_sdp": call.offer_sdp if not mine else "",
        "answer_sdp": call.answer_sdp if mine else "",
        "remote_ice": call.callee_ice if mine else call.caller_ice,
        "created_at": call.created_at,
        "started_at": call.started_at,
    }


class CallRateView(APIView):
    """GET callz/rate/<username>/ — what calling this member costs, before it rings.

    The whole cost/gain rule for this feature lives in this response.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, username):
        other = User.objects.filter(username__iexact=username).first()
        if not other or other.id == request.user.id:
            return Response({"detail": "No member by that name."},
                            status=status.HTTP_404_NOT_FOUND)
        if other.id in blocked_user_ids(request.user):
            return Response({"detail": "You can't call this member."},
                            status=status.HTTP_403_FORBIDDEN)
        rate = rate_per_min_cents(other)
        w = wallet_for(request.user)
        tier = membership_for(request.user).tier
        affordable_minutes = (w.money_cents // rate) if rate else None
        return Response({
            "username": other.username,
            "rate_cents_per_min": rate,
            "free": rate == 0,
            "your_money_cents": w.money_cents,
            # None means "as long as you like" — they have not priced a skill.
            "affordable_minutes": affordable_minutes,
            "max_escrow_minutes": MAX_ESCROW_MINUTES,
            "can_call": tier == TIER_STATZ,
            "tier": tier,
            "tier_required": TIER_STATZ,
            # Receiving is never gated; only placing is. Said here so the tab
            # can explain the asymmetry rather than implying both sides pay.
            "receiving_is_free_at_every_tier": True,
            "ice_servers": ICE_SERVERS,
            "stun_only": True,
        })


class CallsView(APIView):
    """GET callz/ — anything ringing for me, and my live call. POST rings one."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        sweep_stale(request.user)
        active = Call.objects.filter(models_q_for(request.user),
                                     status__in=(Call.STATUS_RINGING, Call.STATUS_LIVE))
        # Touching the row IS the heartbeat, so polling keeps the call alive
        # and not polling is what ends it.
        now = timezone.now()
        for c in active:
            if c.caller_id == request.user.id or c.status == Call.STATUS_LIVE:
                Call.objects.filter(pk=c.pk).update(last_seen_at=now)
        recent = Call.objects.filter(models_q_for(request.user)).exclude(
            status__in=(Call.STATUS_RINGING, Call.STATUS_LIVE))[:20]
        return Response({
            "active": [call_dict(c, request.user) for c in active],
            "recent": [call_dict(c, request.user) for c in recent],
            "ice_servers": ICE_SERVERS,
        })

    def post(self, request):
        if membership_for(request.user).tier != TIER_STATZ:
            return Response(
                {"detail": "Placing a call is a StatZ perk. Receiving one is free at every tier.",
                 "tier_required": TIER_STATZ},
                status=status.HTTP_403_FORBIDDEN)
        d = request.data or {}
        other = User.objects.filter(username__iexact=str(d.get("username", ""))).first()
        if not other or other.id == request.user.id:
            return Response({"detail": "No member by that name."},
                            status=status.HTTP_404_NOT_FOUND)
        if other.id in blocked_user_ids(request.user):
            return Response({"detail": "You can't call this member."},
                            status=status.HTTP_403_FORBIDDEN)
        if Call.objects.filter(models_q_for(request.user),
                               status__in=(Call.STATUS_RINGING, Call.STATUS_LIVE)).exists():
            return Response({"detail": "You're already on a call."},
                            status=status.HTTP_409_CONFLICT)
        if Call.objects.filter(callee=other, status=Call.STATUS_LIVE).exists():
            return Response({"detail": f"{other.username} is on another call."},
                            status=status.HTTP_409_CONFLICT)
        rate = rate_per_min_cents(other)
        w = wallet_for(request.user)
        # Refuse before it rings rather than after they pick up. Being cut off
        # mid-sentence for money is worse than being told the price first.
        if rate and w.money_cents < rate:
            return Response(
                {"detail": f"A minute with {other.username} is {rate}¢ and your balance is {w.money_cents}¢.",
                 "rate_cents_per_min": rate, "your_money_cents": w.money_cents},
                status=status.HTTP_402_PAYMENT_REQUIRED)
        call = Call.objects.create(
            caller=request.user, callee=other, status=Call.STATUS_RINGING,
            # Snapshotted here. Their rate cannot move under a call in progress.
            rate_cents_per_min=rate,
            offer_sdp=str(d.get("offer_sdp", ""))[:200000],
            last_seen_at=timezone.now(),
        )
        return Response(call_dict(call, request.user), status=status.HTTP_201_CREATED)


class CallDetailView(APIView):
    """One call: poll it, answer it, decline it, add ICE, end it."""

    permission_classes = [IsAuthenticated]

    def _get(self, request, pk):
        return Call.objects.filter(models_q_for(request.user), pk=pk).first()

    def get(self, request, pk):
        call = self._get(request, pk)
        if not call:
            return Response({"detail": "No such call."}, status=status.HTTP_404_NOT_FOUND)
        if call.status in (Call.STATUS_RINGING, Call.STATUS_LIVE):
            Call.objects.filter(pk=call.pk).update(last_seen_at=timezone.now())
            call.refresh_from_db()
        return Response(call_dict(call, request.user))

    def post(self, request, pk, action=None):
        call = self._get(request, pk)
        if not call:
            return Response({"detail": "No such call."}, status=status.HTTP_404_NOT_FOUND)
        d = request.data or {}

        if action == "ice":
            # Whichever side you are, your candidates go in your own bucket.
            field = "caller_ice" if call.caller_id == request.user.id else "callee_ice"
            existing = list(getattr(call, field) or [])
            for c in (d.get("candidates") or [])[:60]:
                if isinstance(c, dict) and len(existing) < 200:
                    existing.append(c)
            setattr(call, field, existing)
            call.last_seen_at = timezone.now()
            call.save(update_fields=[field, "last_seen_at"])
            return Response(call_dict(call, request.user))

        if action == "answer":
            if call.callee_id != request.user.id:
                return Response({"detail": "Only the person being called can answer."},
                                status=status.HTTP_403_FORBIDDEN)
            if call.status != Call.STATUS_RINGING:
                return Response({"detail": f"That call is {call.status}."},
                                status=status.HTTP_409_CONFLICT)
            # Escrow is taken HERE and not at ring: nobody pays for a call that
            # was never picked up.
            held = 0
            if call.rate_cents_per_min:
                w = wallet_for(call.caller)
                held = min(w.money_cents, call.rate_cents_per_min * MAX_ESCROW_MINUTES)
                if held < call.rate_cents_per_min:
                    _settle(call, reason="caller can't cover a minute")
                    return Response({"detail": "The caller can't cover a minute any more."},
                                    status=status.HTTP_402_PAYMENT_REQUIRED)
                w.money_cents -= held
                w.save(update_fields=["money_cents", "updated_at"])
            call.status = Call.STATUS_LIVE
            call.started_at = timezone.now()
            call.last_seen_at = call.started_at
            call.held_cents = held
            call.answer_sdp = str(d.get("answer_sdp", ""))[:200000]
            call.save(update_fields=["status", "started_at", "last_seen_at",
                                     "held_cents", "answer_sdp"])
            return Response(call_dict(call, request.user))

        if action == "decline":
            if call.callee_id != request.user.id:
                return Response({"detail": "Only the person being called can decline."},
                                status=status.HTTP_403_FORBIDDEN)
            call.status = Call.STATUS_DECLINED
            call.ended_at = timezone.now()
            call.end_reason = "declined"
            call.save(update_fields=["status", "ended_at", "end_reason"])
            return Response(call_dict(call, request.user))

        if action == "end":
            call = _settle(call, reason=f"ended by {request.user.username}")
            return Response(call_dict(call, request.user))

        return Response({"detail": "Unknown action."}, status=status.HTTP_400_BAD_REQUEST)
