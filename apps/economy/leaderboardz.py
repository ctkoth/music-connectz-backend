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
from django.db.models import Sum, Count, Q, F, Max, Case, When, IntegerField
from django.utils import timezone

from .models import Transaction, Membership, Wallet
from apps.skillz.models import SkillProgression

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

    return [
        {
            "rank": i + 1,
            "username": u.username,
            "spinaz_earned": u.spinaz_earned or 0,
            "current_spinaz": wallet_for(u).spinaz if hasattr(u, 'wallet_for') else 0,
        }
        for i, u in enumerate(qs[:limit])
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

    # Also show their membership tier to prove tier → regen rate
    results = []
    for i, u in enumerate(qs[:limit]):
        m = Membership.objects.get(user=u)
        results.append({
            "rank": i + 1,
            "username": u.username,
            "energy_earned": u.energy_earned or 0,
            "tier": m.tier,  # proves tier → rate
            "current_energy": Wallet.objects.get(user=u).energy,
        })
    return results


def top_xp_earners_by_instrument(app_key, limit=10, period_days=None):
    """Top SkillZ practitioners by XP earned on one instrument.

    Drives instrument-specific competition and shows learning progression.
    Period limiting shows weekly contests for urgency.

    Only public entries appear (visibility=public gain +25% bonus).
    """
    from apps.skillz.models import SkillProgression

    qs = SkillProgression.objects.filter(app_key=app_key).annotate(
        xp_earned=Sum(
            "transactions__amount",
            filter=Q(transactions__resource=Transaction.RES_XP,
                    transactions__amount__gt=0,
                    transactions__visibility=Transaction.VIS_PUBLIC)
        )
    ).filter(xp_earned__isnull=False).order_by("-xp_earned")

    if period_days:
        cutoff = timezone.now() - timedelta(days=period_days)
        qs = SkillProgression.objects.filter(app_key=app_key).annotate(
            xp_earned=Sum(
                "transactions__amount",
                filter=Q(transactions__resource=Transaction.RES_XP,
                        transactions__amount__gt=0,
                        transactions__visibility=Transaction.VIS_PUBLIC,
                        transactions__created_at__gte=cutoff)
            )
        ).filter(xp_earned__isnull=False).order_by("-xp_earned")

    return [
        {
            "rank": i + 1,
            "username": sp.user.username,
            "xp_earned": sp.xp_earned or 0,
            "level": sp.level,
            "xp_progress": sp.xp,
        }
        for i, sp in enumerate(qs[:limit])
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


# Helper: import wallet_for only once per module
from .models import wallet_for
