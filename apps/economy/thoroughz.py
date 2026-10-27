"""Thorough 💯 — the badge for members whose training is actually thorough.

Corey's tiers, on the member's Thorough rating (BodieZ, 1 to 10):

    6   💯 Thorough     (anything above 5)
    7   🥈 Decent
    8   🥇 Legendary
    9   🌟 Supreme
    10  💎 Perfect

THE NUMBER IS THE SAME NUMBER. A member's rating is the mean of the Thorough
rating of each lift they logged in the last 28 days (`bodiez.lift_thoroughness`,
the one formula). Nothing is re-scored here, so the badge, the BodyMap and the
routine card can never disagree about what thorough means.

THE SUBSTANCE RULE, said out loud. Thorough is days trained, sets a week and
whether the lift is going up against the member's own earlier best, so this
badge honestly says "trains thoroughly", not "is strong" or "is good". XP and
badges may reward effort; this is effort, plus a progress leg that a muscle hit
daily and going nowhere cannot fake. `NOTHING_PAYS`: the badges carry no effect
on Energy, SpinaZ or price — a rating that paid would be worth faking.

TWO GUARDS THE FORMULA DID NOT HAVE
* `MIN_LIFTS` (3) distinct lifts in the window. Per lift, a 10 needs eight
  training days and a rising top set; one lift trained hard for four weeks is a
  real effort and a narrow one, and "Perfect" for it would say more than the
  evidence does. The cost: someone who really only does one lift gets no badge.
* The badge is TEMPORARY. The window is 28 days; stop training and the rating
  falls, so the mark has to be able to fall with it (recheck_badges).

ONE HELD AT A TIME. The five badges are a ladder: each check is true only at
its own tier, so climbing replaces the lower mark and the member is not told a
rung "lapsed" when they just stepped past it (`ladder` in models.BADGES).

PRIVACY is BadgeZ's, unchanged: a badge is also a disclosure, so the member's
per-badge switch decides whether it is WORN. Everything on a post, collab or
venue, and membership of the group below, reads `visible=True` badges only.
"""
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

MIN_LIFTS = 3

# (rating, key, name, emoji) — highest first. The emoji are Corey's placeholders
# until his art arrives; `icon` stays "" so the client falls back to the emoji.
TIERS = [
    (10, "perfect", "Perfect", "💎"),
    (9, "supreme", "Supreme", "🌟"),
    (8, "legendary", "Legendary", "🥇"),
    (7, "decent", "Decent", "🥈"),
    (6, "thorough", "Thorough", "💯"),
]
KEYS = tuple(t[1] for t in TIERS)
GROUP_NAME = "Thorough 💯"
GROUP_EMOJI = "💯"
_BY_KEY = {t[1]: t for t in TIERS}

CAVEAT = (
    "Thorough is how completely you train, from your finished sessions in the "
    "last 28 days — days trained, working sets a week, and whether each lift is "
    "going up against your own earlier best. It is not how strong you are next "
    "to anyone else, it pays nothing, and it needs at least "
    f"{MIN_LIFTS} different lifts in those 28 days."
)


def tier_for(rating):
    """The badge key for a rating, or None at 5 and under (and None itself)."""
    if rating is None:
        return None
    for floor, key, _name, _emoji in TIERS:
        if rating >= floor:
            return key
    return None


def member_rating(user, now=None):
    """{"rating": int|None, "lifts": n} — the member's Thorough rating.

    None (never 0) when fewer than MIN_LIFTS lifts were logged in the window.
    The two sides of a one-arm lift are one lift, as in the routine rating.
    """
    from collections import defaultdict
    from .bodiez import BodieZSet, lift_thoroughness

    sets = (BodieZSet.objects.filter(session__user=user, session__ended_at__isnull=False)
            .select_related("exercise", "session"))
    per_lift = defaultdict(list)
    for r in lift_thoroughness(sets, now).values():
        per_lift[r["exercise_id"]].append(r["rating"])
    if len(per_lift) < MIN_LIFTS:
        return {"rating": None, "lifts": len(per_lift)}
    lifts = [sum(v) / len(v) for v in per_lift.values()]
    return {"rating": max(1, min(10, round(sum(lifts) / len(lifts)))), "lifts": len(lifts)}


def badge_key_for(user):
    """The ladder key this member is on right now. Computed once per user
    object, because `recheck_badges` asks five checks the same question."""
    cached = getattr(user, "_thorough_key", None)
    if cached is not None and cached[0] > timezone.now().timestamp() - 5:
        return cached[1]
    key = tier_for(member_rating(user)["rating"])
    try:
        user._thorough_key = (timezone.now().timestamp(), key)
    except Exception:
        pass
    return key


def mark_of(key, awarded_at=None):
    """The compact mark that rides on a post, deal or venue."""
    _floor, k, name, emoji = _BY_KEY[key]
    return {"key": k, "name": name, "emoji": emoji, "rating": _floor,
            "label": f"{name} {emoji}", "open_in": "groupz", "target": "thorough"}


