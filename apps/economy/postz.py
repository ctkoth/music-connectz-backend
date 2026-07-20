"""PostZ — cross-user posts with visibility + restricted-join SpinAZ rewards.

Posting costs energy equal to the combined price of the skills used (in cents).
Restricted posts reward the author 300 SpinAZ per valid join from a distinct,
non-author visitor.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from datetime import timedelta

from django.db.models import Case, IntegerField, Sum, When
from django.utils import timezone

from .models import (
    Post,
    PostJoin,
    PostShare,
    Reaction,
    ItemRating,
    RESTRICTED_JOIN_REWARD_SPINAZ,
    SHARE_REWARD_ENERGY,
    SHARE_MIN_ACTIVE_SECONDS,
    award_spinaz,
    can_view_post,
    item_rating_median,
    notify,
    record_submission,
    submission_cap_for,
    submissions_used_today,
    wallet_for,
)

# Reach engine: likes/dislikes rank the feed (they never touch price — that's
# ratings' job). Heavy dislike ratio downranks + flags for moderation.
HIDE_FLAG_MIN_DOWN = 5   # need at least this many dislikes to consider hiding
HIDE_FLAG_RATIO = 2.0    # ...and dislikes must exceed likes by this factor

# Restricted-join reward anti-fraud. A reward requires a real, engaged visitor:
# a distinct authenticated user + IP who was active >= N seconds, and caps how
# much a post/author can mint per day so rotating IPs / accounts can't farm it.
JOIN_MIN_ACTIVE_SECONDS = 5
JOIN_REWARD_DAILY_CAP_PER_POST = 100
JOIN_REWARD_DAILY_CAP_PER_AUTHOR = 500


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
        "media_url": p.media_url,
        "is_album": p.is_album,
        "items": p.items or [],
        "score": p.score or {},
        "visibility": p.visibility,
        "skill_cost_cents": p.skill_cost_cents,
        "joins": p.joins.count() if p.visibility == "restricted" else 0,
        "shares": p.shares.count(),
        "up": up, "down": down, "vibe": vibe, "flagged": flagged,
        "rating": item_rating_median(f"post:{p.id}"),
        "created_at": p.created_at.isoformat(),
    }


class SubmissionsView(APIView):
    """How many scored/creator submissions the member has left today."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        cap = submission_cap_for(request.user)
        used = submissions_used_today(request.user)
        return Response({"used": used, "cap": cap, "remaining": max(0, cap - used)})


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
        media_url = str(d.get("media_url", "")).strip()[:500]
        media_type = str(d.get("media_type", "")).strip()[:24]
        score = d.get("score") if isinstance(d.get("score"), dict) else {}
        # Album: a list of media items [{url, type, title, lyrics}]. Cap the count
        # and sanitize each entry so the payload can't balloon.
        raw_items = d.get("items") if isinstance(d.get("items"), list) else []
        items = []
        for it in raw_items[:50]:
            if not isinstance(it, dict):
                continue
            items.append({
                "url": str(it.get("url", ""))[:500],
                "type": str(it.get("type", ""))[:24],
                "title": str(it.get("title", ""))[:160],
                "lyrics": str(it.get("lyrics", ""))[:8000],
            })
        is_album = bool(d.get("is_album")) or len(items) > 1
        # A scored/recorded take (score payload or media) counts against the tier's
        # daily submission cap (Free 5 · Premium 15 · StatZ 50).
        is_submission = bool(score) or bool(media_url) or bool(items)
        if is_submission:
            cap = submission_cap_for(request.user)
            used = submissions_used_today(request.user)
            if used >= cap:
                return Response(
                    {"detail": f"Daily submission limit reached ({used}/{cap}). Upgrade for more.",
                     "used": used, "cap": cap},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
        # Posting costs energy = combined skill price (cents). Deduct what's there.
        w = wallet_for(request.user)
        charged = min(cost, max(0, w.energy))
        if charged:
            w.energy -= charged
            w.save(update_fields=["energy", "updated_at"])
        p = Post.objects.create(
            author=request.user, title=title,
            description=str(d.get("description", ""))[:4000],
            links=d.get("links") or [], media_type=media_type, media_url=media_url,
            is_album=is_album, items=items,
            score=score, visibility=vis, skill_cost_cents=cost,
        )
        if is_submission:
            record_submission(request.user)
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
        if not created:
            join.active_seconds = max(join.active_seconds, active)
            if join.user_id is None:
                join.user = request.user
            join.save(update_fields=["active_seconds", "user"])

        rewarded = self._maybe_reward(p, join, request.user)
        return Response({
            "joined": True, "rewarded": rewarded,
            "reward_spinaz": RESTRICTED_JOIN_REWARD_SPINAZ if rewarded else 0,
            "joins": p.joins.count(),
        })

    def _maybe_reward(self, p, join, user):
        """Pay the author once for a genuine, engaged, non-author visitor —
        subject to per-post and per-author daily caps."""
        if join.rewarded or p.author_id == user.id:
            return False
        if join.active_seconds < JOIN_MIN_ACTIVE_SECONDS:
            return False  # bounce / bot — must show real engagement first
        # One reward per distinct user per post (defeats IP rotation).
        if PostJoin.objects.filter(post=p, user=user, rewarded=True).exclude(pk=join.pk).exists():
            return False
        day_ago = timezone.now() - timedelta(hours=24)
        if PostJoin.objects.filter(post=p, rewarded=True, joined_at__gte=day_ago).count() >= JOIN_REWARD_DAILY_CAP_PER_POST:
            return False
        if PostJoin.objects.filter(post__author=p.author, rewarded=True, joined_at__gte=day_ago).count() >= JOIN_REWARD_DAILY_CAP_PER_AUTHOR:
            return False
        award_spinaz(p.author, RESTRICTED_JOIN_REWARD_SPINAZ, note=f"Restricted join on '{p.title}'")
        join.rewarded = True
        join.save(update_fields=["rewarded"])
        notify(p.author, "join", f"@{user.username} joined '{p.title}' — you earned {RESTRICTED_JOIN_REWARD_SPINAZ} SpinAZ 🛑", actor=user, item_id=f"post:{p.id}")
        return True


# One sharer can't farm shares by rotating IPs/accounts on the same post.
SHARE_REWARD_DAILY_CAP = 20  # max share rewards a single user can earn per day


class PostShareView(APIView):
    """Share another member's post. First genuine share (>= 30s dwell) of a post
    you don't own grants the sharer +5⚡, once per user+post."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        p = Post.objects.filter(pk=pk).select_related("author").first()
        if not p:
            return Response({"detail": "post not found"}, status=status.HTTP_404_NOT_FOUND)
        if not can_view_post(p, request.user):
            return Response({"detail": "you can't view this post"}, status=status.HTTP_403_FORBIDDEN)
        active = max(0, int(request.data.get("active_seconds") or 0))
        share, created = PostShare.objects.get_or_create(
            post=p, user=request.user, defaults={"ip": _client_ip(request), "active_seconds": active}
        )
        if not created:
            share.active_seconds = max(share.active_seconds, active)
            share.save(update_fields=["active_seconds"])

        rewarded = self._maybe_reward(p, share, request.user)
        w = wallet_for(request.user)
        return Response({
            "shared": True, "rewarded": rewarded,
            "reward_energy": SHARE_REWARD_ENERGY if rewarded else 0,
            "energy": w.energy,
            "shares": p.shares.count(),
        })

    def _maybe_reward(self, p, share, user):
        """+5⚡ once per user+post for sharing someone else's post, gated by a
        genuine dwell and a per-user daily cap."""
        if share.rewarded or p.author_id == user.id:
            return False
        if share.active_seconds < SHARE_MIN_ACTIVE_SECONDS:
            return False  # must have genuinely viewed it first
        day_ago = timezone.now() - timedelta(hours=24)
        if PostShare.objects.filter(user=user, rewarded=True, shared_at__gte=day_ago).count() >= SHARE_REWARD_DAILY_CAP:
            return False
        w = wallet_for(user)
        w.energy = (w.energy or 0) + SHARE_REWARD_ENERGY
        w.save(update_fields=["energy", "updated_at"])
        share.rewarded = True
        share.save(update_fields=["rewarded"])
        notify(p.author, "like", f"@{user.username} shared your post '{p.title}' 🔁", actor=user, item_id=f"post:{p.id}")
        return True
