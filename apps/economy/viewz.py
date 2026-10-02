"""ViewZ — time on pages, posts and profiles, as DAW tracks.

Every member's and visitor's time on a post, a profile or an app tab is a
`ViewSession`: started when it becomes visible, extended by one heartbeat
every BEAT seconds while it stays visible, closed by silence. A repeat visit
inside SESSION_GAP extends the same session, so a refresh is never a second
view, and an owner looking at their own thing is never counted at all.

Two readers:
  * everyone — the total view count under a post or profile: sessions by
    other people that lasted at least MIN_VIEW_SECONDS, nothing padded;
  * StatZ (the sample included) — a timeline where each viewer of YOUR posts
    and profile is a track and each session is a clip, like a DAW. Somebody
    without an account gets a track of their own too ("Visitor 3"), with the
    screen they used and the share link that brought them — never a name, an
    address or anything that could find them. The
    platform owner can also read every tab ("scope=all").

Who viewed is shown by name to the StatZ owner of what was viewed. That is
told to viewers on the screens that count them, because a member who didn't
know they were seen was never asked.
"""
import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models import Count, F
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Post, ViewSession

User = get_user_model()

BEAT = 15                       # seconds between heartbeats
SESSION_GAP = timedelta(minutes=30)
MAX_BEAT_GAP = timedelta(seconds=BEAT * 3)   # a beat after this long is a new stretch
MAX_IDS_PER_BEAT = 20
RANGES = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7)}
TARGET = re.compile(r"^(post:\d{1,12}|profile:[A-Za-z0-9_]{1,40}|tab:[a-z0-9_]{1,40})$")
MIN_VIEW_SECONDS = 5          # a view is somebody who stayed, not a page that loaded
ANON_STARTS_PER_HOUR = 120    # per address — loose, because a carrier's NAT is many phones
SRC = re.compile(r"^[a-z0-9_]{1,24}$")
DEVICES = ("phone", "tablet", "desktop")
NOTICE = "Views are counted, and StatZ creators can see who viewed their posts and profile."


def owner_of(target):
    kind, _, key = target.partition(":")
    if kind == "post":
        p = Post.objects.filter(pk=int(key)).only("author_id").first()
        return p.author_id if p else None
    if kind == "profile":
        u = User.objects.filter(username__iexact=key).only("id").first()
        return u.id if u else None
    return None


def _viewer(request):
    u = request.user
    return u if u and u.is_authenticated else None


class ViewStartView(APIView):
    """POST {target, anon_id?} → {id}. Reopens a recent session instead of
    making a new one, and counts nothing for an owner on their own thing."""

    permission_classes = [AllowAny]

    def post(self, request):
        d = request.data or {}
        target = str(d.get("target", "")).strip()
        if not TARGET.match(target):
            return Response({"detail": "unknown target"}, status=status.HTTP_400_BAD_REQUEST)
        viewer = _viewer(request)
        anon = "" if viewer else str(d.get("anon_id", ""))[:64]
        if not viewer and not anon:
            return Response({"id": None, "counted": False})
        if not viewer:
            from .clientip import client_ip
            key = f"viewz:anon:{client_ip(request)}:{timezone.now():%Y%m%d%H}"
            n = cache.get_or_set(key, 0, 3600)
            if n >= ANON_STARTS_PER_HOUR:
                return Response({"id": None, "counted": False})
            cache.incr(key)
        owner_id = owner_of(target)
        if target.startswith(("post:", "profile:")) and owner_id is None:
            return Response({"detail": "unknown target"}, status=status.HTTP_404_NOT_FOUND)
        if viewer and owner_id == viewer.id:
            return Response({"id": None, "counted": False})
        src = str(d.get("src", "")).lower()
        src = src if SRC.match(src) else ""
        dev = str(d.get("dev", "")) if d.get("dev") in DEVICES else ""
        now = timezone.now()
        who = {"viewer": viewer} if viewer else {"viewer__isnull": True, "anon_id": anon}
        s = (ViewSession.objects.filter(target=target, ended_at__gte=now - SESSION_GAP, **who)
             .order_by("-ended_at").first())
        if s:
            s.ended_at = now
            s.save(update_fields=["ended_at"])
        else:
            s = ViewSession.objects.create(viewer=viewer, anon_id=anon, target=target,
                                           owner_id=owner_id, ended_at=now, src=src, dev=dev)
        return Response({"id": s.id, "counted": True, "beat": BEAT})


