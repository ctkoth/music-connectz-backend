from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.economy import searchfilters as sf
from apps.economy.models import Post

from .models import (CURRENCY_CHOICES, CURRENCY_MONEY, CURRENCY_SPINAZ,
                     FORMAT_CHOICES, FORMAT_1V1, SIDE_A, SIDE_B, STATUS_LIVE,
                     STATUS_OPEN, STATUS_VOTING, Battle, BattleEntry,
                     BattleVote, Bet, money_bet_error, spinaz_bet_error,
                     take_stake)


def _battle_dict(b, user=None, full=False):
    out = {
        "id": b.id, "format": b.format, "title": b.title, "rules": b.rules,
        "status": b.status, "created_by": b.created_by.username,
        "opens_at": b.opens_at, "closes_at": b.closes_at,
        "winner": b.winner or None,
        "votes": b.vote_counts(), "pools": b.pools(),
        "entry_count": b.entries.count(),
        "accepts_entries": b.accepts_entries,
        "accepts_bets": b.accepts_bets,
        "accepts_votes": b.accepts_votes,
        "requirements": b.requirements or {},
        "requirements_text": sf.describe(sf.load(b.requirements)),
    }
    if user and user.is_authenticated:
        out["your_side"] = b.side_of(user)
        out["you_voted"] = b.votes.filter(user=user).exists()
    if full:
        out["entries"] = [
            {"user": e.user.username, "side": e.side,
             "post_id": e.post_id, "joined_at": e.joined_at}
            for e in b.entries.select_related("user")
        ]
        out["settlement"] = b.settlement
    return out


class CatalogView(APIView):
    """GET the formats and the wagering rules. Public — it's a rulebook."""

    permission_classes = [AllowAny]

    def get(self, _request):
        return Response({
            "formats": [
                {"key": k, "label": v,
                 "icon": {"freestyle": "🆓", "1v1": "1️⃣",
                          "cypher": "🧑‍🤝‍🧑"}[k]}
                for k, v in FORMAT_CHOICES
            ],
            "currencies": [{"key": k, "label": v} for k, v in CURRENCY_CHOICES],
            "rules": {
                "money": "Contestants only, on themselves only, verified 18+ only.",
                "spinaz": "Spectators only. Contestants back themselves with money.",
                "settlement": "Cash and SpinAZ settle as separate pools and never "
                              "cross. The rake comes off the losing pool, so a "
                              "winner never gets back less than they staked.",
                "tie": "A tie refunds every stake. Nobody's money gets decided "
                       "by a coin flip.",
                "requirements": "Range gates set at post time are exclusive and "
                                "apply to entering the battle, not to betting "
                                "or voting on it.",
            },
            "ranges": sf.catalog(),
        })


class BattlesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Battle.objects.select_related("created_by")
        fmt = request.query_params.get("format")
        if fmt in dict(FORMAT_CHOICES):
            qs = qs.filter(format=fmt)
        state = request.query_params.get("status")
        if state:
            qs = qs.filter(status=state)
        return Response({"battles": [_battle_dict(b, request.user) for b in qs[:100]]})

    def post(self, request):
        d = request.data or {}
        title = str(d.get("title", "")).strip()
        if not title:
            return Response({"detail": "title required"},
                            status=status.HTTP_400_BAD_REQUEST)
        fmt = d.get("format") if d.get("format") in dict(FORMAT_CHOICES) else FORMAT_1V1
        b = Battle.objects.create(
            created_by=request.user, title=title[:160],
            rules=str(d.get("rules", ""))[:2000], format=fmt,
            requirements=sf.store(d))
        return Response({"battle": _battle_dict(b, request.user, full=True)},
                        status=status.HTTP_201_CREATED)


class BattleDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        b = Battle.objects.filter(pk=pk).first()
        if not b:
            return Response({"detail": "No such battle."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response({"battle": _battle_dict(b, request.user, full=True)})

    def patch(self, request, pk):
        """Advance the battle. Only the creator moves it along."""
        b = Battle.objects.filter(pk=pk, created_by=request.user).first()
        if not b:
            return Response({"detail": "Not your battle."},
                            status=status.HTTP_404_NOT_FOUND)
        target = (request.data or {}).get("status")
        allowed = {STATUS_OPEN: STATUS_LIVE, STATUS_LIVE: STATUS_VOTING}
        if target == "settled":
            return Response({"battle": _battle_dict(b, request.user, full=True),
                             "settlement": b.settle()})
        if target == "cancelled":
            return Response({"battle": _battle_dict(b, request.user, full=True),
                             "settlement": b.refund_all()})
        if allowed.get(b.status) != target:
            return Response(
                {"detail": f"Can't go from {b.status} to {target}."},
                status=status.HTTP_400_BAD_REQUEST)
        b.status = target
        b.save(update_fields=["status"])
        return Response({"battle": _battle_dict(b, request.user, full=True)})


class EntriesView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        b = Battle.objects.filter(pk=pk).first()
        if not b:
            return Response({"detail": "No such battle."},
                            status=status.HTTP_404_NOT_FOUND)
        if not b.accepts_entries:
            return Response({"detail": "Entries are closed."},
                            status=status.HTTP_409_CONFLICT)
        side = (request.data or {}).get("side")
        if side not in (SIDE_A, SIDE_B):
            return Response({"detail": "side must be 'a' or 'b'."},
                            status=status.HTTP_400_BAD_REQUEST)
        if b.entries.filter(user=request.user).exists():
            return Response({"detail": "You're already in this battle."},
                            status=status.HTTP_409_CONFLICT)

        # The creator's range gates decide who may compete. Checked before the
        # side-full check so a barred contestant hears the real reason rather
        # than "that side is full", which reads as bad luck instead of a rule.
        # Distance is measured against whoever made the battle.
        refused = sf.entry_error(request.user, b.requirements, viewer=b.created_by)
        if refused:
            return Response({"detail": refused, "requirements": b.requirements},
                            status=status.HTTP_403_FORBIDDEN)

        cap = b.max_per_side()
        if cap is not None and b.entries.filter(side=side).count() >= cap:
            return Response(
                {"detail": "That side is full — 1v1 means one artist a side."},
                status=status.HTTP_409_CONFLICT)

        post = None
        post_id = (request.data or {}).get("post_id")
        if post_id:
            post = Post.objects.filter(pk=post_id, author=request.user).first()
            if not post:
                return Response({"detail": "That's not your post."},
                                status=status.HTTP_400_BAD_REQUEST)

        BattleEntry.objects.create(battle=b, user=request.user, side=side, post=post)
        # The headline post for a side is the first one entered on it.
        field = "post_a" if side == SIDE_A else "post_b"
        if post and getattr(b, field) is None:
            setattr(b, field, post)
            b.save(update_fields=[field])
        return Response({"battle": _battle_dict(b, request.user, full=True)},
                        status=status.HTTP_201_CREATED)


class BetsView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        b = Battle.objects.select_for_update().filter(pk=pk).first()
        if not b:
            return Response({"detail": "No such battle."},
                            status=status.HTTP_404_NOT_FOUND)
        if not b.accepts_bets:
            return Response({"detail": "Betting is closed on this one."},
                            status=status.HTTP_409_CONFLICT)

        d = request.data or {}
        side = d.get("side")
        currency = d.get("currency")
        if side not in (SIDE_A, SIDE_B):
            return Response({"detail": "side must be 'a' or 'b'."},
                            status=status.HTTP_400_BAD_REQUEST)
        if currency not in dict(CURRENCY_CHOICES):
            return Response({"detail": "currency must be 'money' or 'spinaz'."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Eligibility before money moves, always.
        check = (money_bet_error if currency == CURRENCY_MONEY else spinaz_bet_error)
        problem = check(b, request.user, side)
        if problem:
            return Response({"detail": problem},
                            status=status.HTTP_403_FORBIDDEN)

        try:
            amount = int(d.get("amount") or 0)
        except (TypeError, ValueError):
            return Response({"detail": "amount must be a whole number."},
                            status=status.HTTP_400_BAD_REQUEST)

        failure = take_stake(request.user, currency, amount)
        if failure:
            return Response({"detail": failure},
                            status=status.HTTP_402_PAYMENT_REQUIRED)

        bet = Bet.objects.create(battle=b, user=request.user, side=side,
                                 currency=currency, amount=amount)
        return Response({"bet": {"id": bet.id, "side": bet.side,
                                 "currency": bet.currency, "amount": bet.amount},
                         "pools": b.pools()},
                        status=status.HTTP_201_CREATED)


class VotesView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        b = Battle.objects.filter(pk=pk).first()
        if not b:
            return Response({"detail": "No such battle."},
                            status=status.HTTP_404_NOT_FOUND)
        if not b.accepts_votes:
            return Response({"detail": "Voting isn't open."},
                            status=status.HTTP_409_CONFLICT)
        side = (request.data or {}).get("side")
        if side not in (SIDE_A, SIDE_B):
            return Response({"detail": "side must be 'a' or 'b'."},
                            status=status.HTTP_400_BAD_REQUEST)
        # A contestant voting for themselves is not a vote, it's a thumb on the
        # scale — and the result decides who gets paid.
        if b.is_contestant(request.user):
            return Response({"detail": "Contestants don't vote in their own battle."},
                            status=status.HTTP_403_FORBIDDEN)
        if b.votes.filter(user=request.user).exists():
            return Response({"detail": "You already voted."},
                            status=status.HTTP_409_CONFLICT)
        BattleVote.objects.create(battle=b, user=request.user, side=side)
        return Response({"votes": b.vote_counts()}, status=status.HTTP_201_CREATED)