def marks_for(user_ids):
    """{user_id: mark} for a page of rows, in ONE query.

    Reads only badges the holder chose to show, so a card can never be the
    place a hidden badge leaks out of. A member holds one rung at a time; if
    the table ever disagrees, the higher one wins.
    """
    from .models import Badge
    ids = {i for i in user_ids if i}
    if not ids:
        return {}
    out = {}
    order = {k: i for i, k in enumerate(KEYS)}      # perfect first
    for uid, key in (Badge.objects.filter(user_id__in=ids, key__in=KEYS, visible=True)
                     .values_list("user_id", "key")):
        if uid not in out or order[key] < order[out[uid]["key"]]:
            out[uid] = mark_of(key)
    return out


def marks_by_username(usernames):
    """{username: mark}; for rows that carry a name and no id (deal participants).
    One joined query, so a page of deals or venues pays one read for its marks."""
    from .models import Badge
    names = {n for n in usernames if n}
    if not names:
        return {}
    out = {}
    order = {k: i for i, k in enumerate(KEYS)}
    for name, key in (Badge.objects.filter(user__username__in=names, key__in=KEYS, visible=True)
                      .values_list("user__username", "key")):
        if name not in out or order[key] < order[out[name]["key"]]:
            out[name] = mark_of(key)
    return out


def _next_rung(rating):
    """The next rung up, or None at the top. Below the ladder it is the first."""
    above = [t for t in reversed(TIERS) if rating is None or t[0] > rating]
    if not above:
        return None
    floor, _k, name, emoji = above[0]
    return {"rating": floor, "label": f"{name} {emoji}"}


def marks_for_posts(posts):
    """{username: mark} for the authors AND credited contributors of a page of
    posts, in two queries however long the page is."""
    names = set()
    for p in posts:
        names.add(p.author.username)
        for c in (p.contributors or []):
            if isinstance(c, dict) and c.get("username"):
                names.add(c["username"])
    return marks_by_username(names)


def marks_for_deals(deals):
    """{username: mark} for every participant and the starter of a page of deals."""
    names = set()
    for d in deals:
        names.add(d.initiator.username)
        for c in (d.participants or []):
            if isinstance(c, dict) and c.get("username"):
                names.add(c["username"])
    return marks_by_username(names)


GROUP_MEMBER_CAP = 200
GROUP_POST_CAP = 20


class ThoroughZView(APIView):
    """GET /api/economy/thoroughz/ — the Thorough 💯 group.

    Everyone wearing a Thorough badge, grouped by rung, with the newest posts
    of the group on top. Yours: where you stand and why, so the climb is
    readable BEFORE you train for it (the cost/gain rule: this costs nothing,
    pays nothing, and says what it takes).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import Badge, Post, can_view_post
        mine = member_rating(request.user)
        my_key = tier_for(mine["rating"])
        wearing = marks_for([request.user.id]).get(request.user.id)

        order = {k: i for i, k in enumerate(KEYS)}
        rows = (Badge.objects.filter(key__in=KEYS, visible=True)
                .select_related("user").order_by("-awarded_at"))[:GROUP_MEMBER_CAP * 2]
        best = {}
        for b in rows:
            cur = best.get(b.user_id)
            if cur is None or order[b.key] < order[cur.key]:
                best[b.user_id] = b
        held = sorted(best.values(), key=lambda b: (order[b.key], b.user.username.lower()))[:GROUP_MEMBER_CAP]

        tiers = []
        for floor, key, name, emoji in TIERS:
            members = [b.user.username for b in held if b.key == key]
            tiers.append({"key": key, "name": name, "emoji": emoji, "rating": floor,
                          "label": f"{name} {emoji}", "count": len(members), "members": members})

        author_ids = list(best)
        posts = []
        if author_ids:
            qs = (Post.objects.filter(author_id__in=author_ids).exclude(visibility="private")
                  .select_related("author").order_by("-created_at")[:GROUP_POST_CAP * 3])
            marks = marks_for(author_ids)
            for p in qs:
                if not can_view_post(p, request.user):
                    continue
                posts.append({"id": p.id, "title": p.title, "author": p.author.username,
                              "media_type": p.media_type, "created_at": p.created_at.isoformat(),
                              "mark": marks.get(p.author_id), "open_in": "social:post",
                              "url": f"/p/{p.id}" if p.visibility == "public" else ""})
                if len(posts) >= GROUP_POST_CAP:
                    break

        return Response({
            "group": {"name": GROUP_NAME, "emoji": GROUP_EMOJI, "icon": ""},
            "caveat": CAVEAT,
            "min_lifts": MIN_LIFTS,
            "mine": {"rating": mine["rating"], "lifts": mine["lifts"], "tier": my_key,
                     "wearing": wearing,
                     "next": _next_rung(mine["rating"]),
                     "open_in": "badgez"},
            "tiers": tiers,
            # Group posts first: the page exists to be a room, and a room is its work.
            "posts": posts,
            "members": sum(t["count"] for t in tiers),
        })
