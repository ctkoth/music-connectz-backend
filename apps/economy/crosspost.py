"""Where a post can go next.

Cross-pollination, applied to the one thing every member makes: a post. A post
was a dead end with a rating on it — the only door out of it was CollabZ, and
that door was a hardcoded string in `_post_dict`. Everything else a member
might want to DO with the work they were looking at (have it coached, put it in
a playlist, enter it in a battle, rework the lyrics, fill a release) meant
finding the app, then finding the file again, then uploading it a second time.

So this module is the one list of destinations, on the server, where the price
of each is already known:

* Every post row carries `destinations` — where this specific post can go, what
  happens when it gets there, what it costs UP FRONT, and what it still needs
  when it can't go yet.
* A destination that can't do anything with the post is never offered as
  available. "Coach it in SingZ" on a post with no recording is a button that
  can only fail, so it comes back with `needs` filled in and the reason on it
  instead of being silently dropped — a member with a lyrics-only post should
  learn that the coach wants a take, not wonder where SingZ went.
* `carry` is the post in the shape a destination consumes, so the client hands
  the work over instead of asking anyone to re-attach it.

The improvement doors — SingZ and RapZ — are the reason this exists. A post is
a finished take sitting still; the coach is the thing that tells you what to fix
about it. Those two were the furthest apart in the app and had the most to say
to each other.
"""
from .instruments import profile_for_app

# The apps that mount a Boss Take coach. Kept level with the routes in
# music_connectz/urls.py — a coach destination for an app with no coach route
# is a door onto a 404.
COACH_APPS = ("singz", "rapz")

# What the coach can be handed. Text isn't a performance and an image isn't
# either; the model listens and watches, so those two slots can't feed it.
COACHABLE = ("audio", "video")


def coach_price(user):
    """What one coached take costs this member right now.

    Read ONCE per request and passed into `destinations_for`, because the feed
    serves up to 100 posts and every one of them offers SingZ and RapZ — pricing
    each card on its own would be 200 wallet reads to print the same number.
    """
    from .catalog import ai_cost
    from .models import can_afford_ai, daily_prompt_state

    cost = ai_cost("standard")
    _allowance, _used, left = daily_prompt_state(user)
    return {
        "resource": "promptz",
        "amount": cost,
        # A free daily prompt covers the whole run before any balance is
        # touched, so the price a member actually pays today is often nothing —
        # and saying "−1 🏷️" at somebody whose take is free is its own small lie.
        "free_today": bool(cost) and left > 0,
        "daily_remaining": left,
        "affordable": bool(not cost or left > 0 or can_afford_ai(user, cost)),
        # A take the coach can't read is never billed — vocalcoach.py bills only
        # after a usable result parses. Said, not just done.
        "charged_on_failure": False,
    }


FREE = {"resource": None, "amount": 0, "free_today": True, "affordable": True,
        "charged_on_failure": False}


def carry(post, media):
    """The post, in the shape a destination fills its form from.

    One shape for every door. A destination that wants the lyrics and one that
    wants the audio read the same dict, so adding an app doesn't mean teaching
    PostZ a new payload.
    """
    return {
        "post_id": post.id,
        "title": post.title,
        "description": post.description or "",
        "genre": post.genre or "",
        "freestyle": bool(post.freestyle),
        "author": post.author.username,
        "skills_used": post.skills_used or [],
        "audio_url": media.get("audio", ""),
        "video_url": media.get("video", ""),
        "image_url": media.get("image", ""),
        "lyrics": media.get("text", ""),
    }


def _take_kind(media):
    """Which slot the coach would listen to, or "" when there's nothing to hear.

    Audio first: a post carrying both is a track with its video, and the track
    is the performance. The coach reads video happily — it marks delivery and
    breath off it — but sending the video of a song when the song itself is
    attached spends the member's prompt on the bigger file for no extra marks.
    """
    for kind in COACHABLE:
        if media.get(kind):
            return kind
    return ""


def _tail(url):
    """The stored path's filename. MEDIA_URL differs between local disk, Render
    and any CDN in front of it, so whole-URL comparison matches in exactly one
    environment."""
    return str(url or "").split("?")[0].rsplit("/", 1)[-1]


