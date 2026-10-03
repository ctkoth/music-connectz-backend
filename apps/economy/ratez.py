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

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from .models import (
    ItemRating,
    OverallRating,
    POST_RATE_UNLOCK_SEC,
    Post,
    RATING_KINDS,
    RATING_NOTE,
    RATING_REWARD_DAILY_CAP,
    RATING_REWARD_ENERGY,
    SkillRating,
    _median,
    adult_only_reason,
    attractiveness_median,
    badge_effects,
    can_view_post,
    heard_enough_required,
    item_rating_medians,
    overall_median,
    skill_rating_median,
    Transaction,
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


def posts_of(user, viewer, limit=50):
    """The member's posts the VIEWER may see, and what each scored.

    It listed every post the member had ever made, private ones included, to
    anybody who asked by username — title, score and all. The feed's own
    visibility rule decides now, the same check /p/<id> runs.

    Medians and counts are fetched once for the whole list, not once per post:
    fifty posts used to be a hundred queries.
    """
    posts = [p for p in Post.objects.filter(author=user).order_by("-created_at")[:limit]
             if can_view_post(p, viewer)]
    keys = [f"post:{p.id}" for p in posts]
    medians = item_rating_medians(keys)
    counts = dict(ItemRating.objects.filter(item_id__in=keys)
                  .values_list("item_id").annotate(n=Count("id")))
    return [{
        "id": p.id, "title": p.title, "kind": "post",
        "item_key": f"post:{p.id}",
        "rating": medians.get(f"post:{p.id}"),
        "count": counts.get(f"post:{p.id}", 0),
        "skills_used": p.skills_used or [],
        "co_owned": bool(p.contributors),
        "url": f"/p/{p.id}",
    } for p in posts]


def contribution_of(user):
    """What the room thought this member did on their deals.

    Contribution ratings are ItemRatings keyed `collab:<deal>:<username>`,
    given by people NOT on the deal — the number that re-cuts a split when a
    deal pays on rating. RATING_KINDS has always declared this kind and the
    dashboard never served it.
    """
    suffix = f":{user.username}"
    rows = (ItemRating.objects.filter(item_id__startswith="collab:", item_id__endswith=suffix)
            .values_list("item_id", "score"))
    by_deal = {}
    for item_id, score in rows:
        parts = item_id.split(":")
        if len(parts) == 3 and parts[2] == user.username:
            by_deal.setdefault(parts[1], []).append(score)
    all_scores = [x for v in by_deal.values() for x in v]
    return {
        "kind": "contribution", "of": "your part of a deal",
        "median": _median(all_scores) if all_scores else None,
        "count": len(all_scores), "deals": len(by_deal),
    }


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
        posts = posts_of(user, request.user)
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
            "contribution": contribution_of(user),
            # Rating people on looks is adults-only in BOTH directions (Play
            # Families) — AttractivenessRateView and FaceZ already hold that
            # line, and this read did not: anybody could read anybody's,
            # a minor's included, by username. Locked with the reason now.
            "attractiveness": (
                {"kind": "attractiveness", "of": "you", "median": None,
                 "locked": adult_only_reason(request.user) or adult_only_reason(user)}
                if (adult_only_reason(request.user) or adult_only_reason(user)) else
                {"kind": "attractiveness", "of": "you",
                 "median": attractiveness_median(user),
                 "note": "Kept apart from the rest on purpose — it is not a "
                         "judgement of anybody's work."}),
        })


def rating_reward(user):
    """The gain a rating pays this member right now, for showing BEFORE they rate."""
    left, cap = rating_reward_left(user)
    return {"resource": "energy", "amount": RATING_REWARD_ENERGY if left else 0,
            "left_today": left, "cap": cap,
            "public_bonus_pct": 25, "per_collaborator_pct": 10}


def rating_reward_left(user):
    """How many more ratings today still pay, so the gain is stated honestly.

    Same count reward_for_rating makes: a +1 ⚡ that the cap has already
    used up is not a gain, and showing it beside the button would be a promise
    the server then breaks.
    """
    day_ago = timezone.now() - timedelta(hours=24)
    paid = Transaction.objects.filter(
        user=user, resource=Transaction.RES_ENERGY,
        note__startswith=RATING_NOTE, created_at__gte=day_ago,
    ).count()
    cap = RATING_REWARD_DAILY_CAP + badge_effects(user).get("rating_cap_bonus", 0)
    return max(0, cap - paid), cap


class RateQueueView(APIView):
    """GET /api/economy/ratez/queue/ — work by other members you haven't rated.

    The other half of RateZ: the dashboard shows what you've been given, this
    is where you give. Only posts the rate endpoint would ACCEPT — not yours,
    past the unlock window, visible to you — so nothing here is a button that
    answers 403.

    `needs_listen` is the substance rule carried through: a track you have not
    heard is not one you can score, so those rows open the post's own player
    rather than offering a number beside the title.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        me = request.user
        cutoff = timezone.now() - timedelta(seconds=POST_RATE_UNLOCK_SEC)
        rated = ItemRating.objects.filter(user=me, item_id__startswith="post:").values_list("item_id", flat=True)
        rated_ids = {int(k.split(":", 1)[1]) for k in rated if k.split(":", 1)[1].isdigit()}
        qs = (Post.objects.exclude(author=me).exclude(visibility="private")
              .filter(created_at__lte=cutoff).exclude(pk__in=rated_ids)
              .select_related("author").order_by("-created_at")[:60])
        posts = [p for p in qs if can_view_post(p, me)][:20]
        keys = [f"post:{p.id}" for p in posts]
        medians = item_rating_medians(keys)
        counts = dict(ItemRating.objects.filter(item_id__in=keys)
                      .values_list("item_id").annotate(n=Count("id")))
        left, cap = rating_reward_left(me)
        return Response({
            "reward": {"resource": "energy", "amount": RATING_REWARD_ENERGY if left else 0,
                       "left_today": left, "cap": cap},
            "posts": [{
                "id": p.id, "item_key": f"post:{p.id}", "title": p.title,
                "author": p.author.username, "media_type": p.media_type or "",
                "needs_listen": heard_enough_required(p),
                "rating": medians.get(f"post:{p.id}"),
                "count": counts.get(f"post:{p.id}", 0),
                "skills_used": p.skills_used or [],
                "url": f"/p/{p.id}",
            } for p in posts],
        })


class RatingKindsView(APIView):
    """GET /api/economy/ratez/kinds/ — what each rating in this app measures."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"kinds": RATING_KINDS})
