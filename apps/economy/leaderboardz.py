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
from django.db.models import Sum, Count, Q, Max, Avg
from django.utils import timezone

from .models import TIER_FREE, Membership, Transaction, Wallet, Badge, Post
from apps.skillz.models import TrainingProfile, TrainingEvent

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


def top_followers(limit=10, period_days=None):
    """Members with most followers — social proof and reach.

    Shows network power and community trust. Motivates:
    - Following others to build audience reciprocally
    - Engagement to grow followers
    - Verification to establish credibility
    """
    qs = User.objects.annotate(
        followers_count=Count(
            "follower_set",  # reverse relation of Follow.following
            distinct=True
        )
    ).filter(followers_count__gt=0).order_by("-followers_count")

    if period_days:
        # For period, count only followers who followed in the window
        cutoff = timezone.now() - timedelta(days=period_days)
        qs = User.objects.annotate(
            followers_count=Count(
                "follower_set",
                filter=Q(follower_set__created_at__gte=cutoff),
                distinct=True
            )
        ).filter(followers_count__gt=0).order_by("-followers_count")

    return [
        {
            "rank": i + 1,
            "username": u.username,
            "followers_count": u.followers_count or 0,
        }
        for i, u in enumerate(qs[:limit])
    ]


def top_streak_keepers(limit=10, period_days=None):
    """Members with longest streaks across all instruments.

    Motivation: consistency, dedication, habit formation.
    Shows discipline and reliability.
    """
    qs = User.objects.annotate(
        longest_streak=Max(
            "training_profiles__longest_streak"
        )
    ).filter(longest_streak__gt=0).order_by("-longest_streak")

    if period_days:
        # For period, show current streaks (within-window only)
        cutoff = timezone.now() - timedelta(days=period_days)
        qs = User.objects.annotate(
            current_streak=Max(
                "training_profiles__current_streak",
                filter=Q(training_profiles__events__created_at__gte=cutoff)
            )
        ).filter(current_streak__gt=0).order_by("-current_streak")

    return [
        {
            "rank": i + 1,
            "username": u.username,
            "streak_days": (u.longest_streak if not period_days else u.current_streak) or 0,
        }
        for i, u in enumerate(qs[:limit])
    ]


def top_verified_reach(limit=10, period_days=None):
    """Members with highest verified external reach/followers.

    Shows network power from external validation (Spotify, YouTube, etc).
    Motivates external account verification for passive ⚡.
    """
    # Note: This assumes Profile.external_followers exists and tracks verified sources.
    # Falls back to 0 if field doesn't exist.
    try:
        qs = User.objects.annotate(
            verified_reach=Sum(
                "profile__external_followers",
                filter=Q(profile__isnull=False)
            )
        ).filter(verified_reach__isnull=False, verified_reach__gt=0).order_by("-verified_reach")

        if period_days:
            # Period version shows growth in verified reach (not meaningful for this metric,
            # so we use all-time)
            pass

        return [
            {
                "rank": i + 1,
                "username": u.username,
                "verified_reach": int(u.verified_reach) or 0,
            }
            for i, u in enumerate(qs[:limit])
        ]
    except Exception:
        # If field doesn't exist, return empty leaderboard
        return []


def top_badge_collectors(limit=10, period_days=None):
    """Members who've earned the most badges.

    Shows achievement/completion. Motivates:
    - Reaching milestones
    - Diversifying across platform features
    - Engagement across different domains
    """
    qs = User.objects.annotate(
        badges_earned=Count(
            "badges",  # reverse relation from Badge.user
            distinct=True
        )
    ).filter(badges_earned__gt=0).order_by("-badges_earned")

    if period_days:
        cutoff = timezone.now() - timedelta(days=period_days)
        qs = User.objects.annotate(
            badges_earned=Count(
                "badges",
                filter=Q(badges__awarded_at__gte=cutoff),
                distinct=True
            )
        ).filter(badges_earned__gt=0).order_by("-badges_earned")

    return [
        {
            "rank": i + 1,
            "username": u.username,
            "badges_earned": u.badges_earned or 0,
        }
        for i, u in enumerate(qs[:limit])
    ]


def top_content_creators(limit=10, period_days=None):
    """Members who've created the most posts.

    Shows content production. Motivates:
    - Sharing work
    - Building audience through consistent posts
    - Content-based earning
    """
    qs = User.objects.annotate(
        posts_count=Count(
            "posts",
            distinct=True
        )
    ).filter(posts_count__gt=0).order_by("-posts_count")

    if period_days:
        cutoff = timezone.now() - timedelta(days=period_days)
        qs = User.objects.annotate(
            posts_count=Count(
                "posts",
                filter=Q(posts__created_at__gte=cutoff),
                distinct=True
            )
        ).filter(posts_count__gt=0).order_by("-posts_count")

    return [
        {
            "rank": i + 1,
            "username": u.username,
            "posts_count": u.posts_count or 0,
        }
        for i, u in enumerate(qs[:limit])
    ]


def _spinaz_balances(users):
    """{user_id: spinaz} for a page of users, in one query."""
    return dict(Wallet.objects.filter(user_id__in=[u.id for u in users])
                .values_list("user_id", "spinaz"))