def take_state_for(rows):
    """{post_id: {"bytes": n, "missing": bool}} for each post's take — ONE query.

    Both facts come off the same `Upload` row, so reading them apart would be
    two queries over the feed to answer one question about the same file.

    `missing` is the row's own `missing_since`, which is only ever stamped by
    something that WENT AND LOOKED — the coach reading a take, or the reconcile
    sweep. Nothing here touches storage: a feed of 100 posts must not become
    100 stat calls, or 100 HEAD requests once uploads are in a bucket.

    A post whose media resolves to no Upload row at all is not marked missing.
    That is a link to somebody else's site, which is a perfectly good post and
    a take the coach simply cannot fetch — a different sentence, and one
    `post_take()` already says.
    """
    return _take_rows(rows)


def take_bytes_for(rows):
    """{post_id: size_bytes} for the take on each post — in ONE query.

    The coach reads a take inside a single request that caps out near MAX_MB,
    and until this existed the destination list had no idea how big a post's
    track was. So "Coach it in SingZ" was offered on a 29MB post, the post
    travelled, the button went live, and the ceiling announced itself by being
    hit. A refusal you discover by pressing the button is the same failure as a
    price you discover by paying it.

    `rows` is [(post, media)]. Scoped to the authors of those posts, like
    `upload_behind` — a size read is not a file read, but the same discipline
    costs nothing and keeps a same-named file belonging to a stranger out of
    the answer.
    """
    from django.db.models import Q

    from .models import Upload

    wanted, authors, kinds = {}, set(), {}
    for post, media in rows:
        kind = _take_kind(media)
        if not kind:
            continue
        tail = _tail(media[kind])
        if tail:
            wanted.setdefault(tail, []).append(post.id)
            kinds[post.id] = kind
            authors.add(post.author_id)
    if not wanted:
        return {}
    return {pid: st["bytes"] for pid, st in _take_rows(rows).items()}


def _take_rows(rows):
    """The shared body. See `take_state_for` — one query, both facts."""
    from django.db.models import Q

    from .models import Upload

    wanted, authors, kinds = {}, set(), {}
    for post, media in rows:
        kind = _take_kind(media)
        if not kind:
            continue
        tail = _tail(media[kind])
        if tail:
            wanted.setdefault(tail, []).append(post.id)
            kinds[post.id] = kind
            authors.add(post.author_id)
    if not wanted:
        return {}
    match = Q()
    for tail in wanted:
        match |= Q(file__endswith=tail)
    out = {}
    for name, size, missing in (Upload.objects.filter(match, user_id__in=authors)
                                .values_list("file", "size_bytes", "missing_since")):
        for pid in wanted.get(_tail(name), ()):
            # `kind` travels with it so the client knows WHICH player to
            # replace with the notice — a post can carry a video that is fine
            # and an audio take that is not.
            prev = out.setdefault(pid, {"bytes": 0, "missing": True,
                                        "kind": kinds.get(pid, "")})
            # Biggest wins on the off-chance two uploads share a basename: a
            # warning that overstates is recoverable, one that understates puts
            # the member back in front of the refusal this exists to prevent.
            prev["bytes"] = max(prev["bytes"], size or 0)
            # Missing only when EVERY candidate behind that name is. One
            # readable file there is a post that still plays, and telling its
            # author their music is gone when it is not is the same false
            # certainty the <audio> element had — pointed at somebody's work
            # this time. It starts True and one present row clears it, so the
            # error is always on the side of saying nothing.
            if not missing:
                prev["missing"] = False
    return out


def coach_cap(user):
    """What the coach will take from THIS member: {mb, bytes, is_tier}.

    Per-member, not global: the ceiling is the coach's own judgement or the
    member's tier upload limit, whichever binds them first, so the destination
    row greys out at the number that will actually refuse THEM.

    Read ONCE per request and passed into `destinations_for`, for the same
    reason the price is — it reads the membership row, and doing that per card
    is a query per post to print one number that is the same on all of them.
    The feed's own query-count test catches it if this is forgotten.
    """
    from .vocalcoach import cap_for
    mb, is_tier = cap_for(user)
    return {"mb": mb, "bytes": mb * 1024 * 1024, "is_tier": is_tier}


