"""The Weekly Open — one battle a week that anybody can enter.

The ordinary battle is two people and a room. This is the room's own event:
one open battle per calendar week (Monday 00:00 UTC to the next Monday),
created on first read, so nobody has to remember to start it and there is
never a week without one.

Ranked by the same thing every rating here is — the median of what OTHER
members scored each take — and an entry only places once BATTLE_MIN_RATINGS
people have judged it. A take nobody rated did not lose and did not win; it is
listed below the line as "needs N more ratings", which is also the ask that
brings people back to rate.

The prize is the crown: the winner is named on the board and on next week's
board, and every entrant is told. A currency prize is a pricing decision, so it
is one number (WEEKLY_PRIZE_SPINAZ, default 0) for Corey to set rather than a
figure chosen here.
"""
from datetime import datetime, time, timedelta, timezone as dt_tz

from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (BATTLE_MIN_RATINGS, Battle, BattleEntry, ItemRating, award_spinaz,
                     item_rating_medians, notify)

KIND = "weekly"
WEEKLY_PRIZE_SPINAZ = 0     # Corey's call; 0 means the crown is the prize


def week_bounds(now=None):
    now = now or timezone.now()
    start = datetime.combine((now - timedelta(days=now.weekday())).date(), time.min, tzinfo=dt_tz.utc)
    return start, start + timedelta(days=7)


def current_week():
    """This week's battle, made on first read. Settles last week's on the way."""
    from .views import platform_owner
    start, end = week_bounds()
    for old in Battle.objects.filter(kind=KIND, status=Battle.STATUS_OPEN, ends_at__lte=timezone.now()):
        settle_week(old)
    b = Battle.objects.filter(kind=KIND, created_at__gte=start, ends_at=end).first()
    if b:
        return b
    host = platform_owner()
    if not host:
        return None
    return Battle.objects.create(
        host=host, kind=KIND, mode=Battle.MODE_OPEN, status=Battle.STATUS_OPEN,
        title=f"Weekly Open — week of {start:%b} {start.day}",
        description="One take, any instrument, any genre. The room rates; the highest "
                    "median with enough ratings takes the crown.",
        ends_at=end, accepted_at=start)


def leaderboard(b, me=None):
    entries = list(b.entries.select_related("user"))
    keys = [e.item_key for e in entries]
    medians = item_rating_medians(keys)
    from django.db.models import Count
    counts = dict(ItemRating.objects.filter(item_id__in=keys).values_list("item_id")
                  .annotate(n=Count("id")))
    mine_rated = set()
    if me is not None and getattr(me, "is_authenticated", False):
        mine_rated = set(ItemRating.objects.filter(user=me, item_id__in=keys)
                         .values_list("item_id", flat=True))
    rows = []
    for e in entries:
        n = counts.get(e.item_key, 0)
        rows.append({
            "entry_id": e.id, "item_key": e.item_key, "username": e.user.username,
            "title": e.title, "media_type": e.media_type, "media_url": e.media_url,
            "image_url": e.image_url, "median": medians.get(e.item_key), "count": n,
            "qualified": n >= BATTLE_MIN_RATINGS,
            "needs": max(0, BATTLE_MIN_RATINGS - n),
            "mine": bool(me and e.user_id == getattr(me, "id", None)),
            "rated_by_me": e.item_key in mine_rated,
        })
    # Placed entries by median (ties share a rank), then the unplaced by how
    # close they are to placing.
    placed = sorted([r for r in rows if r["qualified"]], key=lambda r: -(r["median"] or 0))
    rank, last = 0, None
    for i, r in enumerate(placed):
        if r["median"] != last:
            rank, last = i + 1, r["median"]
        r["rank"] = rank
    waiting = sorted([r for r in rows if not r["qualified"]], key=lambda r: (r["needs"], r["entry_id"]))
    for r in waiting:
        r["rank"] = None
    return placed + waiting


@transaction.atomic
def settle_week(b):
    b = Battle.objects.select_for_update().get(pk=b.pk)
    if b.status != Battle.STATUS_OPEN:
        return b
    board = leaderboard(b)
    top = [r for r in board if r["rank"] == 1]
    # A tie at the top crowns nobody alone — both are named on the board.
    winner = None
    if len(top) == 1:
        from django.contrib.auth import get_user_model
        winner = get_user_model().objects.filter(username=top[0]["username"]).first()
    b.winner = winner
    b.status = Battle.STATUS_SETTLED
    b.settled_at = timezone.now()
    b.save(update_fields=["winner", "status", "settled_at", "updated_at"])
    if winner and WEEKLY_PRIZE_SPINAZ:
        award_spinaz(winner, WEEKLY_PRIZE_SPINAZ, f"Weekly Open win: {b.title}", app_key="battlez")
    for e in b.entries.select_related("user"):
        msg = (f"👑 You won '{b.title}'!" if winner and e.user_id == winner.id
               else f"'{b.title}' is settled — 👑 @{winner.username} takes it" if winner
               else f"'{b.title}' ended without a single winner — see the board")
        try:
            notify(e.user, "system", msg, item_id=b.item_key)
        except Exception:
            pass
    return b


def _summary(b, me):
    if not b:
        return None
    return {
        "id": b.id, "title": b.title, "description": b.description,
        "ends_at": b.ends_at, "status": b.status,
        "winner": b.winner.username if b.winner_id else "",
        "entered": bool(me and b.entries.filter(user=me).exists()),
        "board": leaderboard(b, me),
    }


class WeeklyBattleView(APIView):
    """GET /api/economy/battlez/weekly/ — this week's open battle, its board,
    and last week's result. Enter through the ordinary battle entry endpoint."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        b = current_week()
        last = (Battle.objects.filter(kind=KIND, status=Battle.STATUS_SETTLED)
                .select_related("winner").order_by("-ends_at").first())
        return Response({
            "week": _summary(b, request.user),
            "last_week": ({"id": last.id, "title": last.title,
                           "winner": last.winner.username if last.winner_id else "",
                           "board": leaderboard(last, request.user)[:3]} if last else None),
            "min_ratings": BATTLE_MIN_RATINGS,
            "prize_spinaz": WEEKLY_PRIZE_SPINAZ,
        })
