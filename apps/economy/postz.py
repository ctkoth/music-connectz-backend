"""PostZ — cross-user posts with visibility + restricted-join SpinAZ rewards.

Posting costs energy equal to the combined price of the skills used (in cents).
Restricted posts reward the author 300 SpinAZ per valid join from a distinct,
non-author visitor.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db.models import Case, IntegerField, Sum, When
from django.utils import timezone

from .models import (
    Post,
    PostJoin,
    Reaction,
    ItemRating,
    RESTRICTED_JOIN_REWARD_SPINAZ,
    award_spinaz,
    can_view_post,
    item_rating_median,
    wallet_for,
)

# Reach engine: likes/dislikes rank the feed (they never touch price — that's
# ratings' job). Heavy dislike ratio downranks + flags for moderation.
HIDE_FLAG_MIN_DOWN = 5   # need at least this many dislikes to consider hiding
HIDE_FLAG_RATIO = 2.0    # ...and dislikes must exceed likes by this factor


def _client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _reactions_for(post_ids):
    """{post_id: (up, down)} from the shared Reaction table keyed 'post:<id>'."""
    rows = (
        Reaction.objects
        .filter(item_id__in=[f"post:{pid}" for pid in post_ids])
        .values("item_id")
        .annotate(
            up=Sum(Case(When(value=1, then=1), default=0, output_field=IntegerField())),
            down=Sum(Case(When(value=-1, then=1), default=0, output_field=IntegerField())),
        )
    )
    out = {}
    for r in rows:
        try:
            pid = int(r["item_id"].split(":", 1)[1])
        except (ValueError, IndexError):
            continue
        out[pid] = (r["up"] or 0, r["down"] or 0)
    return out


def _post_dict(p, request, up=0, down=0):
    vibe = up - down
    flagged = down >= HIDE_FLAG_MIN_DOWN and down >= up * HIDE_FLAG_RATIO
    return {
        "id": p.id,
        "author": p.author.username,
        "mine": p.author_id == request.user.id,
        "title": p.title,
        "description": p.description,
        "links": p.links,
        "media_type": p.media_type,
        "visibility": p.visibility,
        "skill_cost_cents": p.skill_cost_cents,
        "joins": p.joins.count() if p.visibility == "restricted" else 0,
        "up": up, "down": down, "vibe": vibe, "flagged": flagged,
        "rating": item_rating_median(f"post:{p.id}"),
        "created_at": p.created_at.isoformat(),
    }


class PostsView(APIView):
    """GET the visible feed; POST creates a post (charges the skill-cost energy).

    sort=hot (default, vibe×recency), new (chronological), or top (by rating).
    Likes/dislikes rank reach here; ratings drive value elsewhere.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        sort = (request.query_params.get("sort") or "hot").lower()
        qs = Post.objects.select_related("author").exclude(visibility="private").order_by("-created_at")[:300]
        mine = Post.objects.filter(author=request.user, visibility="private")
        visible = [p for p in list(qs) + list(mine) if can_view_post(p, request.user)]
        reactions = _reactions_for([p.id for p in visible])
        posts = [_post_dict(p, request, *reactions.get(p.id, (0, 0))) for p in visible]

        now = timezone.now()

        def hot(d, p):
            # vibe boosted, decayed by age (hours). Flagged posts sink.
            age_h = max(1.0, (now - p.created_at).total_seconds() / 3600)
            base = (d["vibe"] + 1) / (age_h ** 0.6)
            return base - (100 if d["flagged"] else 0)

        by_id = {p.id: p for p in visible}
        if sort == "new":
            posts.sort(key=lambda d: d["created_at"], reverse=True)
        elif sort == "top":
            posts.sort(key=lambda d: (d["rating"] or 0, d["vibe"]), reverse=True)
        else:  # hot
            posts.sort(key=lambda d: hot(d, by_id[d["id"]]), reverse=True)
        return Response({"posts": posts[:100], "sort": sort})

    def post(self, request):
        d = request.data
        title = str(d.get("title", "")).strip()[:160]
        if not title:
            return Response({"detail": "title required"}, status=status.HTTP_400_BAD_REQUEST)
        vis = str(d.get("visibility", "public")).lower()
        if vis not in {"public", "restricted", "private"}:
            vis = "public"
        cost = max(0, int(d.get("skill_cost_cents") or 0))
        # Posting costs energy = combined skill price (cents). Deduct what's there.
        w = wallet_for(request.user)
        charged = min(cost, max(0, w.energy))
        if charged:
            w.energy -= charged
            w.save(update_fields=["energy", "updated_at"])
        p = Post.objects.create(
            author=request.user, title=title,
            description=str(d.get("description", ""))[:4000],
            links=d.get("links") or [], media_type=str(d.get("media_type", ""))[:24],
            visibility=vis, skill_cost_cents=cost,
        )
        return Response({**_post_dict(p, request), "energy_charged": charged, "energy": w.energy}, status=status.HTTP_201_CREATED)


class PostJoinView(APIView):
    """Record a join on a restricted post. First join from a distinct non-author
    IP rewards the author 300 SpinAZ. Repeat calls update active time only."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        p = Post.objects.filter(pk=pk).select_related("author").first()
        if not p:
            return Response({"detail": "post not found"}, status=status.HTTP_404_NOT_FOUND)
        if p.visibility != "restricted":
            return Response({"detail": "post is not restricted"}, status=status.HTTP_400_BAD_REQUEST)
        ip = _client_ip(request)
        active = max(0, int(request.data.get("active_seconds") or 0))
        join, created = PostJoin.objects.get_or_create(
            post=p, ip=ip, defaults={"user": request.user, "active_seconds": active}
        )
        rewarded = False
        if not created:
            join.active_seconds = max(join.active_seconds, active)
            join.save(update_fields=["active_seconds"])
        # Valid join = distinct IP that isn't the author's; reward once.
        if created and not join.rewarded and p.author_id != request.user.id:
            award_spinaz(p.author, RESTRICTED_JOIN_REWARD_SPINAZ, note=f"Restricted join on '{p.title}'")
            join.rewarded = True
            join.save(update_fields=["rewarded"])
            rewarded = True
        return Response({"joined": True, "rewarded": rewarded, "reward_spinaz": RESTRICTED_JOIN_REWARD_SPINAZ if rewarded else 0, "joins": p.joins.count()})