def destinations_for(post, user, media, *, price=None, collabs=0, take_bytes=None,
                     cap=None, take_missing=False):
    """Every app this post can open in, with the price of each stated first.

    `media` is `postz.media_slots(post)` — passed in rather than recomputed,
    since the caller has already resolved it for the row.

    Each entry:
      app      — the tab key, for goToSpot()
      target   — the data-tour anchor inside it, so the jump lands on the
                 control rather than the top of the app
      action   — what the destination does with the payload: "coach", "seed",
                 or "open"
      needs    — empty when it can go. Non-empty means the button says what is
                 missing instead of failing after the tap.
      cost/gain— stated here, before the member commits to anything.
    """
    mine = _owns(post, user)
    take = _take_kind(media)
    price = price or coach_price(user)
    no_take = [] if take else ["a recording — attach audio or video to this post"]
    out = []

    # The coach's ceiling, checked HERE rather than on the way in. The post
    # keeps the whole track — this is the scorer's per-request limit, not the
    # member's tier — but a door that can only end in a refusal must say so on
    # the row instead of after the tap.
    #
    # `take_bytes` is None when nobody looked. An unmeasured file is not a file
    # over the limit, so the door stays open rather than claiming a size it
    # never read; the coach still refuses at the wall if it comes to that.
    cap = cap or coach_cap(user)
    too_big = bool(take and take_bytes and take_bytes > cap["bytes"])
    # The recording is gone from storage, and we know because something went
    # and looked. The coach door has to close HERE, on the row, in the app the
    # member is already in — not one jump away after they have chosen it. That
    # trip used to end with SingZ telling somebody their own take was not on
    # the server, which is the worst possible place to learn it: away from the
    # post, away from the file they might still have, and framed as a refusal
    # by the coach rather than as something the platform lost.
    if take and take_missing:
        coach_needs = [f"the {take} back — the recording on this post isn't on "
                       f"the server any more. Attach it again here and every "
                       f"door on this post opens with it"]
    elif too_big:
        from .vocalcoach import cap_why
        mb = take_bytes / (1024 * 1024)
        coach_needs = [f"a take under {cap['mb']}MB — the {take} on this post is "
                       f"{mb:.0f}MB. " + cap_why(cap["mb"], cap["is_tier"])
                       + " The post keeps the full track, so record or attach just "
                         "the section you want scored"]
    else:
        coach_needs = no_take

    # --- The improvement doors. -------------------------------------------
    # A post is a finished take standing still. The coach is what turns it into
    # the next one, so these go first.
    for app_key in COACH_APPS:
        p = profile_for_app(app_key)
        out.append({
            "app": app_key,
            "label": f"Coach it in {p['label']}",
            "target": "bosstake-mic",
            "action": "coach",
            "what": f"Send this {take or 'take'} to the {p['coach']} — scored out of 10 on "
                    + ", ".join(list(p["scores"].values())[:3]).lower()
                    + ", with what worked, what to fix and one drill.",
            "needs": coach_needs,
            "cost": price,
            "gain": {"what": "a scored take with a drill to run next"},
            "carry": carry(post, media),
            "coach_kind": take,
            # What the client needs to hold the same line if it is showing a
            # card the feed rendered a while ago.
            "take_bytes": take_bytes or 0,
            "max_bytes": cap["bytes"],
            "max_is_tier_limit": cap["is_tier"],
        })

    # --- Doors that already existed as buttons, now in the same list. -----
    out.append({
        "app": "collabz",
        "label": "Take it to CollabZ",
        "target": "collabz-deals",
        "action": "deal",
        "what": "Start a deal from this post — the title and the author come "
                "with it, so nobody retypes what they were just looking at.",
        "needs": [],
        "cost": FREE,
        "gain": {"what": "a draft deal, free to draft"},
        "carry": carry(post, media),
        "count": collabs,
    })
    out.append({
        "app": "playlistz",
        "label": "Add it to a playlist",
        "target": "playlistz-add",
        "action": "seed",
        # The consent switch is the post's, so a post opted out of playlists
        # doesn't offer the door — see Post.allow_in_playlists.
        "what": "Drop this post into one of your playlists, ready to share as a link.",
        "needs": ([] if post.allow_in_playlists
                  else ["playlist consent — this post is set to stay out of playlists"]),
        "cost": FREE,
        "gain": {"what": "a shareable list this sits in"},
        "carry": carry(post, media),
    })
    out.append({
        "app": "battlez",
        "label": "Enter it in a battle",
        "target": "battlez-list",
        "action": "seed",
        "what": "Put this up as your entry — the title and the take are filled in "
                "from the post. The battle states its own stake before you enter.",
        # Same fact, same sentence. A door that hands over a recording cannot
        # open on a recording that is not there either.
        "needs": (coach_needs if (take and take_missing) else no_take),
        "cost": FREE,
        "gain": {"what": "your entry, prefilled"},
        "carry": carry(post, media),
    })
    out.append({
        "app": "occ",
        "label": "Rework it in OCC",
        "target": "occ-workz",
        "action": "seed",
        "what": "Open the post in WorkZ with its words and attachment already in — "
                "rewrite the hook, tighten the description, keep the result.",
        # A title on its own is not something to rework. The door opens when
        # there are actual WORDS on the post — otherwise OCC is handed a name
        # and asked to improve it.
        "needs": ([] if (post.description or media.get("text"))
                  else ["words to work on — a description or lyrics on the post"]),
        "cost": FREE,
        "gain": {"what": "a WorkZ draft; keeping it is free"},
        "carry": carry(post, media),
    })
    # DirectZ fills a release from the four assets a distributor asks for, and
    # only the people whose work it is may release it.
    out.append({
        "app": "directz",
        "label": "Fill a release from it",
        "target": "directz-releases",
        "action": "distribute",
        "what": "The song, the video, the cover and the lyrics are already on this "
                "post — a release gets filled from them rather than retyped.",
        "needs": ([] if mine else ["your own post — a release is the author's to start"])
                 + ([] if media.get("audio") else ["the song — attach audio to this post"]),
        "cost": FREE,
        "gain": {"what": "a release, prefilled from the post"},
        "carry": carry(post, media),
    })
    for d in out:
        d["available"] = not d["needs"]
    return out


