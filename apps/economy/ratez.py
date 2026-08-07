"""RateZ — every rating in the app, each one classified for what it is.

Five different things were all called "a rating", and a number with no label is
a number nobody can act on. A member seeing "8.4" had no way to know whether
that was their work, their mixing, their face or them.

    post           the WORK          given directly on a post
    skill          a SKILL you used  derived from the posts that used it
    contribution   your PART of a deal   given by people not on the deal
    overall        YOU               given directly on a profile
    attractiveness YOU               kept apart on purpose

The one that changed: a post rating used to land on the post and stop. It now
lands on the skills that made the post too, for the person who brought each —
so a mix engineer with forty well-rated posts has a rated skill to show for it,
and the price they charge is backed by something.

Nothing here is rated directly except what the member chose to rate. A skill
rating exists only because somebody rated a piece of work that used it, which
is what keeps it a measure of work rather than an opinion about a person.
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    ItemRating,
    OverallRating,
    Post,
    RATING_KINDS,
    SkillRating,
    attractiveness_median,
    item_rating_median,
    overall_median,
    skill_rating_median,
)

User = get_user_model()


def skills_of(user):
    """Every skill this member has been rated on, with the median and the count.

    Sorted by how much work is behind it, not by score — a 10 from one rating
    should not outrank a 9 from thirty, and showing the count is what lets a
    reader tell those apart.
    """
    rows = {}
    for r in SkillRating.objects.filter(subject=user).values_list("skill", "score"):
        rows.setdefault(r[0], []).append(r[1])
    out = []
    for skill, scores in rows.items():
        out.append({
            "skill": skill,
            "rating": skill_rating_median(user, skill),
            "count": len(scores),
            "kind": "skill",
        })
    out.sort(key=lambda r: (-r["count"], -(r["rating"] or 0)))
    return out


def posts_of(user, limit=50):
    """The member's own posts and what each scored."""
    qs = Post.objects.filter(author=user).order_by("-created_at")[:limit]
    return [{
        "id": p.id, "title": p.title, "kind": "post",
        "item_key": f"post:{p.id}",
        "rating": item_rating_median(f"post:{p.id}"),
        "count": ItemRating.objects.filter(item_id=f"post:{p.id}").count(),
        "skills_used": p.skills_used or [],
        "co_owned": bool(p.contributors),
    } for p in qs]


class RatezView(APIView):
    """GET /api/economy/ratez/ — every rating about a member, by kind.

    `?username=` reads someone else's; without it, your own.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        username = (request.query_params.get("username") or "").strip()
        user = (User.objects.filter(username__iexact=username).first()
                if username else request.user)
        if not user:
            return Response({"detail": "member not found"}, status=status.HTTP_404_NOT_FOUND)

        skills = skills_of(user)
        posts = posts_of(user)
        rated_posts = [p for p in posts if p["rating"] is not None]

        return Response({
            "username": user.username,
            "mine": user.id == request.user.id,
            # The taxonomy itself, served rather than hardcoded on the client,
            # so a label can't drift from what the number actually measures.
            "kinds": RATING_KINDS,
            "post": {
                "kind": "post", "of": "the work",
                "posts": posts,
                # The average of what their work scored — NOT an average of
                # averages across skills, which would double-count a post that
                # used four of them.
                "median": (round(sum(p["rating"] for p in rated_posts) / len(rated_posts), 1)
                           if rated_posts else None),
                "rated": len(rated_posts), "total": len(posts),
            },
            "skill": {
                "kind": "skill", "of": "a skill you used",
                "skills": skills,
                "note": "Nobody rates a skill directly. Rating a post rates "
                        "every skill that went into it, for whoever brought it.",
            },
            "overall": {
                "kind": "overall", "of": "you",
                "median": overall_median(user),
                "count": OverallRating.objects.filter(target=user).count(),
            },
            "attractiveness": {
                "kind": "attractiveness", "of": "you",
                "median": attractiveness_median(user),
                "note": "Kept apart from the rest on purpose — it is not a "
                        "judgement of anybody's work.",
            },
        })


class RatingKindsView(APIView):
    """GET /api/economy/ratez/kinds/ — what each rating in this app measures."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"kinds": RATING_KINDS})
