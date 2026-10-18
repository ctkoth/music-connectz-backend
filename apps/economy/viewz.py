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

from .models import (ItemRating, Message, Post, PostJoin, PostShare, Reaction, ScoreShare, SocialComment,
                     ViewSession)

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
        raw_ids = d.get("ids")
        # Anything but a list is junk, and `isdigit` accepts digits `int` refuses ("²"): both
        # were a 500 on an endpoint anybody, signed in or not, can call.
        raw_ids = raw_ids[:MAX_IDS_PER_BEAT] if isinstance(raw_ids, list) else []
        ids = [i for i in raw_ids if isinstance(i, int) and not isinstance(i, bool) and 0 < i < 2**31]
        ids += [int(i) for i in raw_ids if isinstance(i, str) and i.isascii() and i.isdigit() and int(i) < 2**31]
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


# ----------------------------------------------------------------- results
#
# "How did it do?" — for one post, and for the share links a member sent out. Two
# readers again: everybody gets the NUMBERS about their own post (nothing in a
# count names anybody), and StatZ also gets who — the same line the timeline
# already draws. Read live (the screen re-asks every BEAT seconds) and kept: it is
# derived from the sessions, so the past is exactly as true as now.
#
# What the words mean, said on the screen beside the numbers (`DEFINITIONS`),
# because "retention" with no definition is a number nobody can check:
#   stayed     — of the visits, how many lasted at least MIN_VIEW_SECONDS
#   came back  — of the people, how many visited on more than one separate stretch
# Neither is video-style retention (there is no timeline to drop off from); they
# are what a post can honestly show, and they are never blended into one score.

DEFINITIONS = {
    "views": f"Visits that lasted at least {MIN_VIEW_SECONDS} seconds — a page that merely loaded is not a view.",
    "stayed": f"Of all visits, the share that lasted {MIN_VIEW_SECONDS} seconds or more.",
    "came_back": "Of the people who visited, the share who came back after a gap of 30 minutes or more.",
    "actions": "What people who visited did to this post — rated, commented, liked, or messaged you afterwards.",
}


def _secs(r):
    return max(0, int((r.ended_at - r.started_at).total_seconds()))


def _viewer_key(r):
    return f"u{r.viewer_id}" if r.viewer_id else f"a{r.anon_id}"


def aggregate(rows, now=None):
    """The numbers about a list of ViewSession rows. Absent is None, never 0:
    a percentage of nobody is an empty measurement."""
    now = now or timezone.now()
    total = len(rows)
    counted = [r for r in rows if _secs(r) >= MIN_VIEW_SECONDS]
    people = {}
    for r in rows:
        people.setdefault(_viewer_key(r), []).append(r)
    members = sum(1 for k in people if k.startswith("u"))
    back = sum(1 for v in people.values() if len(v) > 1)
    return {
        "views": len(counted),
        "visits": total,
        "people": len(people), "members": members, "visitors": len(people) - members,
        "avg_seconds": round(sum(_secs(r) for r in counted) / len(counted)) if counted else None,
        "stayed_pct": round(100 * len(counted) / total) if total else None,
        "came_back_pct": round(100 * back / len(people)) if people else None,
        "live_now": sum(1 for r in rows if r.ended_at >= now - MAX_BEAT_GAP),
    }


def breakdown(rows, field, blank):
    """Visits and people by `field` (src or dev): where they came from, said in counts.
    An empty value is `blank` ("direct" / "unknown"), a real bucket rather than a
    dropped row — most visits arrive with no ?src= and a table that hid them would
    make the few tagged ones look like all of them."""
    seen = {}
    for r in rows:
        key = getattr(r, field) or blank
        b = seen.setdefault(key, {"visits": 0, "people": set()})
        b["visits"] += 1
        b["people"].add(_viewer_key(r))
    return sorted(({field: k, "visits": b["visits"], "people": len(b["people"])} for k, b in seen.items()),
                  key=lambda x: (-x["visits"], x[field]))


