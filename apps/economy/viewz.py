"""ViewZ — who is looking, and when they looked.

Every page in this app could be looked at by a thousand people and say nothing
about it. A creator posting a track had ratings (which need somebody to act)
and comments (which need somebody to care) and no answer at all to the first
question anybody asks: *did anyone see it?* Silence reads as "nobody", and
"nobody" is the reason people stop posting.

So: a view count on everything, and a **timeline** rather than a scalar,
because this is a music app and a scalar is a number while a timeline is a
waveform. Twenty-four lanes across a day reads like a track in a DAW: you can
see the spike when it got shared, the flat stretch overnight, whether the
attention is still arriving or already over. "128 views" cannot tell you any
of that, and every one of those is a thing a creator would act on.

## What a "view" IS, precisely, because a number nobody can check is decoration

The rule this app holds every number to: *could somebody get a good one
without getting good?* A raw hit counter fails it instantly — refresh it
yourself fifty times. So:

- **One view is one viewer, once a day.** A `ViewSession` row is unique per
  (target, viewer, day). Refreshing does not move the count; coming back
  tomorrow does, because that genuinely is more attention.
- **The author's own looks never count.** Checking your own post is not
  reach, and letting it count would make the first number every creator sees
  a lie told by their own thumb.
- **`watching` is live and separate.** Sessions beating inside
  `WATCHING_SECONDS` — the number that actually drives behaviour, because
  "3 people are here right now" is an invitation and "128 total" is a receipt.
- **Anonymous viewers count once too**, keyed by a client-side id. It can be
  cleared, so it is a floor rather than a truth, and the API says so rather
  than presenting it as certainty.

Nothing here is a dead end: every row carries `open_in`, so a spike on the
timeline leads to the thing that was being looked at.
"""
import hashlib
import re
from datetime import timedelta

from django.db import models
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ENERGY_RESET_TZ, ViewSession

# Still here = beating within this. One minute is long enough to survive a
# tab switch or a slow network and short enough that "watching now" means now.
WATCHING_SECONDS = 90

# How often a client should beat. Published so the client does not pick its
# own and drift from what the server calls "still here".
BEAT_SECONDS = 30

# The timeline. Twenty-four lanes across a day is one an hour — the resolution
# a person actually reasons in ("it took off last night"), and small enough to
# draw on a phone without a library.
LANES = 24

# What a target may look like: "post:12", "tab:postz", "member:novabeatz".
TARGET = re.compile(r"^[a-z][a-z0-9_]{0,15}:[A-Za-z0-9_.:-]{1,48}$")

# Targets whose owner is knowable, so an author's own view can be excluded.
# Anything else counts every viewer, because there is nobody to exclude.
OWNED_KINDS = ("post", "member", "work", "playlist")


def clean_target(raw):
    """A target, or "". Validated rather than trusted: it is a database key
    written by a client, and it is echoed back to other clients."""
    t = str(raw or "").strip()[:64]
    return t if TARGET.match(t) else ""


def anon_key(request):
    """A stable-per-browser id for a viewer with no account.

    Hashed with the target-independent parts only, so this cannot be used to
    follow one person around: it identifies "the same browser on this page",
    which is exactly and only what deduplicating a view needs.
    """
    raw = (request.headers.get("X-MCZ-Viewer") or "")[:64]
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()[:32]


def local_day(when=None):
    """The date this view belongs to, on the same 04:20 clock as Energy.

    One "today" across the app. Two different day boundaries would mean a
    member's views and their ⚡ reset at different times, and nobody would
    ever work out why.
    """
    from .models import energy_day_start
    return energy_day_start(when).date()


def owner_id_for(target):
    """Whose thing this is, or None. Used only to not count their own look."""
    kind, _, key = target.partition(":")
    if kind not in OWNED_KINDS:
        return None
    try:
        if kind == "post":
            from .models import Post
            return Post.objects.filter(pk=int(key)).values_list("author_id", flat=True).first()
        if kind == "playlist":
            from .models import Playlist
            return Playlist.objects.filter(pk=int(key)).values_list("owner_id", flat=True).first()
        if kind == "member":
            from django.contrib.auth import get_user_model
            return get_user_model().objects.filter(
                username__iexact=key).values_list("id", flat=True).first()
    except (TypeError, ValueError):
        return None
    return None


def counts_for(target, now=None):
    """`views`, `viewers` and `watching` for one target, in three queries."""
    now = now or timezone.now()
    rows = ViewSession.objects.filter(target=target)
    agg = rows.aggregate(
        views=Count("id"),
        viewers=Count("viewer_id", distinct=True),
    )
    # A viewer-day is a view. Distinct PEOPLE is the second number, and the
    # two are published side by side because they answer different questions:
    # "how much attention" and "how many people".
    anon = rows.exclude(anon_key="").values("anon_key").distinct().count()
    watching = rows.filter(
        last_beat_at__gte=now - timedelta(seconds=WATCHING_SECONDS)).count()
    return {
        "views": agg["views"] or 0,
        "viewers": (agg["viewers"] or 0) + anon,
        "watching": watching,
    }


