"""Discovery Engine — personalized recommendations based on listening behavior.

The discovery engine solves: "How do I find new music/creators I'll like?"

It works by:
1. Tracking what members listen to and rate
2. Finding members with similar taste (taste affinity)
3. Recommending posts from those members that you haven't heard

This creates a virtuous cycle:
- Better recommendations → members listen more
- More listening → better data for recommendations
- Better discovery → creators get audience → they improve → better content

The algorithm is deliberately simple and verifiable (not a black box).
"""
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.db.models import F, Q, Count, Avg, Value
from django.db.models.functions import Coalesce

from .models import Post, ListenProgress, ItemRating


def taste_affinity(user1_id, user2_id, min_overlap=3):
    """Calculate taste affinity between two users (0-1).

    Taste affinity = how similar their listening patterns are.

    Returns a score from 0 (nothing in common) to 1 (identical taste).
    Only calculated if users have listened to at least min_overlap items together.
    """
    # Find items both users have listened to
    user1_listens = set(
        ListenProgress.objects.filter(user_id=user1_id, seconds__gte=10)
        .values_list('item_id', flat=True)
    )
    user2_listens = set(
        ListenProgress.objects.filter(user_id=user2_id, seconds__gte=10)
        .values_list('item_id', flat=True)
    )

    overlap = user1_listens & user2_listens
    if len(overlap) < min_overlap:
        return 0.0

    # Find shared ratings on overlapping items
    user1_ratings = dict(
        ItemRating.objects.filter(user_id=user1_id, item_id__in=overlap)
        .values_list('item_id', 'score')
    )
    user2_ratings = dict(
        ItemRating.objects.filter(user_id=user2_id, item_id__in=overlap)
        .values_list('item_id', 'score')
    )

    if not user1_ratings or not user2_ratings:
        return 0.0

    # Score based on rating agreement on shared items
    # If you both rated the same items similarly, you have similar taste
    agreements = 0
    for item_id in overlap:
        if item_id in user1_ratings and item_id in user2_ratings:
            r1 = user1_ratings[item_id]
            r2 = user2_ratings[item_id]
            # Agreement: both liked (>= 6) or both didn't (< 6)
            if (r1 >= 6 and r2 >= 6) or (r1 < 6 and r2 < 6):
                agreements += 1

    return agreements / len(overlap) if overlap else 0.0


def recommendations_for(user, limit=50):
    """Generate recommendations for a member.

    Returns posts from members with similar taste that the user hasn't heard.

    Algorithm:
    1. Find members with similar taste (top 20 by affinity)
    2. Get their recent posts
    3. Filter out posts user has already heard
    4. Rank by: creator taste affinity, post rating, recency
    5. Return top N
    """
    # Step 1: Find taste-similar members
    # This is expensive in production (would need denormalization),
    # but works for MVP. Real version would cache affinities.

    from django.contrib.auth import get_user_model
    User = get_user_model()

    all_users = User.objects.filter(is_active=True).exclude(id=user.id)
    affinities = []

    for other_user in all_users[:500]:  # Limit to prevent timeout
        aff = taste_affinity(user.id, other_user.id, min_overlap=2)
        if aff > 0:
            affinities.append((other_user, aff))

    if not affinities:
        # Fallback to newest posts if no taste matches
        return _fallback_recommendations(user, limit)

    # Sort by affinity, take top creators
    affinities.sort(key=lambda x: x[1], reverse=True)
    similar_user_ids = [u.id for u, _ in affinities[:20]]

    # Step 2: Get their recent posts (last 30 days)
    cutoff = timezone.now() - timezone.timedelta(days=30)
    posts = Post.objects.filter(
        author_id__in=similar_user_ids,
        created_at__gte=cutoff,
        visibility='public'  # Only recommend public posts
    ).select_related('author', 'author__membership')

    # Step 3: Filter out what user has already listened to
    heard_item_ids = set(
        ListenProgress.objects.filter(user_id=user.id)
        .values_list('item_id', flat=True)
    )

    recommendations = []
    for p in posts:
        if f"post:{p.id}" not in heard_item_ids:
            # Find the affinity of this post's creator
            creator_affinity = next(
                (aff for u, aff in affinities if u.id == p.author_id),
                0
            )
            recommendations.append((p, creator_affinity))

    # Step 4: Rank recommendations
    # Prefer: similar creators, well-rated posts, recent
    from apps.economy.models import item_rating_medians

    post_ids = [p.id for p, _ in recommendations]
    ratings = item_rating_medians([f"post:{p}" for p in post_ids])

    def rank_score(item):
        post, creator_affinity = item
        post_rating = ratings.get(f"post:{post.id}", 0) or 0
        age_days = (timezone.now() - post.created_at).days

        # Score = (creator affinity) + (post rating / 10) - (age penalty)
        # Affinity: 0-1 (most important)
        # Rating: normalized to 0-1 scale
        # Recency: penalize old posts
        score = (
            creator_affinity * 5 +  # Creator match is most important
            (post_rating / 10.0) +   # Post quality
            max(0, 1 - age_days / 30)  # Recent boost (30 day window)
        )
        return score

    recommendations.sort(key=rank_score, reverse=True)
    return [p for p, _ in recommendations[:limit]]


def _fallback_recommendations(user, limit=50):
    """Fallback when no taste matches found: return newest public posts."""
    from apps.economy.models import can_view_post

    cutoff = timezone.now() - timezone.timedelta(days=7)
    posts = Post.objects.filter(
        created_at__gte=cutoff,
        visibility='public'
    ).select_related('author', 'author__membership').order_by('-created_at')

    heard_item_ids = set(
        ListenProgress.objects.filter(user_id=user.id)
        .values_list('item_id', flat=True)
    )

    result = []
    for p in posts:
        if f"post:{p.id}" not in heard_item_ids and can_view_post(p, user):
            result.append(p)
            if len(result) >= limit:
                break

    return result


def genre_recommendations_for(user, genre, limit=30):
    """Recommend posts in a specific genre.

    Simple filter-based discovery: show posts in genres the user might like.
    """
    from apps.economy.models import can_view_post

    cutoff = timezone.now() - timezone.timedelta(days=14)
    posts = Post.objects.filter(
        genre=genre,
        created_at__gte=cutoff,
        visibility='public'
    ).select_related('author', 'author__membership').order_by('-created_at')

    heard_item_ids = set(
        ListenProgress.objects.filter(user_id=user.id)
        .values_list('item_id', flat=True)
    )

    result = []
    for p in posts:
        if f"post:{p.id}" not in heard_item_ids and can_view_post(p, user):
            result.append(p)
            if len(result) >= limit:
                break

    return result
