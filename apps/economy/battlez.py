"""BattleZ — a challenge, its entries, and the same door everything else has.

BattleZ has been in the tab bar since the app was written and has never had a
single row behind it, which made "BattleZ carries the range gates" a promise
with nothing to enforce. This is the smallest honest version:

* the challenge carries the WORK in the PostZ format — record or upload
  audio/video, an image, and the lyrics or script;
* entering carries the same;
* who may enter is decided by the same five exclusive ranges search, VenueZ and
  CollabZ use, from one spec, so what a host advertises and what the door
  enforces cannot diverge;
* judging is not reimplemented — a battle and every entry live in the item space
  RateZ already serves, so they get ratings and a comment thread for free.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import over_char_limit
from .gates import clean_gates, describe, failing_gate, member_metrics, refusal
from .models import (
    BATTLE_MIN_RATINGS,
    BATTLE_WINDOW_HOURS,
    Battle,
    BattleEntry,
    BattleWager,
    MoneyBattleVote,
    award_spinaz,
    blocked_user_ids,
    clean_link,
    item_rating_median,
    membership_for,
    notify,
    profile_for,
    wallet_for,
)

User = get_user_model()


def _media(d, prefix=""):
    return {
        "media_type": str(d.get(f"{prefix}media_type", "") or "")[:24],
        "media_url": str(d.get(f"{prefix}media_url", "") or "")[:500],
        "image_url": str(d.get(f"{prefix}image_url", "") or "")[:500],
        "lyrics": str(d.get(f"{prefix}lyrics", "") or ""),
    }


def entry_dict(e, request=None):
    user = getattr(request, "user", None)
    return {
        "id": e.id,
        "user": e.user.username,
        "mine": bool(user and getattr(user, "is_authenticated", False) and e.user_id == user.id),
        "title": e.title,
        "media_type": e.media_type,
        "media_url": e.media_url,
        "image_url": e.image_url,
        "lyrics": e.lyrics,
        "link": e.link or {},
        # Judged through the shared item space, not a second rating system.
        "item_key": e.item_key,
        "rating": item_rating_median(e.item_key),
        "created_at": e.created_at.isoformat(),
    }


def battle_dict(b, request=None, with_entries=True):
    user = getattr(request, "user", None)
    me = bool(user and getattr(user, "is_authenticated", False))
    out = {
        "id": b.id,
        "host": b.host.username,
        "mine": bool(me and b.host_id == user.id),
        "title": b.title,
        "description": b.description,
        "genre": b.genre,
        "media_type": b.media_type,
        "media_url": b.media_url,
        "image_url": b.image_url,
        "lyrics": b.lyrics,
        "gates": b.gates or {},
        "entry_spinaz": b.entry_spinaz,
        "status": b.status,
        "item_key": b.item_key,
        "rating": item_rating_median(b.item_key),
        "entry_count": b.entries.count(),
        "mode": b.mode,
        "kind": b.kind,
        "opponent": b.opponent.username if b.opponent else "",
        "accepted_at": b.accepted_at.isoformat() if b.accepted_at else None,
        "ends_at": b.ends_at.isoformat() if b.ends_at else None,
        "winner": b.winner.username if b.winner else "",
        "settled_at": b.settled_at.isoformat() if b.settled_at else None,
        "min_ratings": BATTLE_MIN_RATINGS,
        "created_at": b.created_at.isoformat(),
    }
    if b.mode == Battle.MODE_1V1 and b.opponent_id:
        out["scoreboard"] = scoreboard(b)
        out["pools"] = pools(b)
        out["pool_total"] = sum(pools(b).values())
        if me:
            mine = b.wagers.filter(user=user).first()
            out["my_side"] = side_of(b, user)
            out["my_wager"] = ({"side": mine.side, "amount": mine.amount,
                                "paid_out": mine.paid_out} if mine else None)
            out["i_am_contestant"] = bool(out["my_side"])
    if me:
        out["entered"] = b.entries.filter(user=user).exists()
    if with_entries:
        entries = list(b.entries.select_related("user"))
        # Best-judged first — a battle with no leaderboard is just a thread.
        entries.sort(key=lambda e: (item_rating_median(e.item_key) or 0), reverse=True)
        out["entries"] = [entry_dict(e, request) for e in entries]
    return out


class BattlesView(APIView):
    """GET the open battles; POST hosts one."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (Battle.objects.select_related("host", "opponent")
              .exclude(host_id__in=blocked_user_ids(request.user))[:200])
        qs = [maybe_auto_settle(b) for b in qs]
        return Response({"battles": [battle_dict(b, request, with_entries=False) for b in qs]})

    def post(self, request):
        d = request.data or {}
        title = str(d.get("title", "")).strip()
        if not title:
            return Response({"detail": "Give the battle a name."},
                            status=status.HTTP_400_BAD_REQUEST)
        description = str(d.get("description", "") or "")
        cap = over_char_limit(description, membership_for(request.user).tier)
        if cap:
            return Response(
                {"detail": f"That's over your {cap:,}-character limit — upgrade in MembershipZ for more room.",
                 "char_limit": cap},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            entry_spinaz = max(0, int(d.get("entry_spinaz") or 0))
        except (TypeError, ValueError):
            entry_spinaz = 0
        b = Battle.objects.create(
            host=request.user, title=title[:160], description=description,
            genre=str(d.get("genre", "") or "")[:40],
            gates=clean_gates(d.get("gates")), entry_spinaz=entry_spinaz,
            **_media(d),
        )
        return Response(battle_dict(b, request), status=status.HTTP_201_CREATED)


class BattleDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        b = Battle.objects.select_related("host", "opponent").filter(pk=pk).first()
        if not b:
            return Response({"detail": "battle not found"}, status=status.HTTP_404_NOT_FOUND)
        # Settle on read: otherwise a finished battle's pool sits held forever
        # because nobody happened to press a button.
        return Response(battle_dict(maybe_auto_settle(b), request))

    def patch(self, request, pk):
        """The host closes it. Closing is the only edit — a challenge whose
        terms change after people have entered isn't a challenge."""
        b = Battle.objects.filter(pk=pk, host=request.user).first()
        if not b:
            return Response({"detail": "battle not found"}, status=status.HTTP_404_NOT_FOUND)
        if str((request.data or {}).get("status", "")).lower() == Battle.STATUS_CLOSED:
            b.status = Battle.STATUS_CLOSED
            b.save(update_fields=["status", "updated_at"])
        return Response(battle_dict(b, request))


class BattleEnterView(APIView):
    """POST enters the battle — gated, priced, and in the PostZ format."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        b = Battle.objects.select_related("host").filter(pk=pk).first()
        if not b:
            return Response({"detail": "battle not found"}, status=status.HTTP_404_NOT_FOUND)
        b = maybe_auto_settle(b)
        if b.status != Battle.STATUS_OPEN:
            return Response({"detail": f"This battle is {b.status}."},
                            status=status.HTTP_409_CONFLICT)

        # In a 1v1 the two contestants are the only entrants, and the host is
        # one of them — the open-challenge rule ("not your own battle") would
        # lock a challenger out of the battle they started.
        if b.mode == Battle.MODE_1V1 and b.opponent_id:
            if not side_of(b, request.user):
                return Response({"detail": "This is a 1v1 — only the two contestants put takes up."},
                                status=status.HTTP_403_FORBIDDEN)
        elif b.host_id == request.user.id:
            return Response({"detail": "You can't enter your own battle."},
                            status=status.HTTP_400_BAD_REQUEST)

        if b.entries.filter(user=request.user).exists():
            return Response({"detail": "You're already in this one."},
                            status=status.HTTP_409_CONFLICT)

        # The same five ranges, evaluated exactly as search evaluates them.
        # A contestant already passed them when they were challenged.
        if b.gates and not (b.mode == Battle.MODE_1V1 and b.opponent_id):
            host_p = profile_for(b.host)
            origin = ((host_p.lat, host_p.lng)
                      if (host_p.share_location and host_p.lat is not None) else (None, None))
            failed = failing_gate(member_metrics(profile_for(request.user), origin), b.gates)
            if failed:
                return Response(refusal(failed, b.gates), status=status.HTTP_403_FORBIDDEN)

        w = wallet_for(request.user)
        if b.mode == Battle.MODE_1V1 and b.opponent_id:
            b.entry_spinaz = 0      # a 1v1 has no gate fee; the wager is the stake
        if b.entry_spinaz and (w.spinaz or 0) < b.entry_spinaz:
            return Response(
                {"detail": f"Entry costs {b.entry_spinaz} SpinaZ and you have {w.spinaz or 0}.",
                 "entry_spinaz": b.entry_spinaz},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        d = request.data or {}
        entry = BattleEntry.objects.create(
            battle=b, user=request.user, title=str(d.get("title", "") or "")[:160],
            link=clean_link(d.get("link")), **_media(d),
        )
        if b.entry_spinaz:
            # Entry goes to the host. Stated on the button before it's pressed.
            award_spinaz(request.user, -b.entry_spinaz, f"BattleZ entry: {b.title}")
            award_spinaz(b.host, b.entry_spinaz, f"BattleZ entry from @{request.user.username}")
        notify(b.host, "join", f"@{request.user.username} entered '{b.title}' ⚔️",
               actor=request.user, item_id=b.item_key)
        return Response({"entry": entry_dict(entry, request),
                         "battle": battle_dict(b, request)},
                        status=status.HTTP_201_CREATED)

    def delete(self, request, pk):
        """Withdraw. The entry fee is NOT returned — it was paid to the host for
        their time the moment it was accepted, and refunding on withdrawal would
        make the fee meaningless."""
        b = Battle.objects.filter(pk=pk).first()
        if not b:
            return Response({"detail": "battle not found"}, status=status.HTTP_404_NOT_FOUND)
        b.entries.filter(user=request.user).delete()
        return Response(battle_dict(b, request))


# ---- 1v1: the scoreboard, the pool, and the settlement ----

def side_of(battle, user):
    if user and battle.host_id == user.id:
        return BattleWager.SIDE_HOST
    if user and battle.opponent_id and battle.opponent_id == user.id:
        return BattleWager.SIDE_OPPONENT
    return None


def scoreboard(battle):
    """Each contestant's median and how many people have judged them.

    A side with fewer than BATTLE_MIN_RATINGS judges does not qualify — one
    friend rating you a 10 is not a win, and paying a pool out on it would make
    the whole thing worthless.
    """
    out = {}
    for key, user in (("host", battle.host), ("opponent", battle.opponent)):
        if not user:
            out[key] = None
            continue
        entry = battle.entries.filter(user=user).first()
        if not entry:
            out[key] = {"username": user.username, "median": None, "count": 0,
                        "qualified": False, "submitted": False}
            continue
        from .models import ItemRating
        scores = list(ItemRating.objects.filter(item_id=entry.item_key)
                      .values_list("score", flat=True))
        median = item_rating_median(entry.item_key)
        out[key] = {
            "username": user.username,
            "median": median,
            "count": len(scores),
            "qualified": len(scores) >= BATTLE_MIN_RATINGS,
            "submitted": True,
            "entry_id": entry.id,
            "item_key": entry.item_key,
        }
    return out


def pools(battle):
    totals = {BattleWager.SIDE_HOST: 0, BattleWager.SIDE_OPPONENT: 0}
    for w in battle.wagers.all():
        totals[w.side] = totals.get(w.side, 0) + w.amount
    return totals


@transaction.atomic
def settle_battle(battle):
    """Decide the winner and pay the pool. Idempotent — guarded on status.

    Winners split the WHOLE pool in proportion to what they staked, so backing
    the right side pays more the more you risked. No house cut: SpinaZ carries
    no developer tax anywhere else in this app and a battle is not the place to
    invent one.

    If nobody qualifies, or it's a draw, every stake goes back. A pool that
    can't be decided is not the spectators' problem.
    """
    battle = Battle.objects.select_for_update().get(pk=battle.pk)
    if battle.status not in (Battle.STATUS_OPEN,):
        return battle

    board = scoreboard(battle)
    host, opp = board.get("host"), board.get("opponent")
    qualified = [s for s in (host, opp) if s and s["qualified"]]

    winner_side = None
    if len(qualified) == 2 and host["median"] != opp["median"]:
        winner_side = (BattleWager.SIDE_HOST if host["median"] > opp["median"]
                       else BattleWager.SIDE_OPPONENT)
    elif len(qualified) == 1:
        # One side never got judged — the judged one takes it, but only if they
        # actually put a take up. A walkover on an empty entry is not a win.
        only = qualified[0]
        winner_side = (BattleWager.SIDE_HOST if only is host else BattleWager.SIDE_OPPONENT)

    wagers = list(battle.wagers.select_related("user"))
    if winner_side is None:
        # Draw, or nobody qualified — hand every stake back untouched.
        for w in wagers:
            award_spinaz(w.user, w.amount, f"BattleZ refund: {battle.title}")
            w.paid_out = w.amount
            w.save(update_fields=["paid_out"])
        battle.winner = None
    else:
        winners = [w for w in wagers if w.side == winner_side]
        pot = sum(w.amount for w in wagers)
        staked = sum(w.amount for w in winners)
        if winners and staked:
            handed = 0
            # Biggest stake last so the rounding remainder lands there and the
            # pot comes out exactly — nothing evaporates.
            for i, w in enumerate(sorted(winners, key=lambda x: x.amount)):
                share = pot - handed if i == len(winners) - 1 else int(pot * w.amount / staked)
                handed += 0 if i == len(winners) - 1 else share
                award_spinaz(w.user, share, f"BattleZ win: {battle.title}")
                w.paid_out = share
                w.save(update_fields=["paid_out"])
        else:
            # Nobody backed the winner — the losers' stakes go back rather than
            # being pocketed by the house. We didn't earn them.
            for w in wagers:
                award_spinaz(w.user, w.amount, f"BattleZ refund: {battle.title}")
                w.paid_out = w.amount
                w.save(update_fields=["paid_out"])
        battle.winner = (battle.host if winner_side == BattleWager.SIDE_HOST
                         else battle.opponent)

    battle.held_wager_spinaz = 0
    battle.status = Battle.STATUS_SETTLED
    battle.settled_at = timezone.now()
    battle.save(update_fields=["winner", "status", "settled_at", "held_wager_spinaz", "updated_at"])
    for user in battle.contestants:
        if user:
            notify(user, "system",
                   (f"'{battle.title}' is settled — 👑 @{battle.winner.username} takes it"
                    if battle.winner else f"'{battle.title}' ended in a draw — every wager refunded"),
                   item_id=battle.item_key)
    return battle


def maybe_auto_settle(battle):
    """Settle a live battle whose window has passed. Safe to call on any read —
    otherwise a pool sits held forever because nobody pressed a button."""
    if battle.status == Battle.STATUS_OPEN and battle.ends_at and timezone.now() >= battle.ends_at:
        return settle_battle(battle)
    return battle


class BattleChallengeView(APIView):
    """POST /api/economy/battlez/challenge/ — name somebody and throw down.

    A 1v1 starts PENDING. Nothing is live, and no wager can be placed, until
    the other person accepts — a battle somebody was entered into without
    agreeing is not a battle.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        d = request.data or {}
        title = str(d.get("title", "")).strip()
        opponent_name = str(d.get("opponent", "")).strip()
        opponent = User.objects.filter(username__iexact=opponent_name).first()
        if not opponent:
            return Response({"detail": f"No member called '{opponent_name}'."},
                            status=status.HTTP_400_BAD_REQUEST)
        if opponent.id == request.user.id:
            return Response({"detail": "You can't battle yourself."},
                            status=status.HTTP_400_BAD_REQUEST)
        if opponent.id in blocked_user_ids(request.user):
            return Response({"detail": "You can't battle that member."},
                            status=status.HTTP_403_FORBIDDEN)

        gates = clean_gates(d.get("gates"))
        if gates:
            # The ranges apply to who you're allowed to CALL OUT, so a battle
            # advertised as "rating 8+" can't be aimed at somebody below it.
            me_p = profile_for(request.user)
            origin = ((me_p.lat, me_p.lng)
                      if (me_p.share_location and me_p.lat is not None) else (None, None))
            failed = failing_gate(member_metrics(profile_for(opponent), origin), gates)
            if failed:
                body = refusal(failed, gates)
                body["detail"] = f"@{opponent.username} is outside this battle's range — {describe(failed, gates)}."
                return Response(body, status=status.HTTP_403_FORBIDDEN)

        kind = str(d.get("kind", "1v1")).lower()
        b = Battle.objects.create(
            host=request.user, opponent=opponent,
            title=(title or f"@{request.user.username} vs @{opponent.username}")[:160],
            description=str(d.get("description", "") or ""),
            genre=str(d.get("genre", "") or "")[:40],
            mode=Battle.MODE_1V1,
            kind=kind if kind in ("1v1", "freestyle", "cypher") else "1v1",
            gates=gates, status=Battle.STATUS_PENDING, **_media(d),
        )
        notify(opponent, "system",
               f"@{request.user.username} challenged you to '{b.title}' ⚔️",
               actor=request.user, item_id=b.item_key)
        return Response(battle_dict(b, request), status=status.HTTP_201_CREATED)


class BattleRespondView(APIView):
    """POST /api/economy/battlez/<pk>/respond/ {accept: true|false}."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        b = Battle.objects.select_related("host", "opponent").filter(pk=pk).first()
        if not b:
            return Response({"detail": "battle not found"}, status=status.HTTP_404_NOT_FOUND)
        if b.opponent_id != request.user.id:
            return Response({"detail": "Only the person challenged can answer."},
                            status=status.HTTP_403_FORBIDDEN)
        if b.status != Battle.STATUS_PENDING:
            return Response({"detail": f"That challenge is already {b.status}."},
                            status=status.HTTP_409_CONFLICT)

        if not bool((request.data or {}).get("accept", True)):
            b.status = Battle.STATUS_DECLINED
            b.save(update_fields=["status", "updated_at"])
            notify(b.host, "system", f"@{request.user.username} declined '{b.title}'.",
                   actor=request.user, item_id=b.item_key)
            return Response(battle_dict(b, request))

        b.status = Battle.STATUS_OPEN
        b.accepted_at = timezone.now()
        # The clock starts on ACCEPTANCE, not on the challenge — otherwise a
        # slow reply eats the window the contestants actually get.
        b.ends_at = b.accepted_at + timedelta(hours=BATTLE_WINDOW_HOURS)
        b.save(update_fields=["status", "accepted_at", "ends_at", "updated_at"])
        notify(b.host, "system", f"@{request.user.username} accepted '{b.title}' — it's on ⚔️",
               actor=request.user, item_id=b.item_key)
        return Response(battle_dict(b, request))


class BattleWagerView(APIView):
    """POST /api/economy/battlez/<pk>/wager/ {side, amount} — spectators only."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        b = Battle.objects.select_related("host", "opponent").filter(pk=pk).first()
        if not b:
            return Response({"detail": "battle not found"}, status=status.HTTP_404_NOT_FOUND)
        b = maybe_auto_settle(b)
        if b.status != Battle.STATUS_OPEN:
            return Response({"detail": f"You can't wager on a {b.status} battle."},
                            status=status.HTTP_409_CONFLICT)
        if side_of(b, request.user):
            # A contestant betting on themselves is not a spectator, and betting
            # against themselves is a reason to lose on purpose.
            return Response({"detail": "You're in this battle — you can't wager on it."},
                            status=status.HTTP_403_FORBIDDEN)
        if b.wagers.filter(user=request.user).exists():
            return Response({"detail": "You've already got a wager on this one."},
                            status=status.HTTP_409_CONFLICT)

        d = request.data or {}
        side = str(d.get("side", "")).lower()
        if side not in (BattleWager.SIDE_HOST, BattleWager.SIDE_OPPONENT):
            return Response({"detail": "Pick a side."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            amount = int(d.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0
        if amount <= 0:
            return Response({"detail": "Stake some SpinaZ."}, status=status.HTTP_400_BAD_REQUEST)

        w = wallet_for(request.user)
        if (w.spinaz or 0) < amount:
            return Response(
                {"detail": f"That's {amount} SpinaZ and you have {w.spinaz or 0}.",
                 "spinaz": w.spinaz or 0},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        with transaction.atomic():
            # Held by the battle, not spent — a battle that never settles has to
            # be able to give every stake back.
            award_spinaz(request.user, -amount, f"BattleZ wager: {b.title}")
            BattleWager.objects.create(battle=b, user=request.user, side=side, amount=amount)
            Battle.objects.filter(pk=b.pk).update(
                held_wager_spinaz=models.F("held_wager_spinaz") + amount)
        b.refresh_from_db()
        return Response(battle_dict(b, request), status=status.HTTP_201_CREATED)


class BattleSettleView(APIView):
    """POST /api/economy/battlez/<pk>/settle/ — close it and pay the pool.

    Either contestant may settle once the window has passed. Before that only
    the clock can, so nobody ends it the moment they happen to be ahead.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        b = Battle.objects.select_related("host", "opponent").filter(pk=pk).first()
        if not b:
            return Response({"detail": "battle not found"}, status=status.HTTP_404_NOT_FOUND)
        if b.status != Battle.STATUS_OPEN:
            return Response({"detail": f"That battle is {b.status}."},
                            status=status.HTTP_409_CONFLICT)
        if not side_of(b, request.user):
            return Response({"detail": "Only a contestant can settle it."},
                            status=status.HTTP_403_FORBIDDEN)
        if b.ends_at and timezone.now() < b.ends_at:
            left = int((b.ends_at - timezone.now()).total_seconds() // 60) + 1
            return Response(
                {"detail": f"The window is still open — {left} minutes to go. "
                           "It settles itself when it closes.",
                 "minutes_left": left, "ends_at": b.ends_at.isoformat()},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(battle_dict(settle_battle(b), request))


class MoneyBattleVoteView(APIView):
    """GET the tally; POST toggles my vote.

    Real-money wagering is regulated gambling in most jurisdictions, so this
    counts demand rather than switching anything on. Shipping it on a show of
    hands would be reckless; pretending nobody asked would be dishonest.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            "votes": MoneyBattleVote.objects.count(),
            "my_vote": MoneyBattleVote.objects.filter(user=request.user).exists(),
            "note": "SpinaZ battles are live. Real-money battles need legal clearance first.",
        })

    def post(self, request):
        existing = MoneyBattleVote.objects.filter(user=request.user).first()
        if existing:
            existing.delete()
        else:
            MoneyBattleVote.objects.create(user=request.user)
        return self.get(request)
