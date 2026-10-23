"""Share a stats snapshot as a post: a member's ViewZ results for one of their posts,
or (owner only) FunnelZ. Both are a date range the sharer picks and an audience they
pick, and both become an ordinary PostZ post through `postz.create_post` — so they get
likes, dislikes, ratings, comments, shares and the other-app doors, the same daily cap,
the same price and the same visibility rules as anything else posted.

The text is written HERE from the server's own numbers, never from the request: a
snapshot is a claim, and a claim a client could type is not one. GET returns exactly
what POST would publish, so the preview is the post.

Never in a snapshot: who viewed (ViewZ names are StatZ's and stay off a public card),
and — unless the owner ticks it — who joined (genders and ages are members' facts).
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Post, ViewSession

RANGES = (1, 7, 14, 30, 90)


def clean_days(v, default=7):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return n if n in RANGES else default


def _span(days):
    return "today" if days == 1 else f"the last {days} days"


def _pct(x):
    return "—" if x is None else f"{x:g}%"


def views_snapshot(post, days, now=None):
    from .viewz import aggregate, breakdown
    now = now or timezone.now()
    since = now - timedelta(days=days)
    rows = list(ViewSession.objects.filter(target=f"post:{post.id}", started_at__gte=since)
                .order_by("started_at")[:5000])
    agg = aggregate(rows, now)
    src = [s for s in breakdown(rows, "src", "direct") if s.get("visits")][:3]
    lines = [f"📊 “{post.title}” — {_span(days)} on Music ConnectZ",
             f"👀 {agg['views']} views from {agg['people']} people",
             f"⏱️ stayed: {_pct(agg['stayed_pct'])} · came back: {_pct(agg['came_back_pct'])}"]
    if src:
        lines.append("📍 from " + ", ".join(f"{s['src']} {s['visits']}" for s in src))
    return {"title": f"{post.title[:120]} — {_span(days)}", "text": "\n".join(lines),
            "numbers": {k: agg.get(k) for k in ("views", "people", "stayed_pct", "came_back_pct")},
            "days": days}


def funnel_snapshot(days, with_members=False):
    from .views import FunnelSummaryView
    d = FunnelSummaryView().summary(days)
    lines = [f"🧭 Music ConnectZ funnel — {_span(days)}"]
    for h in d.get("headline") or []:
        lines.append(f"• {h['label']}: {h['to']} of {h['from']} ({_pct(h['pct'])})")
    if with_members:
        m = d.get("members") or {}
        g = ", ".join(f"{x['gender']} {x['members']}" for x in m.get("genders", []))
        a = ", ".join(f"{x['band']} {x['members']}" for x in m.get("ages", []))
        lines.append(f"👥 {m.get('total', 0)} members — {g}" + (f" · ages {a}" if a else ""))
    return {"title": f"FunnelZ — {_span(days)}", "text": "\n".join(lines), "days": days}


def _publish(request, snap, extra=None):
    from .postz import _post_dict, create_post
    vis = str(request.data.get("visibility") or "public").lower()
    body = {"title": snap["title"], "description": snap["text"], "visibility": vis,
            "gates": request.data.get("gates") if vis == "restricted" else None,
            **(extra or {})}
    post, info, error = create_post(request.user, body)
    if error:
        return Response(error[0], status=error[1])
    return Response({"post": _post_dict(post, request), **info, "snapshot": snap},
                    status=status.HTTP_201_CREATED)


class ViewShareView(APIView):
    """GET/POST /api/economy/views/post/<id>/share/?days= — the member's own post only."""
    permission_classes = [IsAuthenticated]

    def _post(self, request, pk):
        return Post.objects.filter(pk=pk, author=request.user).first()

    def get(self, request, pk):
        post = self._post(request, pk)
        if not post:
            return Response({"detail": "Not your post."}, status=status.HTTP_404_NOT_FOUND)
        return Response({**views_snapshot(post, clean_days(request.query_params.get("days"))),
                         "ranges": RANGES})

    def post(self, request, pk):
        post = self._post(request, pk)
        if not post:
            return Response({"detail": "Not your post."}, status=status.HTTP_404_NOT_FOUND)
        return _publish(request, views_snapshot(post, clean_days(request.data.get("days"))))


class FunnelShareView(APIView):
    """GET/POST /api/economy/funnel/share/?days=&members= — the platform owner only."""
    permission_classes = [IsAuthenticated]

    def _refuse(self, request):
        from .views import ensure_owner, is_owner
        ensure_owner(request.user)
        if not is_owner(request.user):
            return Response({"detail": "Only the platform owner shares FunnelZ."},
                            status=status.HTTP_403_FORBIDDEN)
        return None

    def get(self, request):
        no = self._refuse(request)
        if no:
            return no
        return Response({**funnel_snapshot(clean_days(request.query_params.get("days")),
                                           request.query_params.get("members") == "1"),
                         "ranges": RANGES})

    def post(self, request):
        no = self._refuse(request)
        if no:
            return no
        return _publish(request, funnel_snapshot(clean_days(request.data.get("days")),
                                                 bool(request.data.get("members"))))