class ViewBeatView(APIView):
    """POST {ids, anon_id?} — still looking at these. Only your own sessions
    move, and a beat after a long silence doesn't stretch the gap into time
    on the page."""

    permission_classes = [AllowAny]

    def post(self, request):
        d = request.data or {}
        ids = [int(i) for i in (d.get("ids") or [])[:MAX_IDS_PER_BEAT] if str(i).isdigit()]
        viewer = _viewer(request)
        qs = ViewSession.objects.filter(pk__in=ids)
        qs = qs.filter(viewer=viewer) if viewer else qs.filter(viewer__isnull=True,
                                                                anon_id=str(d.get("anon_id", ""))[:64] or "-")
        now = timezone.now()
        moved = qs.filter(ended_at__gte=now - MAX_BEAT_GAP).update(ended_at=now)
        return Response({"moved": moved})


class ViewCountsView(APIView):
    """GET ?t=post:1&t=profile:x — total views for each, for anybody to read."""

    permission_classes = [AllowAny]

    def get(self, request):
        targets = [t for t in request.query_params.getlist("t")[:100] if TARGET.match(t)]
        rows = (ViewSession.objects.filter(target__in=targets,
                                           ended_at__gte=F("started_at") + timedelta(seconds=MIN_VIEW_SECONDS))
                .values("target").annotate(n=Count("id")))
        counts = {t: 0 for t in targets}
        counts.update({r["target"]: r["n"] for r in rows})
        return Response({"counts": counts, "notice": NOTICE})


def _label(target, titles):
    kind, _, key = target.partition(":")
    if kind == "post":
        return titles.get(int(key)) or f"Post #{key}"
    if kind == "profile":
        return f"@{key}'s profile"
    return key.title() if key else target


class ViewTimelineView(APIView):
    """GET ?range=1h|24h|7d&scope=mine|all — the DAW. StatZ (or the sample)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .statz_trial import has_statz
        from .views import is_owner
        if not has_statz(request.user):
            return Response({"detail": "The ViewZ timeline is a StatZ feature.", "tier": "statz"},
                            status=status.HTTP_403_FORBIDDEN)
        span = RANGES.get(request.query_params.get("range", "24h"), RANGES["24h"])
        now = timezone.now()
        since = now - span
        scope_all = request.query_params.get("scope") == "all" and is_owner(request.user)
        qs = ViewSession.objects.filter(ended_at__gte=since)
        if not scope_all:
            qs = qs.filter(owner=request.user)
        rows = list(qs.select_related("viewer").order_by("started_at")[:3000])
        post_ids = {int(r.target[5:]) for r in rows if r.target.startswith("post:")}
        titles = dict(Post.objects.filter(pk__in=post_ids).values_list("id", "title"))
        lanes = {}
        visitor_no = {}
        for r in rows:
            if r.viewer_id:
                key = r.viewer.username
                lane = lanes.setdefault(key, {"viewer": key, "member": True, "seconds": 0, "clips": []})
            else:
                # Somebody without an account: their own track, numbered by
                # first appearance in this window. The browser's random id
                # stays on the server — the label is all the owner sees.
                key = f"anon:{r.anon_id}"
                n = visitor_no.setdefault(key, len(visitor_no) + 1)
                lane = lanes.setdefault(key, {"viewer": f"Visitor {n}", "member": False, "seconds": 0,
                                              "clips": [], "dev": r.dev, "src": r.src})
                lane["dev"] = lane["dev"] or r.dev
                lane["src"] = lane["src"] or r.src
            start = max(r.started_at, since)
            secs = max(1, int((r.ended_at - start).total_seconds()))
            lane["seconds"] += secs
            lane["clips"].append({"target": r.target, "label": _label(r.target, titles),
                                  "start": start.isoformat(), "end": r.ended_at.isoformat(), "seconds": secs})
        ordered = sorted(lanes.values(), key=lambda l: -l["seconds"])
        return Response({
            "range": [k for k, v in RANGES.items() if v == span][0],
            "from": since.isoformat(), "to": now.isoformat(),
            "scope": "all" if scope_all else "mine",
            "can_scope_all": is_owner(request.user),
            "lanes": ordered[:60],
            "total_views": len(rows),
            "members": sum(1 for l in ordered if l["member"]),
            "visitors": sum(1 for l in ordered if not l["member"]),
            "total_seconds": sum(l["seconds"] for l in ordered),
            "notice": NOTICE,
        })
