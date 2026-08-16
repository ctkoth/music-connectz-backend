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

from django.db.models import Case, Count, IntegerField, Sum, When
from django.utils import timezone

from .models import (
    CollabDeal,
    POST_COMMENT_UNLOCK_SEC,
    POST_RATE_UNLOCK_SEC,
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
    owns_post,
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


def media_slots(p):
    """The post's attachments as one-per-kind, for a client that renders all of
    them. Merges the primary media slot with the album entries, so a caller
    never has to know that a post keeps its first attachment in two places."""
    slots = {k: "" for k in MEDIA_SLOTS}
    if p.media_url and p.media_type in slots:
        slots[p.media_type] = p.media_url
    for it in (p.items or []):
        kind = (it.get("type") or "").lower()
        if kind not in slots or slots[kind]:
            continue
        slots[kind] = it.get("lyrics") if kind == "text" else it.get("url")
    return {k: v or "" for k, v in slots.items()}


def _post_dict(p, request, up=0, down=0, collabs=None):
    vibe = up - down
    flagged = down >= HIDE_FLAG_MIN_DOWN and down >= up * HIDE_FLAG_RATIO
    return {
        "id": p.id,
        "author": p.author.username,
        # True for everyone credited, not just whoever pressed post — a
        # collab post belongs to all of them.
        "mine": owns_post(p, request.user),
        "contributors": p.contributors or [],
        "co_owned": bool(p.contributors),
        "title": p.title,
        "description": p.description,
        "links": p.links,
        "media_type": p.media_type,
        "media_url": p.media_url,
        "is_album": p.is_album,
        "items": p.items or [],
        # One of each, resolved for the client so it renders every attachment
        # rather than only the primary one.
        "media": media_slots(p),
        "slots": list(MEDIA_SLOTS),
        "score": p.score or {},
        "genre": p.genre,
        # A flag beside the genre, never instead of it — a freestyle Trap verse
        # is still Trap, and ChartZ must still be able to slice it as Trap.
        "freestyle": p.freestyle,
        "skills_used": p.skills_used or [],
        "visibility": p.visibility,
        "allow_in_playlists": p.allow_in_playlists,
        # Age from the SERVER's clock, so the client's unlock countdowns can't
        # drift from the checks the API actually runs.
        "age_sec": int((timezone.now() - p.created_at).total_seconds()),
        "rate_unlock_sec": POST_RATE_UNLOCK_SEC,
        "comment_unlock_sec": POST_COMMENT_UNLOCK_SEC,
        # PostZ is for show, CollabZ is for collaboration — this is the count
        # of times somebody moved from one to the other on this post, and where
        # the client sends them to do it again.
        "collab_count": p.collab_deals.count() if collabs is None else collabs,
        "open_in": "collabz",
        "skill_cost_cents": p.skill_cost_cents,
        "joins": p.joins.count() if p.visibility == "restricted" else 0,
        "shares": p.shares.count(),
        "up": up, "down": down, "vibe": vibe, "flagged": flagged,
        "rating": item_rating_median(f"post:{p.id}"),
        "created_at": p.created_at.isoformat(),
        "edited_at": p.edited_at.isoformat() if p.edited_at else None,
        "edit_history": p.edit_history or [],
        # Who touched it last, when that wasn't the author. A post carries its
        # author's name; an edit by anybody else has to be visible on the post
        # itself, not buried in a history nobody opens.
        "edited_by": next((h.get("by") for h in reversed(p.edit_history or [])
                           if h.get("by") and h.get("by") != p.author.username), ""),
    }


def clean_items(raw):
    """Album entries, sanitized. One definition — CollabZ and OCC use it too."""
    out = []
    for it in (raw if isinstance(raw, list) else [])[:50]:
        if not isinstance(it, dict):
            continue
        out.append({
            "url": str(it.get("url", ""))[:500],
            "type": str(it.get("type", ""))[:24],
            "title": str(it.get("title", ""))[:160],
            "lyrics": str(it.get("lyrics", ""))[:8000],
        })
    return out


# What a post can carry: one of each. Not one attachment — one AUDIO, one
# VIDEO, one IMAGE and one SCRIPT, together, because a track with its video,
# its cover and its lyrics is one piece of work and was always meant to post as
# one thing. The composer used to make audio and video overwrite each other.
#
# An ALBUM is the deliberate exception and the only way to carry several of a
# kind. It has to be asked for (`is_album`) rather than inferred, which is the
# bug this replaces: `len(items) > 1` quietly turned "a track plus its cover"
# into an album nobody asked for.
MEDIA_SLOTS = ("audio", "video", "image", "text")
SLOT_LABEL = {"audio": "audio track", "video": "video", "image": "image",
              "text": "script"}


def one_of_each(items):
    """Enforce the slot rule. Returns (items, offending_type or None).

    Refuses rather than silently keeping the first — a member who attached two
    images should be told which one wasn't going to make it, not discover the
    loss later on their own post.
    """
    seen = set()
    for it in items:
        kind = (it.get("type") or "").lower()
        if kind in seen:
            return items, kind
        seen.add(kind)
    return items, None


def skill_prices(user):
    """{skill name: rate_cents} from the member's own PersonaZ skills."""
    from .models import profile_for
    out = {}
    for persona in (profile_for(user).personas or []):
        if not isinstance(persona, dict):
            continue
        for s in (persona.get("skills") or []):
            if not isinstance(s, dict):
                continue
            name = str(s.get("name", "")).strip()
            try:
                rate = int(s.get("rate_cents") or 0)
            except (TypeError, ValueError):
                rate = 0
            if name and rate > 0:
                out[name] = max(out.get(name, 0), rate)
    return out


def post_cost_cents(user, skills_used):
    """What posting this costs: the combined price of the skills that went in.

    Computed HERE, from the member's own rates, never taken from the request.
    The composer sent no cost at all, so every post in the app has been free
    while the screen implied otherwise — and a client-supplied price is a price
    the client can set to zero anyway.

    Returns (total_cents, breakdown) so the cost can be SHOWN before the button
    rather than discovered by pressing it.
    """
    prices = skill_prices(user)
    lines, total = [], 0
    for name in (skills_used or [])[:40]:
        if not isinstance(name, str):
            continue
        cents = prices.get(name.strip(), 0)
        lines.append({"skill": name.strip(), "cents": cents})
        total += cents
    # BadgeZ reads here, where the price is decided — the Gifted badge's
    # discount would be a sticker anywhere else.
    from .models import badge_effects
    off = badge_effects(user).get("post_discount_pct", 0)
    if off and total:
        total = max(0, total - int(total * off / 100))
    return total, lines


def create_post(user, d):
    """Make a post from a PostZ payload. Returns (post, info, error).

    Lifted out of the view so anything that publishes work — the composer, and
    now an OCC output being shared — goes through the SAME daily cap, the same
    energy charge and the same sanitizing. A second creation path is how one
    surface quietly stops charging for what the other charges for.

    `error` is a (payload, status) pair, or None.
    """
    title = str(d.get("title", "")).strip()[:160]
    if not title:
        return None, {}, ({"detail": "title required"}, status.HTTP_400_BAD_REQUEST)
    vis = str(d.get("visibility", "public")).lower()
    if vis not in {"public", "restricted", "private"}:
        vis = "public"
    # The price of the skills the member put on it, from THEIR rates. Taking
    # this from the request meant the composer's zero was the real price.
    skills = [str(x)[:60] for x in (d.get("skills_used") or [])
              if isinstance(x, (str, int))][:40]
    cost, _lines = post_cost_cents(user, skills)
    media_url = str(d.get("media_url", "")).strip()[:500]
    media_type = str(d.get("media_type", "")).strip()[:24]
    score = d.get("score") if isinstance(d.get("score"), dict) else {}
    items = clean_items(d.get("items"))
    # An album is asked for, never inferred from the count. Otherwise a track
    # posted with its cover art became "an album" of two.
    is_album = bool(d.get("is_album"))
    # Rides alongside the genre rather than replacing it — see Post.freestyle.
    freestyle = bool(d.get("freestyle"))
    if not is_album:
        items, dup = one_of_each(items)
        if dup:
            return None, {}, (
                {"detail": f"A post carries one {SLOT_LABEL.get(dup, dup)} — you attached two. "
                           "Tick album if you meant several.",
                 "duplicate_type": dup, "slots": list(MEDIA_SLOTS)},
                status.HTTP_400_BAD_REQUEST,
            )
    # A scored/recorded take (score payload or media) counts against the tier's
    # daily submission cap (Free 5 · Premium 15 · StatZ 50).
    is_submission = bool(score) or bool(media_url) or bool(items)
    if is_submission:
        cap = submission_cap_for(user)
        used = submissions_used_today(user)
        if used >= cap:
            return None, {}, (
                {"detail": f"Daily submission limit reached ({used}/{cap}). Upgrade for more.",
                 "used": used, "cap": cap},
                status.HTTP_429_TOO_MANY_REQUESTS,
            )
    # Posting costs energy = combined skill price (cents). Deduct what's there.
    w = wallet_for(user)
    charged = min(cost, max(0, w.energy))
    if charged:
        w.energy -= charged
        w.save(update_fields=["energy", "updated_at"])
    p = Post.objects.create(
        author=user, title=title,
        description=str(d.get("description", ""))[:4000],
        links=d.get("links") or [], media_type=media_type, media_url=media_url,
        is_album=is_album, items=items,
        score=score, visibility=vis, skill_cost_cents=cost,
        genre=str(d.get("genre", ""))[:40],
        freestyle=freestyle,
        skills_used=skills,
        allow_in_playlists=bool(d.get("allow_in_playlists", True)),
    )
    if is_submission:
        record_submission(user)
    return p, {"energy_charged": charged, "energy": w.energy}, None


class PostCostView(APIView):
    """GET /api/economy/postz/cost/?skills=a,b — what posting this will cost.

    Exists so the composer can state the price ON the button. The rule is that
    a cost is announced before it is paid; a post that charges you and tells
    you afterwards has sent a bill, not quoted a price.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        raw = request.query_params.get("skills", "")
        skills = [s for s in (x.strip() for x in raw.split(",")) if s]
        total, lines = post_cost_cents(request.user, skills)
        w = wallet_for(request.user)
        return Response({
            "cost": {"resource": "energy", "amount": total},
            "lines": lines,
            "energy": w.energy,
            # What actually comes off. Energy never goes negative — the post is
            # made either way, so say that rather than implying a refusal.
            "charged": min(total, max(0, w.energy)),
            "affordable": w.energy >= total,
            "priced_skills": sorted(skill_prices(request.user)),
            "note": "Posting costs the combined price of the skills you put on "
                    "it. Skills you haven't priced cost nothing.",
        })


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
        # A collab post belongs to its contributors too, so a private one has
        # to reach them — `can_view_post` already allows it, but the query never
        # fetched it, and a post you may see that is never selected is invisible
        # either way.
        #
        # One indexed join through PostContributor. Reaching it through the
        # deal's participants JSON instead cost two extra queries on every feed
        # load, which the query-count test below caught immediately.
        ours = Post.objects.filter(visibility="private",
                                   contributor_rows__user=request.user)
        seen_ids, visible = set(), []
        for p in list(qs) + list(mine) + list(ours):
            if p.id in seen_ids or not can_view_post(p, request.user):
                continue
            seen_ids.add(p.id)
            visible.append(p)
        reactions = _reactions_for([p.id for p in visible])
        # Counted in ONE query rather than one per card — the feed serves up to
        # 100 posts and this is the third per-row count on it.
        deals = dict(
            CollabDeal.objects.filter(source_post_id__in=[p.id for p in visible])
            .values_list("source_post_id")
            .annotate(n=Count("id"))
        )
        posts = [_post_dict(p, request, *reactions.get(p.id, (0, 0)),
                            collabs=deals.get(p.id, 0)) for p in visible]

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
        # Edit an existing post (author only, within the tier's edit window).
        edit_id = d.get("edit_id")
        if edit_id is not None:
            return self._edit(request, edit_id, d)
        p, info, err = create_post(request.user, d)
        if err:
            return Response(err[0], status=err[1])
        return Response({**_post_dict(p, request), **info}, status=status.HTTP_201_CREATED)

    def _edit(self, request, edit_id, d):
        """Edit a post — yours within the tier's edit window, any post if you own
        the platform.

        Two things the owner override is careful about:

        * **The window is the author's protection, not the owner's.** It exists
          so a post can't be quietly rewritten after people have read and rated
          it. The owner is exempt because somebody has to be able to fix a
          broken media link on a two-year-old post — that is the whole reason
          this exists — but exempt is not invisible.
        * **An edit to somebody else's post is recorded as theirs to see.** The
          history entry names who made it, and `_post_dict` surfaces it. A post
          still carries its author's name; an unmarked edit by anybody else is
          the platform putting words in their mouth, and no amount of "it's my
          app" makes that readable to the person whose name is on it.
        """
        from .catalog import edit_window_for
        from .models import membership_for, notify
        from .views import is_owner
        owner = is_owner(request.user)
        p = (Post.objects.filter(pk=edit_id).first() if owner
             else Post.objects.filter(pk=edit_id, author=request.user).first())
        if not p:
            return Response({"detail": "post not found"}, status=status.HTTP_404_NOT_FOUND)
        mine = p.author_id == request.user.id
        # Playlist consent is a SETTING, not content, so it is not held to the
        # tier's edit window. Locking an author out of withdrawing their work
        # four minutes after posting would make the switch useless.
        if "allow_in_playlists" in d:
            p.allow_in_playlists = bool(d["allow_in_playlists"])
            p.save(update_fields=["allow_in_playlists"])
            if len(d) <= 2:            # edit_id + the flag: nothing else to do
                return Response(_post_dict(p, request))
        if not owner:
            window = edit_window_for(membership_for(request.user).tier)
            if timezone.now() > p.created_at + timedelta(seconds=window):
                return Response({"detail": "edit_window_passed", "window_seconds": window}, status=status.HTTP_403_FORBIDDEN)
        title = str(d.get("title", p.title)).strip()[:160] or p.title
        description = str(d.get("description", p.description))[:4000]
        # Media is editable too. A post whose whole point is the track, with no
        # way to attach one afterwards, is why this went past title-and-caption:
        # the fix for a missing upload was posting the whole thing again.
        before = {"title": p.title, "description": p.description,
                  "media_url": p.media_url, "media_type": p.media_type,
                  "items": p.items, "is_album": p.is_album, "links": p.links,
                  "genre": p.genre, "skills_used": p.skills_used}
        fields = ["title", "description"]
        p.title, p.description = title, description
        if "media_url" in d:
            p.media_url = str(d.get("media_url") or "").strip()[:500]
            fields.append("media_url")
        if "media_type" in d:
            p.media_type = str(d.get("media_type") or "").strip()[:24]
            fields.append("media_type")
        if "is_album" in d:
            p.is_album = bool(d["is_album"])
            fields.append("is_album")
        if "items" in d:
            items = clean_items(d.get("items"))
            if not p.is_album:
                # Same rule as posting: one of each slot unless it's an album,
                # or a track plus its cover silently becomes "an album of two".
                items, dup = one_of_each(items)
                if dup:
                    return Response(
                        {"detail": f"A post carries one {SLOT_LABEL.get(dup, dup)} — you attached two. "
                                   "Tick album if you meant several.",
                         "duplicate_type": dup, "slots": list(MEDIA_SLOTS)},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            p.items = items
            fields.append("items")
        if "links" in d:
            p.links = [x for x in (d.get("links") or []) if x][:20]
            fields.append("links")
        if "genre" in d:
            p.genre = str(d.get("genre") or "")[:40]
            fields.append("genre")
        if "skills_used" in d:
            p.skills_used = [str(x)[:60] for x in (d.get("skills_used") or [])
                             if isinstance(x, (str, int))][:40]
            fields.append("skills_used")

        after = {k: getattr(p, k) for k in before}
        if after == before:
            return Response(_post_dict(p, request))
        # Who changed it goes in the row. On your own post that is just you; on
        # somebody else's it is the whole point of keeping a history at all.
        entry = {**before, "at": timezone.now().isoformat(), "by": request.user.username}
        p.edit_history = (p.edit_history or []) + [entry]
        p.edited_at = timezone.now()
        p.save(update_fields=[*fields, "edit_history", "edited_at"])
        if not mine:
            # The author finds out from the app, not by noticing. Editing
            # somebody's work and letting them discover it is the version of
            # this that costs trust.
            notify(p.author, "post",
                   f"✏️ @{request.user.username} edited your post \"{p.title}\" as platform owner.",
                   actor=request.user, item_id=f"post:{p.id}")
        return Response(_post_dict(p, request))


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
        notify(p.author, "join", f"@{user.username} joined '{p.title}' — you earned +{RESTRICTED_JOIN_REWARD_SPINAZ} 🍥", actor=user, item_id=f"post:{p.id}")
        return True


# One sharer can't farm shares by rotating IPs/accounts on the same post.
SHARE_REWARD_DAILY_CAP = 20  # max share rewards a single user can earn per day


class PostDeleteView(APIView):
    """DELETE /api/economy/postz/<pk>/delete/ — remove a post.

    Yours at any age: the edit window protects readers from a post changing
    under them, and taking your own work down is not that — an author who can
    never withdraw what they published is the dead end this app doesn't do.

    The platform owner can remove any post, which is what moderation is. When
    it isn't theirs, the author is told, because work vanishing with no
    explanation is indistinguishable from a bug.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        from .models import notify
        from .views import is_owner
        p = Post.objects.filter(pk=pk).select_related("author").first()
        if not p:
            return Response({"detail": "post not found"}, status=status.HTTP_404_NOT_FOUND)
        mine = p.author_id == request.user.id
        if not mine and not is_owner(request.user):
            return Response({"detail": "That isn't your post."},
                            status=status.HTTP_403_FORBIDDEN)
        title = p.title
        author = p.author
        if not mine:
            notify(author, "post",
                   f"🗑️ @{request.user.username} removed your post \"{title}\" as platform owner.",
                   actor=request.user)
        p.delete()
        return Response({"deleted": True, "id": pk, "title": title,
                         "author": author.username})

    # Some clients can't send a body-less DELETE through their fetch wrapper.
    def post(self, request, pk):
        return self.delete(request, pk)


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
