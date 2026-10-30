"""SuperfanZ 🫶 — an artist's top fans, counted from what they actually did.

Badges told the room who is good; nothing told an artist who is THEIRS. A
superfan is the person who keeps coming back to one artist's work, and the only
honest way to know that is to count what they did with it — never what they
said about themselves.

WHAT COUNTS, inside `WINDOW_DAYS` on the artist's own posts:

    a play heard to the end    1   (ListenProgress.finished — clamped to the
                                    wall clock, so it costs real time)
    a rating                   2   (needs the listen the rating door already asks)
    a comment                  2
    a share                    3   (taking the work to somebody else)

`MIN_POINTS` before anybody is a superfan at all — one rating is a visit, not
devotion — and the top `TOP` are the artist's SuperfanZ.

WHY IT PAYS NOTHING. A 🍥 or ⚡ for being somebody's top fan would make the
list worth faking: a second account rating your own work would be a superfan
for money. With no payout a fake superfan buys nothing but a 🫶 beside a name
the artist can see is their own other account. The perk is attention, which is
what a fan wants from an artist anyway: **a superfan's comments pin to the top
of that artist's posts** (`social.SocialView._payload` reads `ranked`).

WHAT A LIST MAY SHOW, and to whom:
- **A fan can leave every list.** `superfan` is a VisibilitieZ field, members by
  default; set to private, they are counted for nobody and shown nowhere.
- **The age wall holds.** Member search keeps adults and minors apart, and a
  list of names is discovery, so a viewer only sees fans in their own age group.
- **Blocks hold** in both directions between artist and fan.
- **It is a count of acts, never a rating of a person.** The number beside a
  fan is how much they did, and the screen says so.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

WINDOW_DAYS = 30
TOP = 3
MIN_POINTS = 5
POINTS = {"listen": 1, "rate": 2, "comment": 2, "share": 3}
EMOJI = "🫶"
NAME = "SuperfanZ"
CACHE_SECONDS = 600
RULE = (f"{NAME} {EMOJI} are an artist's top {TOP} fans over the last {WINDOW_DAYS} days, counted from what they did "
        f"with that artist's posts: a play heard to the end is {POINTS['listen']}, a rating {POINTS['rate']}, a comment "
        f"{POINTS['comment']}, a share {POINTS['share']}. It takes {MIN_POINTS} to count. It pays nothing — a superfan's "
        "comments pin to the top of that artist's posts.")


def _points(artist_id):
    """{fan_id: {"points": n, "listen": n, "rate": n, "comment": n, "share": n}} for one
    artist, before anybody's visibility is applied. Five queries, cached."""
    key = f"superfanz:{artist_id}"
    got = cache.get(key)
    if got is not None:
        return got
    from .models import ItemRating, ListenProgress, Post, PostShare, SocialComment
    since = timezone.now() - timedelta(days=WINDOW_DAYS)
    ids = list(Post.objects.filter(author_id=artist_id).values_list("id", flat=True))
    keys = [f"post:{i}" for i in ids]
    out = {}

    def add(uid, kind):
        if not uid or uid == artist_id:
            return
        row = out.setdefault(uid, {"points": 0, "listen": 0, "rate": 0, "comment": 0, "share": 0})
        row[kind] += 1
        row["points"] += POINTS[kind]

    if ids:
        for uid in ListenProgress.objects.filter(item_id__in=keys, finished=True,
                                                 updated_at__gte=since).values_list("user_id", flat=True):
            add(uid, "listen")
        for uid in ItemRating.objects.filter(item_id__in=keys, created_at__gte=since).values_list("user_id", flat=True):
            add(uid, "rate")
        for uid in SocialComment.objects.filter(item_id__in=keys, created_at__gte=since).values_list("user_id", flat=True):
            add(uid, "comment")
        for uid in PostShare.objects.filter(post_id__in=ids, shared_at__gte=since).values_list("user_id", flat=True):
            add(uid, "share")
    cache.set(key, out, CACHE_SECONDS)
    return out


def ranked(artist_id, viewer):
    """The artist's fans as `viewer` may see them, best first, each
    {username, points, rank, ...breakdown}. Only fans who reached MIN_POINTS,
    chose to be listed for this viewer, share the viewer's age group and are not
    blocked either way with the artist."""
    from .models import Profile, blocked_user_ids, profile_for, profile_is_minor
    from .visibility import can_see
    pts = {uid: r for uid, r in _points(artist_id).items() if r["points"] >= MIN_POINTS}
    if not pts:
        return []
    User = get_user_model()
    blocked = set(blocked_user_ids(User(pk=artist_id))) if pts else set()
    viewer_minor = profile_is_minor(profile_for(viewer))
    profiles = {p.user_id: p for p in Profile.objects.filter(user_id__in=pts)}
    names = dict(User.objects.filter(id__in=pts).values_list("id", "username"))
    rows = []
    for uid, r in pts.items():
        if uid not in names or uid in blocked:
            continue
        # A Profile is made lazily, so a fan who never opened a profile screen
        # has none — which means every default: listed for members, an adult.
        p = profiles.get(uid) or Profile(user_id=uid)
        if profile_is_minor(p) != viewer_minor or not can_see(p, "superfan", viewer):
            continue
        rows.append({"username": names[uid], "user_id": uid, **r})
    rows.sort(key=lambda r: (-r["points"], r["username"].lower()))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def top_ids(artist_id, viewer):
    """The user ids of the artist's SuperfanZ as `viewer` may see them."""
    return {r["user_id"] for r in ranked(artist_id, viewer)[:TOP]}


class SuperfanzView(APIView):
    """GET /api/economy/superfanz/?username= — an artist's SuperfanZ, and where you stand."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        name = (request.query_params.get("username") or "").strip()
        artist = (get_user_model().objects.filter(username__iexact=name).first()
                  if name else request.user)
        if not artist:
            return Response({"detail": "member not found"}, status=status.HTTP_404_NOT_FOUND)
        rows = ranked(artist.id, request.user)
        top = [{k: v for k, v in r.items() if k != "user_id"} for r in rows[:TOP]]
        out = {"artist": artist.username, "name": NAME, "emoji": EMOJI, "rule": RULE,
               "points": POINTS, "min_points": MIN_POINTS, "window_days": WINDOW_DAYS, "top": top,
               "mine": artist.id == request.user.id}
        if artist.id != request.user.id:
            # Where the viewer stands — counted even when they have hidden themselves,
            # because it is theirs to see.
            me = _points(artist.id).get(request.user.id, {"points": 0})["points"]
            is_fan = any(r["username"] == request.user.username for r in top)
            # What it takes to get on: past the third fan when the list is full,
            # else just the floor. Already on it is 0, never a negative.
            need = (top[-1]["points"] + 1) if len(top) >= TOP else MIN_POINTS
            out["you"] = {"points": me, "superfan": is_fan,
                          "to_top": 0 if is_fan else max(0, need - me)}
        from .models import profile_for
        from .visibility import level_for
        out["your_listing"] = level_for(profile_for(request.user), "superfan")
        return Response(out)
