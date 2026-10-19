"""Real leaderboards measuring actual member activity and earnings.

All leaderboards track substance, never decoration: actual earnings, participation,
and progression. Gamified reality, not gamified nothing — per CLAUDE.md.

Leaderboards drive competition and motivate premium upgrades by showing:
- What top earners make daily (proof of ROI)
- How reach/verification compounds into passive income
- Peer progression on skills
- Urgency through weekly resets
"""

from datetime import timedelta
from django.contrib.auth import get_user_model
from django.db.models import Sum, Count, Q
from django.utils import timezone

from .models import TIER_FREE, Membership, Transaction, Wallet
from apps.skillz.models import TrainingProfile

User = get_user_model()


def top_spinaz_earners(limit=10, period_days=None):
    """Top earners by SpinaZ earned (all-time or weekly).

    Shows members what earning 🍥 is possible, motivating free tier to earn
    and free tier to convert to Premium (2x passive ⚡).

    Only public entries appear (visibility=public). Public earnings get 1.25x
    multiplier, incentivizing transparency and social proof.
    """
    qs = User.objects.annotate(
        spinaz_earned=Sum(
            "transactions__amount",
            filter=Q(transactions__resource=Transaction.RES_SPINAZ,
                    transactions__amount__gt=0,
                    transactions__visibility=Transaction.VIS_PUBLIC)
        )
    ).filter(spinaz_earned__isnull=False).order_by("-spinaz_earned")

    if period_days:
        cutoff = timezone.now() - timedelta(days=period_days)
        qs = User.objects.annotate(
            spinaz_earned=Sum(
                "transactions__amount",
                filter=Q(transactions__resource=Transaction.RES_SPINAZ,
                        transactions__amount__gt=0,
                        transactions__visibility=Transaction.VIS_PUBLIC,
                        transactions__created_at__gte=cutoff)
            )
        ).filter(spinaz_earned__isnull=False).order_by("-spinaz_earned")

    # `hasattr(u, "wallet_for")` was never true — wallet_for is a module
    # function, not an attribute of User — so this column was a hardcoded 0
    # wearing a lookup's clothes. One query for the page, not one per row.
    top = list(qs[:limit])
    balances = _spinaz_balances(top)
    return [
        {
            "rank": i + 1,
            "username": u.username,
            "spinaz_earned": u.spinaz_earned or 0,
            "current_spinaz": balances.get(u.id, 0),
        }
        for i, u in enumerate(top)
    ]


def top_energy_earners(limit=10, period_days=None):
    """Top earners by ⚡ earned (active + passive regen).

    Shows passive income strategy via reach/verification. Motivates:
    - Verification to unlock higher passive rates
    - Premium for 2x faster regen (shows concrete ROI)

    Only public entries appear (visibility=public gain +25% bonus).
    """
    qs = User.objects.annotate(
        energy_earned=Sum(
            "transactions__amount",
            filter=Q(transactions__resource=Transaction.RES_ENERGY,
                    transactions__amount__gt=0,
                    transactions__visibility=Transaction.VIS_PUBLIC)
        )
    ).filter(energy_earned__isnull=False).order_by("-energy_earned")

    if period_days:
        cutoff = timezone.now() - timedelta(days=period_days)
        qs = User.objects.annotate(
            energy_earned=Sum(
                "transactions__amount",
                filter=Q(transactions__resource=Transaction.RES_ENERGY,
                        transactions__amount__gt=0,
                        transactions__visibility=Transaction.VIS_PUBLIC,
                        transactions__created_at__gte=cutoff)
            )
        ).filter(energy_earned__isnull=False).order_by("-energy_earned")

    # Also show their membership tier to prove tier → regen rate.
    #
    # This was two `.objects.get()` calls per row: 2N queries for the page, and
    # a DoesNotExist — a 500 on the whole board — for any member whose
    # Membership or Wallet row had not been created yet. A leaderboard is the
    # one screen guaranteed to touch accounts the caller has never met, so the
    # missing row is a matter of time rather than an edge case.
    top = list(qs[:limit])
    ids = [u.id for u in top]
    tiers = dict(Membership.objects.filter(user_id__in=ids)
                 .values_list("user_id", "tier"))
    energies = dict(Wallet.objects.filter(user_id__in=ids)
                    .values_list("user_id", "energy"))
    return [
        {
            "rank": i + 1,
            "username": u.username,
            "energy_earned": u.energy_earned or 0,
            # No row yet means the default tier, which is what a member without
            # one actually has.
            "tier": tiers.get(u.id, TIER_FREE),
            "current_energy": energies.get(u.id, 0),
        }
        for i, u in enumerate(top)
    ]