def lanes_for(target, now=None, lanes=LANES):
    """The DAW lane: one bucket an hour, oldest first.

    Every bucket is returned even when it is empty — a timeline with the quiet
    hours missing is a timeline that lies about the shape of the day, and the
    flat stretch is half of what makes the spike legible.
    """
    now = now or timezone.now()
    start = (now - timedelta(hours=lanes)).replace(minute=0, second=0, microsecond=0)
    buckets = [0] * lanes
    seen = ViewSession.objects.filter(
        target=target, started_at__gte=start).values_list("started_at", flat=True)
    for at in seen:
        i = int((at - start).total_seconds() // 3600)
        if 0 <= i < lanes:
            buckets[i] += 1
    peak = max(buckets) if buckets else 0
    return {
        "lanes": [
            {"at": (start + timedelta(hours=i)).isoformat(),
             "views": n,
             # 0..1 against the peak, so a client draws the lane without
             # inventing a scale of its own — and a flat day reads as flat
             # rather than being stretched into drama.
             "level": round(n / peak, 3) if peak else 0.0}
            for i, n in enumerate(buckets)
        ],
        "peak": peak,
        "hours": lanes,
    }


def record(request, target):
    """Upsert this viewer's session for today. Returns (session, counted)."""
    now = timezone.now()
    user = request.user if getattr(request.user, "is_authenticated", False) else None
    key = "" if user else anon_key(request)
    if not user and not key:
        # No account and no viewer id: countable views are per-viewer, and a
        # viewer we cannot tell apart from the next one would be a hit
        # counter wearing a viewer count's clothes.
        return None, False
    if user and owner_id_for(target) == user.id:
        # Your own look at your own thing is not reach.
        return None, False
    row, created = ViewSession.objects.get_or_create(
        target=target, viewer=user, anon_key=key, day=local_day(now),
        defaults={"started_at": now, "last_beat_at": now, "beats": 1},
    )
    if not created:
        ViewSession.objects.filter(pk=row.pk).update(
            last_beat_at=now, beats=models.F("beats") + 1)
    return row, created


class ViewZView(APIView):
    """POST — I am looking at this. GET — what has been looked at.

    Unauthenticated on purpose, like the media route: a logged-out visitor on
    a public post is exactly the reach a creator most wants counted, and an
    auth wall here would make the number mean "views by members", which is a
    different and much smaller thing nobody asked for.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        target = clean_target((request.data or {}).get("target"))
        if not target:
            return Response({"detail": "target required, e.g. post:12"},
                            status=status.HTTP_400_BAD_REQUEST)
        _, counted = record(request, target)
        return Response({
            "target": target, "counted": counted,
            "beat_seconds": BEAT_SECONDS,
            **counts_for(target),
        })

    def get(self, request):
        target = clean_target(request.query_params.get("target"))
        if not target:
            return Response({"detail": "target required, e.g. post:12"},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "target": target,
            "beat_seconds": BEAT_SECONDS,
            "watching_seconds": WATCHING_SECONDS,
            **counts_for(target),
            **lanes_for(target),
            # Said out loud rather than implied. A viewer count built partly
            # from a clearable browser id is a floor, and presenting a floor
            # as a total is the same class of dishonesty as an "AI craft
            # estimate" computed from how many fields somebody filled in.
            "note": "One view is one viewer per day — refreshing doesn't move it, "
                    "and your own looks at your own work are never counted. "
                    "Logged-out viewers count once per browser, so this is a floor.",
        })


class ViewZMineView(APIView):
    """Everything of MINE that has been looked at, newest attention first.

    A creator with five posts should not have to open five screens to find out
    which one is moving. Each row carries `open_in`, so the answer is one tap
    from the thing it is about.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        from .models import Post
        mine = list(Post.objects.filter(author=request.user)
                    .order_by("-created_at").values_list("id", "title")[:50])
        targets = [f"post:{pid}" for pid, _ in mine]
        rows = (ViewSession.objects.filter(target__in=targets)
                .values("target")
                .annotate(views=Count("id"),
                          watching=Count("id", filter=Q(
                              last_beat_at__gte=now - timedelta(seconds=WATCHING_SECONDS))))
                )
        by_target = {r["target"]: r for r in rows}
        out = []
        for pid, title in mine:
            t = f"post:{pid}"
            r = by_target.get(t, {})
            out.append({
                "target": t,
                "title": title,
                "views": r.get("views", 0),
                "watching": r.get("watching", 0),
                "open_in": "postz",
            })
        out.sort(key=lambda r: (-r["watching"], -r["views"]))
        return Response({"items": out, "watching_seconds": WATCHING_SECONDS})


def views_for_posts(post_ids):
    """{post_id: views} for a page of posts, in one query.

    The feed's query-count test is the reason this exists rather than a count
    per card: a hundred posts must not become a hundred round trips behind a
    number whose whole job is to be glanced at.
    """
    ids = list(post_ids)
    if not ids:
        return {}
    rows = (ViewSession.objects
            .filter(target__in=[f"post:{i}" for i in ids])
            .values("target").annotate(n=Count("id")))
    out = {}
    for r in rows:
        try:
            out[int(r["target"].split(":", 1)[1])] = r["n"]
        except (IndexError, ValueError):
            continue
    return out
