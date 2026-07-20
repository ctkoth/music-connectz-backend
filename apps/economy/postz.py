"""PostZ — cross-user posts with visibility + restricted-join SpinAZ rewards.

Posting costs energy equal to the combined price of the skills used (in cents).
Restricted posts reward the author 300 SpinAZ per valid join from a distinct,
non-author visitor.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Post,
    PostJoin,
    RESTRICTED_JOIN_REWARD_SPINAZ,
    award_spinaz,
    can_view_post,
    wallet_for,
)


def _client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _post_dict(p, request):
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
        "created_at": p.created_at.isoformat(),
    }


class PostsView(APIView):
    """GET the visible feed; POST creates a post (charges the skill-cost energy)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Public to everyone; restricted to any member; private only to author.
        qs = Post.objects.select_related("author").exclude(
            visibility="private"
        ).order_by("-created_at")[:200]
        mine = Post.objects.filter(author=request.user, visibility="private")
        posts = [_post_dict(p, request) for p in list(qs) + list(mine) if can_view_post(p, request.user)]
        posts.sort(key=lambda d: d["created_at"], reverse=True)
        return Response({"posts": posts[:100]})

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