def _actions(post, rows):
    """What the people who visited did: {viewer_key: {...}} for MEMBERS (a visitor
    has no account to act with), and the totals."""
    item = f"post:{post.id}"
    first = {}
    for r in rows:
        if r.viewer_id and (r.viewer_id not in first or r.started_at < first[r.viewer_id]):
            first[r.viewer_id] = r.started_at
    ids = list(first)
    rated = dict(ItemRating.objects.filter(item_id=item, user_id__in=ids).values_list("user_id", "score"))
    liked = {u for u, v in Reaction.objects.filter(item_id=item, user_id__in=ids).values_list("user_id", "value") if v > 0}
    comments = {}
    for u in SocialComment.objects.filter(item_id=item, user_id__in=ids).values_list("user_id", flat=True):
        comments[u] = comments.get(u, 0) + 1
    messaged = {}
    for u, at in Message.objects.filter(sender_id__in=ids, recipient_id=post.author_id).values_list("sender_id", "created_at"):
        if at >= first[u]:
            messaged[u] = messaged.get(u, 0) + 1
    per = {u: {"rated": rated.get(u), "liked": u in liked, "commented": comments.get(u, 0),
               "messaged": messaged.get(u, 0)} for u in ids}
    totals = {"rated": len(rated), "liked": len(liked), "commented": sum(comments.values()),
              "messaged": sum(messaged.values()),
              "acted": len({u for u, a in per.items() if a["rated"] or a["liked"] or a["commented"] or a["messaged"]})}
    return per, totals


ACTION_LOG_MAX = 100
ACTION_LABELS = {"rating": "rated it", "comment": "commented", "like": "liked it", "share": "shared it",
                 "join": "joined it (members-only)", "message": "messaged you"}


def action_log(post, rows):
    """ActionZ: everything people DID from this post, newest first — a rating, a comment,
    a like, a share, a members-only join, a message sent after looking. `via_page` says
    whether that person also has a visit on the post's own page (they came and looked)
    or acted from the feed. Read from the tables the actions already live in; nothing
    here is stored twice, so the past is as true as now."""
    item = f"post:{post.id}"
    visited = {r.viewer_id: r.started_at for r in rows if r.viewer_id}
    ev = []
    for r in ItemRating.objects.filter(item_id=item).select_related("user").order_by("-id")[:ACTION_LOG_MAX]:
        ev.append({"type": "rating", "who": r.user.username, "at": r.created_at or r.updated_at,
                   "detail": f"{r.score}/10" + (f" — “{r.reason}”" if r.reason else ""), "uid": r.user_id})
    for c in SocialComment.objects.filter(item_id=item).select_related("user").order_by("-id")[:ACTION_LOG_MAX]:
        ev.append({"type": "comment", "who": c.user.username, "at": c.created_at,
                   "detail": c.body[:140], "uid": c.user_id})
    for x in Reaction.objects.filter(item_id=item, value__gt=0).select_related("user").order_by("-id")[:ACTION_LOG_MAX]:
        ev.append({"type": "like", "who": x.user.username, "at": x.updated_at, "detail": "", "uid": x.user_id})
    for sh in PostShare.objects.filter(post=post).select_related("user").order_by("-id")[:ACTION_LOG_MAX]:
        ev.append({"type": "share", "who": sh.user.username, "at": sh.shared_at, "detail": "", "uid": sh.user_id})
    for j in PostJoin.objects.filter(post=post, user__isnull=False).select_related("user").order_by("-id")[:ACTION_LOG_MAX]:
        ev.append({"type": "join", "who": j.user.username, "at": j.joined_at,
                   "detail": f"stayed {j.active_seconds}s", "uid": j.user_id})
    for m in Message.objects.filter(recipient_id=post.author_id, sender_id__in=list(visited)).select_related("sender").order_by("-id")[:ACTION_LOG_MAX]:
        if m.created_at >= visited[m.sender_id]:
            ev.append({"type": "message", "who": m.sender.username, "at": m.created_at, "detail": "", "uid": m.sender_id})
    ev = [e for e in ev if e["uid"] != post.author_id]          # your own taps on your own post are not "people"
    ev.sort(key=lambda e: e["at"], reverse=True)
    return [{"type": e["type"], "label": ACTION_LABELS[e["type"]], "who": e["who"], "at": e["at"].isoformat(),
             "detail": e["detail"], "via_page": e["uid"] in visited} for e in ev[:ACTION_LOG_MAX]]