def top_xp_earners_by_instrument(app_key, limit=10, period_days=None):
    """Top SkillZ practitioners by XP on one instrument.

    This asked `apps.skillz.models` for a `SkillProgression` that has never
    existed, at module scope, so importing this module raised — and since
    `LeaderboardsView` imports it INSIDE the request, every call to both
    leaderboard endpoints answered 500 from the day they were written. A
    module-level import would have failed the deploy and been fixed in an hour;
    the deferred one turned it into a screen that is simply always broken.

    The model is `TrainingProfile`, one per (user, app_key). Two more things
    were wrong beneath the name, and both would have survived a rename:

    * `transactions` is a reverse relation on USER, not on a training row, so
      `transactions__amount` was not a traversable path from here either.
    * XP does not live in the ledger. `TrainingProfile.xp` is the real running
      total the rest of SkillZ reads, and it is indexed on (app_key, -xp) for
      exactly this query. Ranking off Transaction rows would have ranked
      something else and called it progression.

    So: all-time ranks on the profile's own XP, and a period ranks on the
    `TrainingEvent` rows inside the window, which is the only place a
    time-bounded answer actually exists.

    Unlike the earnings boards there is NO visibility filter here, because
    training data carries no visibility flag to filter on. Rather than imply
    one, this ranks every profile with XP on the board — the profile is public
    and searchable by design, and SkillZ level is already read publicly (it is
    what LessonZ gates teaching on).
    """
    rows = TrainingProfile.objects.filter(app_key=app_key).select_related("user")

    if period_days:
        cutoff = timezone.now() - timedelta(days=period_days)
        rows = rows.annotate(
            window_xp=Sum("events__xp_awarded",
                          filter=Q(events__created_at__gte=cutoff))
        ).filter(window_xp__gt=0).order_by("-window_xp")
    else:
        rows = rows.filter(xp__gt=0).order_by("-xp")

    return [
        {
            "rank": i + 1,
            "username": p.user.username,
            # What ranked them: XP in the window, or the lifetime total.
            "xp_earned": (p.window_xp if period_days else p.xp) or 0,
            # `level` and `xp_into_level` are properties on the model, so they
            # are computed from the lifetime total either way — a member's
            # level is not a function of the week you happen to be looking at.
            "level": p.level,
            "xp_progress": p.xp,
        }
        for i, p in enumerate(rows[:limit])
    ]


def top_raters(limit=10, period_days=None):
    """Members who rate most, earning ⚡ per rating.

    Drives community rating behavior which fuels ranking/sorting.
    Period limiting shows weekly contest for urgency.

    Only public entries appear (visibility=public gain +25% bonus).
    """
    qs = User.objects.annotate(
        ratings_count=Count(
            "transactions",
            filter=Q(transactions__kind="rating",
                    transactions__visibility=Transaction.VIS_PUBLIC)
        )
    ).filter(ratings_count__gt=0).order_by("-ratings_count")

    if period_days:
        cutoff = timezone.now() - timedelta(days=period_days)
        qs = User.objects.annotate(
            ratings_count=Count(
                "transactions",
                filter=Q(transactions__kind="rating",
                        transactions__visibility=Transaction.VIS_PUBLIC,
                        transactions__created_at__gte=cutoff)
            )
        ).filter(ratings_count__gt=0).order_by("-ratings_count")

    return [
        {
            "rank": i + 1,
            "username": u.username,
            "ratings_count": u.ratings_count or 0,
        }
        for i, u in enumerate(qs[:limit])
    ]


def top_referrers(limit=10):
    """Members with most active referrals (joined via their code).

    Motivates network growth. Shows successful referrers as peers.

    Only public entries appear (visibility=public gain +25% bonus).
    """
    qs = User.objects.annotate(
        referral_count=Count(
            "transactions",
            filter=Q(transactions__kind="referral",
                    transactions__amount__gt=0,
                    transactions__visibility=Transaction.VIS_PUBLIC)
        ),
        referral_earned=Sum(
            "transactions__amount",
            filter=Q(transactions__kind="referral",
                    transactions__visibility=Transaction.VIS_PUBLIC)
        )
    ).filter(referral_count__gt=0).order_by("-referral_count")

    return [
        {
            "rank": i + 1,
            "username": u.username,
            "referral_count": u.referral_count or 0,
            "referral_earned": u.referral_earned or 0,
        }
        for i, u in enumerate(qs[:limit])
    ]


def _spinaz_balances(users):
    """{user_id: spinaz} for a page of users, in one query."""
    return dict(Wallet.objects.filter(user_id__in=[u.id for u in users])
                .values_list("user_id", "spinaz"))