def _owns(post, user):
    from .models import owns_post
    return owns_post(post, user)


# ---- The take behind a post, for the coach ------------------------------

def upload_behind(url, users):
    """The stored Upload a post's media URL points at, or None.

    Scoped to `users` — the post's author and everyone credited on it — for the
    same reason DirectZ scopes its lookup to one member: matching on the URL
    alone would let any address resolve to any member's file. The difference
    here is that the URL is not the client's to choose. It comes off the Post
    row, so the owners of the file are exactly the people whose post it is.
    """
    from .models import Upload

    url = str(url or "").strip()
    if not url:
        return None
    # The stored path's tail, not the whole URL: MEDIA_URL differs between
    # local disk, Render and any CDN in front of it, so comparing full URLs
    # would match in exactly one environment.
    tail = url.split("?")[0].rsplit("/", 1)[-1]
    if not tail:
        return None
    return (Upload.objects.filter(user__in=users, file__endswith=tail)
            .order_by("-id").first())


def post_take(post, media):
    """(upload, kind, reason) — the file the coach should listen to.

    Exactly one of `upload` and `reason` is set. `reason` is written to be read
    by a member: "there's no recording on this post" is an answer, "not found"
    is a shrug.
    """
    kind = _take_kind(media)
    if not kind:
        return None, "", ("There's no recording on this post — the coach scores "
                          "audio or video, so attach a take and try again.")
    owners = [post.author_id] + list(
        post.contributor_rows.values_list("user_id", flat=True))
    up = upload_behind(media[kind], owners)
    if up is None:
        # A link to somebody else's site is a perfectly good post and a take the
        # coach can't fetch. Say which of those it is.
        return None, kind, ("That take isn't stored on Music ConnectZ, so the "
                            "coach can't read it. Record or attach it in the "
                            "coach and it'll be scored.")
    return up, kind, ""