def account_action_log(posts, author, limit=ACTION_LOG_MAX):
    """ActionZ across ALL of one member's posts: the newest actions, each naming the post it
    was on. One query per kind for the whole list (not per post): a member with forty posts must
    not cost two hundred queries on a screen that re-asks every fifteen seconds.

    Each kind is read newest-first and capped at `limit` — the log can only show that many, and
    loading every rating a popular post ever got to throw most away is the cost this avoids. The
    COUNTS are separate `count()` queries, never the length of the capped list: a total that
    silently stopped at 100 would be a made-up number. Your own taps on your own posts are not
    people and are excluded in the query. Messages are not here: a message is about a person, not
    a post."""
    ids = {p.id: p for p in posts}
    items = {f"post:{pid}": pid for pid in ids}
    sources = {
        "rating": ItemRating.objects.filter(item_id__in=items).exclude(user_id=author.id),
        "comment": SocialComment.objects.filter(item_id__in=items).exclude(user_id=author.id),
        "like": Reaction.objects.filter(item_id__in=items, value__gt=0).exclude(user_id=author.id),
        "share": PostShare.objects.filter(post_id__in=ids).exclude(user_id=author.id),
        "join": PostJoin.objects.filter(post_id__in=ids, user__isnull=False).exclude(user_id=author.id),
    }
    counts = {k: qs.count() for k, qs in sources.items()}
    counts = {k: v for k, v in counts.items() if v}
    ev = []
    if counts.get("rating"):
        for r in sources["rating"].select_related("user").order_by("-id")[:limit]:
            ev.append({"type": "rating", "who": r.user.username, "at": r.created_at or r.updated_at,
                       "post": items[r.item_id], "detail": f"{r.score}/10" + (f" — “{r.reason}”" if r.reason else "")})
    if counts.get("comment"):
        for c in sources["comment"].select_related("user").order_by("-id")[:limit]:
            ev.append({"type": "comment", "who": c.user.username, "at": c.created_at,
                       "post": items[c.item_id], "detail": c.body[:140]})
    if counts.get("like"):
        for x in sources["like"].select_related("user").order_by("-id")[:limit]:
            ev.append({"type": "like", "who": x.user.username, "at": x.updated_at,
                       "post": items[x.item_id], "detail": ""})
    if counts.get("share"):
        for sh in sources["share"].select_related("user").order_by("-id")[:limit]:
            ev.append({"type": "share", "who": sh.user.username, "at": sh.shared_at,
                       "post": sh.post_id, "detail": ""})
    if counts.get("join"):
        for j in sources["join"].select_related("user").order_by("-id")[:limit]:
            ev.append({"type": "join", "who": j.user.username, "at": j.joined_at,
                       "post": j.post_id, "detail": f"stayed {j.active_seconds}s"})
    ev.sort(key=lambda e: e["at"], reverse=True)
    log = [{"type": e["type"], "label": ACTION_LABELS[e["type"]], "who": e["who"], "at": e["at"].isoformat(),
            "detail": e["detail"], "post": e["post"], "post_title": ids[e["post"]].title or f"Post #{e['post']}"}
           for e in ev[:limit]]
    return log, counts


def post_results(post, user, now=None, days=14):
    from .statz_trial import has_statz
    now = now or timezone.now()
    rows = list(ViewSession.objects.filter(target=f"post:{post.id}").select_related("viewer")
                .order_by("started_at")[:5000])
    agg = aggregate(rows, now)
    per, totals = _actions(post, rows)
    agg["actions"] = totals
    # Where the visits came from and on what — counts, never names, so every tier sees
    # them. `src` is the share link's ?src= (instagram, tiktok…); "direct" is a visit
    # that carried none, which is not the same as "unknown" and is said as it is.
    agg["sources"] = breakdown(rows, "src", "direct")
    agg["devices"] = breakdown(rows, "dev", "unknown")
    # By day, newest last — the history. Days with nothing are rows too, so a gap
    # reads as a gap rather than a line that skips it.
    since = (now - timedelta(days=days - 1)).date()
    by_day = {since + timedelta(days=i): {"views": 0, "members": set(), "visitors": set()} for i in range(days)}
    for r in rows:
        d = timezone.localtime(r.started_at).date() if timezone.is_aware(r.started_at) else r.started_at.date()
        if d in by_day and _secs(r) >= MIN_VIEW_SECONDS:
            by_day[d]["views"] += 1
            by_day[d]["members" if r.viewer_id else "visitors"].add(_viewer_key(r))
    out = {"post": {"id": post.id, "title": post.title, "at": post.created_at.isoformat()},
           **agg, "definitions": DEFINITIONS, "as_of": now.isoformat(), "notice": NOTICE,
           "by_day": [{"day": d.isoformat(), "views": v["views"], "members": len(v["members"]),
                       "visitors": len(v["visitors"])} for d, v in sorted(by_day.items())]}
    if has_statz(user):
        out["action_log"] = action_log(post, rows)
    else:
        out["action_log"] = None
        out["action_log_locked"] = ("ActionZ — who rated, commented, liked, shared or messaged, by name and when — is a "
                                    "StatZ feature. The counts above are yours at every tier.")
    if not has_statz(user):
        out["viewers"] = None
        out["viewers_locked"] = "Who viewed — by name, with what each did — is a StatZ feature. The numbers above are yours at every tier."
        return out
    people = {}
    visitor_no = {}
    for r in rows:
        k = _viewer_key(r)
        if r.viewer_id:
            row = people.setdefault(k, {"viewer": r.viewer.username, "member": True, "sessions": 0, "seconds": 0,
                                        "first_at": r.started_at, "last_at": r.ended_at, "src": r.src, "dev": r.dev,
                                        "clips": [], **per.get(r.viewer_id, {})})
        else:
            n = visitor_no.setdefault(k, len(visitor_no) + 1)
            row = people.setdefault(k, {"viewer": f"Visitor {n}", "member": False, "sessions": 0, "seconds": 0,
                                        "first_at": r.started_at, "last_at": r.ended_at, "src": r.src, "dev": r.dev,
                                        "clips": []})
        row["sessions"] += 1
        # One clip per visit — when it started, when it ended and how long it was —
        # so a screen can lay each viewer out as a track on a clock, like ViewZ's
        # timeline does for everything. `seconds` is the same figure the totals use.
        if len(row["clips"]) < 50:
            row["clips"].append({"start": r.started_at.isoformat(), "end": r.ended_at.isoformat(),
                                 "seconds": _secs(r)})
        row["seconds"] += _secs(r)
        row["last_at"] = max(row["last_at"], r.ended_at)
        row["src"] = row["src"] or r.src
        row["dev"] = row["dev"] or r.dev
    viewers = sorted(people.values(), key=lambda v: -v["seconds"])[:100]
    for v in viewers:
        v["first_at"], v["last_at"] = v["first_at"].isoformat(), v["last_at"].isoformat()
        v["came_back"] = v["sessions"] > 1
    out["viewers"] = viewers
    # The clock the tracks are drawn on: from the post going up (or the first visit,
    # if it came earlier than the history kept) to now.
    start = min([post.created_at] + [r.started_at for r in rows])
    out["from"], out["to"] = start.isoformat(), now.isoformat()
    return out


class ViewPostResultsView(APIView):
    """GET /api/economy/views/post/<id>/ — how one of YOUR posts did, live and over time."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        post = Post.objects.filter(pk=pk, author=request.user).first()
        if not post:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(post_results(post, request.user))


def link_rows(user, limit=30):
    """The share links this member has sent out and how many times each was opened.
    `opens` is the public page's own counter (a crawler fetching the preview image
    is not an open); who opened a link is not recorded, so none is claimed."""
    out = []
    for r in ScoreShare.objects.filter(user=user).order_by("-created_at")[:limit]:
        p = r.payload or {}
        kind = "recap" if p.get("recap") else "win" if p.get("progress") else "take"
        out.append({"token": r.token, "url": f"/s/{r.token}", "app_key": r.app_key, "score": r.score,
                    "kind": kind, "genre": r.genre, "opens": r.views, "human": bool(p.get("human")),
                    "at": r.created_at.isoformat()})
    return out


class ViewMineView(APIView):
    """GET /api/economy/views/mine/ — every post of yours with its numbers, and every
    link you shared with its opens. The list screen; one post's detail is
    `views/post/<id>/`."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import Referral
        posts = list(Post.objects.filter(author=request.user).order_by("-created_at")[:40])
        by_target = {}
        # Only the columns `aggregate` and `breakdown` read, and no join to the viewer: this list
        # re-asks every 15 seconds and a popular account has tens of thousands of sessions.
        for r in (ViewSession.objects.filter(target__in=[f"post:{p.id}" for p in posts])
                  .only("target", "viewer_id", "anon_id", "started_at", "ended_at", "src", "dev")
                  .order_by("started_at")):
            by_target.setdefault(r.target, []).append(r)
        now = timezone.now()
        rows = []
        for p in posts:
            agg = aggregate(by_target.get(f"post:{p.id}", []), now)
            rows.append({"id": p.id, "title": p.title, "at": p.created_at.isoformat(),
                         "visibility": p.visibility, **agg})
        links = link_rows(request.user)
        from .statz_trial import has_statz
        log, counts = account_action_log(posts, request.user)
        every = [r for rs in by_target.values() for r in rs]
        named = has_statz(request.user)
        return Response({"posts": rows, "links": links,
                         # ActionZ across every post: counts for everybody, the named log for StatZ.
                         "action_counts": counts,
                         "action_log": log if named else None,
                         "action_log_locked": None if named else (
                             "ActionZ — who rated, commented, liked or shared, by name and when — is a StatZ feature. "
                             "The counts are yours at every tier."),
                         "sources": breakdown(every, "src", "direct"),
                         "devices": breakdown(every, "dev", "unknown"),
                         "links_opens": sum(l["opens"] for l in links),
                         "joined_from_invites": Referral.objects.filter(referrer=request.user).count(),
                         "definitions": DEFINITIONS, "as_of": now.isoformat(), "notice": NOTICE})
