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

from django.db import transaction
from django.db.models import Case, Count, IntegerField, Sum, When
from django.utils import timezone

from .catalog import (SUBMISSION_PACK, SUBMISSION_PACK_ENERGY, SUBMISSION_PACKS_MAX, BOOST_ENERGY, BOOST_HOURS, BOOST_MAX_AHEAD_HOURS, BOOST_SLOTS,
                      POST_ENERGY_FLOOR, edit_window_for)
from .coachshare import clean_visibility, coach_read_for, for_new_post, legacy_score
from .crosspost import coach_cap, coach_price, destinations_for, take_state_for
from .thoroughz import marks_for_posts
from .gates import clean_gates, failing_gate, member_metrics, refusal
from .models import (
    CollabDeal,
    Wallet,
    POST_COMMENT_UNLOCK_SEC,
    POST_RATE_UNLOCK_SEC,
    DailySubmission,
    Post,
    PostJoin,
    PostShare,
    Reaction,
    ItemRating,
    RESTRICTED_JOIN_REWARD_SPINAZ,
    SHARE_REWARD_ENERGY,
    SHARE_MIN_ACTIVE_SECONDS,
    BATTLE_RATING_THRESHOLD,
    DEV_TAX,
    Transaction,
    award_spinaz,
    can_view_post,
    owns_post,
    item_rating_median,
    item_rating_medians,
    log_resource,
    membership_for,
    notify,
    record_submission,
    split_cents,
    submission_cap_for,
    submissions_used_today,
    spend_energy,
    wallet_for,
    post_collab_threshold,
    post_is_battle_eligible,
    post_is_collab_eligible,
)
from .embedplays import play_count, plays_for
from .personaz import personas_of
from .views import credit_owner

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


# One reader, in clientip.py. This was a local copy that took
# X-Forwarded-For[0] — the entry the CALLER writes — so the cap it feeds was
# keyed on a value the person being capped chooses.
from .clientip import client_ip as _client_ip


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


# "nobody passed one", as distinct from "looked, and there is no take". The
# feed resolves every size in one query and passes the answer — including None
# — so it must not be re-read per row; a single-post response passes nothing and
# gets it looked up here, because a card that can't state the coach's ceiling
# sends the member at the button to find out.
_UNSET = object()


def _bought_ids(request, ids):
    """Which of `ids` this member has bought — one query for a whole feed."""
    u = getattr(request, "user", None)
    if not ids or not getattr(u, "is_authenticated", False):
        return set()
    from .models import PostSale
    return set(PostSale.objects.filter(buyer_id=u.id, post_id__in=ids)
               .values_list("post_id", flat=True))


# What a post may be priced at, in cents. 0 is free.
POST_PRICE_MIN_CENTS = 100
POST_PRICE_MAX_CENTS = 50000


def clean_post_price(value):
    """Cents, or None for free. Raises ValueError with a member-facing reason."""
    try:
        cents = int(value or 0)
    except (TypeError, ValueError):
        raise ValueError("Price must be a whole number of cents.")
    if cents <= 0:
        return None
    if not POST_PRICE_MIN_CENTS <= cents <= POST_PRICE_MAX_CENTS:
        raise ValueError(f"Price must be between ${POST_PRICE_MIN_CENTS/100:.2f} "
                         f"and ${POST_PRICE_MAX_CENTS/100:.2f}, or free.")
    return cents


def _post_dict(p, request, up=0, down=0, collabs=None, price=None, take_state=_UNSET,
               cap=None, shares=None, joins=None, rating=_UNSET, bought=_UNSET,
               plays=None, marks=_UNSET):
    vibe = up - down
    # Thorough marks (thoroughz.py): the author's and any credited
    # contributor's, by name. A list passes them in one batch; a single post
    # costs the two queries here.
    if marks is _UNSET:
        marks = marks_for_posts([p])
    media = media_slots(p)
    if take_state is _UNSET:
        take_state = take_state_for([(p, media)]).get(p.id)
    take_bytes = (take_state or {}).get("bytes")
    # Known gone, because something went and looked — never because a player
    # failed. See crosspost.take_state_for.
    take_missing = bool((take_state or {}).get("missing"))
    n_collabs = p.collab_deals.count() if collabs is None else collabs
    flagged = down >= HIDE_FLAG_MIN_DOWN and down >= up * HIDE_FLAG_RATIO
    # What THIS viewer may see of the coach's read. Decided in one place
    # (coachshare.coach_read_for), costs no query, and is the only thing that
    # may put read content into this dict — `score` below is derived from it.
    coach = coach_read_for(p, request.user)
    return {
        "id": p.id,
        "author": p.author.username,
        "author_mark": marks.get(p.author.username),
        "contributor_marks": {c["username"]: marks[c["username"]]
                              for c in (p.contributors or [])
                              if isinstance(c, dict) and c.get("username") in marks},
        # True for everyone credited, not just whoever pressed post — a
        # collab post belongs to all of them.
        "mine": owns_post(p, request.user),
        "contributors": p.contributors or [],
        "co_owned": bool(p.contributors),
        "title": p.title,
        "derived": p.derived or None,
        "description": p.description,
        "links": p.links,
        "media_type": p.media_type,
        "media_url": p.media_url,
        "is_album": p.is_album,
        "items": p.items or [],
        "embeds": p.embeds or [],
        # Listens counted on Music ConnectZ from the embedded SoundCloud player
        # (embedplays.py) — never SoundCloud's own number. 0 = say nothing.
        "mcz_plays": play_count(p) if plays is None else plays,
        # One of each, resolved for the client so it renders every attachment
        # rather than only the primary one.
        "media": media,
        # The recording this post carries is not in storage any more. The row
        # outlived the bytes, so the card must say so instead of rendering a
        # player that sits at 0:00 and explains nothing — and it has to say it
        # HERE, next to the post, where the member might still have the file.
        "take_missing": take_missing,
        # Which slot the lost recording filled, so the client replaces that
        # player and leaves the ones that still work alone.
        "take_kind": (take_state or {}).get("kind", "") if take_missing else "",
        "slots": list(MEDIA_SLOTS),
        # The legacy key: the whole stored read, but only when `coach` says it
        # is shown. A viewer the read was refused gets nothing in either place.
        "score": legacy_score(p, coach),
        # {state: none|locked|shown, read?, reason?, visibility? (author only)}
        "coach": coach,
        "genre": p.genre,
        # A flag beside the genre, never instead of it — a freestyle Trap verse
        # is still Trap, and ChartZ must still be able to slice it as Trap.
        "freestyle": p.freestyle,
        "skills_used": p.skills_used or [],
        "visibility": p.visibility,
        # Buy: the price is on the card so the button can carry it BEFORE it
        # is pressed. None/0 is free. `bought` is batched by the feeds.
        "price_cents": p.price_cents or 0,
        "bought": (_bought_ids(request, [p.id]).__contains__(p.id)
                   if bought is _UNSET else bool(bought)),
        "gates": p.gates,
        "allow_in_playlists": p.allow_in_playlists,
        # Age from the SERVER's clock, so the client's unlock countdowns can't
        # drift from the checks the API actually runs.
        "age_sec": int((timezone.now() - p.created_at).total_seconds()),
        "rate_unlock_sec": POST_RATE_UNLOCK_SEC,
        "comment_unlock_sec": POST_COMMENT_UNLOCK_SEC,
        # How long the author can still edit this post.
        #
        # `getattr`, not `p.author.membership.tier`. A Membership row is made
        # lazily by `membership_for()`, so an author who has never been near a
        # path that creates one simply has not got one — and the bare access
        # raised RelatedObjectDoesNotExist, which is a 500 on every response
        # carrying that post: the feed, the post itself, every edit and rate
        # reply. It is the pattern social.py already uses for the same column,
        # and it works because Django makes that exception a subclass of
        # AttributeError precisely so `getattr` can absorb it.
        #
        # No tier means the free window, which is what a member with no
        # membership row effectively has.
        "edit_unlock_sec": edit_window_for(getattr(getattr(p.author, "membership", None), "tier", None)),
        # PostZ is for show, CollabZ is for collaboration — this is the count
        # of times somebody moved from one to the other on this post, and where
        # the client sends them to do it again.
        "collab_count": n_collabs,
        # Nothing is a dead end. `open_in` is the first door and stays a plain
        # string for anything already reading it; `destinations` is the whole
        # list — every app this post can open in, what happens there, what it
        # costs before it is spent, and what it still needs when it can't go.
        "open_in": "collabz",
        "destinations": destinations_for(p, request.user, media,
                                         price=price, collabs=n_collabs,
                                         take_bytes=take_bytes, cap=cap,
                                         take_missing=take_missing),
        "skill_cost_cents": p.skill_cost_cents,
        # Three more per-card counts, batched by the caller for the same
        # reason `collabs` and `take_state` above already were: the feed
        # serves up to 300 posts and re-polls every 30 seconds, so each of
        # these was one query per card per poll. `joins` hid behind a
        # `restricted` check, which is why a feed of public posts measured two
        # N+1s and a real one had three.
        #
        # None/_UNSET keeps the single-post callers (create, edit, detail)
        # working unchanged — one extra query on one post is not worth a
        # batching call site.
        "joins": (p.joins.count() if p.visibility == "restricted" else 0) if joins is None else joins,
        "shares": p.shares.count() if shares is None else shares,
        "up": up, "down": down, "vibe": vibe, "flagged": flagged,
        "boosted": bool(p.boosted_until and p.boosted_until > timezone.now()),
        "boost_cost_energy": BOOST_ENERGY,
        "boosted_until": p.boosted_until.isoformat() if p.boosted_until else None,
        "rating": item_rating_median(f"post:{p.id}") if rating is _UNSET else rating,
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
    """{skill name: price_cents} from the member's own PersonaZ skills.

    Every price still counts here whatever its unit, so nobody's costs moved when the unit
    arrived; `skill_price_units` says what each one is per, and the quote carries it."""
    from .models import profile_for
    out = {}
    for persona in personas_of(profile_for(user)):
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


def skill_price_units(user):
    """{skill name: "hour" | "work"} for the priced skills — what each price is PER."""
    from .models import profile_for
    from .personaz import rate_unit_of
    out = {}
    for persona in personas_of(profile_for(user)):
        for s in (persona.get("skills") or []):
            if isinstance(s, dict) and s.get("name") and int(s.get("rate_cents") or 0) > 0:
                out.setdefault(str(s["name"]).strip(), rate_unit_of(s))
    return out


def post_cost_cents(user, skills_used, floor=None):
    """What posting this costs: the combined price of the skills that went in.

    Computed HERE, from the member's own rates, never taken from the request.
    The composer sent no cost at all, so every post in the app has been free
    while the screen implied otherwise — and a client-supplied price is a price
    the client can set to zero anyway.

    Returns (total_cents, breakdown) so the cost can be SHOWN before the button
    rather than discovered by pressing it.
    """
    prices = skill_prices(user)
    units = skill_price_units(user)
    lines, total = [], 0
    for name in (skills_used or [])[:40]:
        if not isinstance(name, str):
            continue
        cents = prices.get(name.strip(), 0)
        line = {"skill": name.strip(), "cents": cents}
        if cents:
            line["unit"] = units.get(name.strip(), "hour")      # said beside the price, never assumed
        lines.append(line)
        total += cents
    # BadgeZ reads here, where the price is decided — the Gifted badge's
    # discount would be a sticker anywhere else.
    from .models import badge_effects
    off = badge_effects(user).get("post_discount_pct", 0)
    if off and total:
        total = max(0, total - int(total * off / 100))
    # Every POST costs at least the floor. Submissions that refuse when short
    # (battles, collabs, venues) pass floor=0: a floor there would be a wall.
    floor = POST_ENERGY_FLOOR if floor is None else floor
    if total < floor:
        lines.append({"skill": "Posting", "cents": floor - total})
        total = floor
    return total, lines


HABIT_SHARE = 0.65      # the remembered-choices bar: a skill is a habit at 65% of posts
HABIT_MIN_POSTS = 5


def suggest_skills(user):
    """(skills, source) a new post of this member's would most likely list.

    Same rule as every remembered field: if at least HABIT_MIN_POSTS recent
    posts exist, a skill used in HABIT_SHARE of them is a habit and they are all
    suggested — so a producer / mix engineer / artist who does everything alone
    gets the whole stack, because every one of their posts lists it. Below that
    bar the LAST post's skills win. With no history at all, their declared
    (priced) skills are the default. It only suggests: the member edits the list
    before publishing, and the price follows the list.
    """
    recent = [list(sk) for sk in
              Post.objects.filter(author=user).order_by("-created_at")
              .values_list("skills_used", flat=True)[:30]
              if isinstance(sk, list) and sk]
    if len(recent) >= HABIT_MIN_POSTS:
        counts = {}
        for sk in recent:
            for name in set(str(x).strip()[:80] for x in sk if str(x).strip()):
                counts[name] = counts.get(name, 0) + 1
        habit = [n for n, c in counts.items() if c / len(recent) >= HABIT_SHARE]
        if habit:
            order = {str(x).strip()[:80]: i for i, x in enumerate(recent[0])}
            return sorted(habit, key=lambda n: order.get(n, 999))[:40], "habit"
    if recent:
        return [str(x).strip()[:80] for x in recent[0] if str(x).strip()][:40], "last"
    return list(skill_prices(user))[:40], "declared"


def skills_from(d, key="skills"):
    """The skill names off a submission payload, bounded the way posts are."""
    return [str(s).strip()[:80] for s in (d.get(key) or []) if str(s).strip()][:40]


def charge_skill_energy(user, skills):
    """Spend the combined price of `skills` as ⚡ on a submission.

    BattleZ, VenueZ and CollabZ all price a submission the same way a post is
    priced, so they charge it through here rather than each keeping their own
    copy — three call sites that each read the wallet, compare and subtract is
    three places for the comparison to drift, and the one that drifts is the one
    nobody re-reads.

    Unlike `create_post`, which lets the post through and takes what is there,
    a submission is REFUSED when it cannot be afforded: an insufficient balance
    has to be a wall for the paradigm to have anything to explain. The refusal
    states the price, the balance and the gap and stops there — where to go earn
    it is `/api/economy/earn/`'s answer, and a second list of ways to earn,
    written out here in prose, is exactly how "20 free prompts" reached nine
    files.

    Caller must be inside a transaction: the wallet is locked so two entries
    submitted at once cannot both pass the check against the same balance.

    Returns (info, refusal). `refusal` is a (payload, status) pair or None,
    matching `create_post`'s error shape.
    """
    cost, lines = post_cost_cents(user, skills, floor=0)
    if not cost:
        return {"energy_cost": 0, "energy_charged": 0}, None

    Wallet.objects.get_or_create(user=user)
    w = Wallet.objects.select_for_update().get(user=user)
    have = max(0, w.energy or 0)
    if have < cost:
        return {}, ({
            "detail": f"This costs {cost} ⚡ and you have {have}.",
            "insufficient": True,
            "resource": "energy",
            "cost": {"resource": "energy", "amount": cost},
            "energy_needed": cost,
            "energy_available": have,
            "energy_short": cost - have,
            "lines": lines,
        }, status.HTTP_402_PAYMENT_REQUIRED)

    w.energy = have - cost
    w.save(update_fields=["energy", "updated_at"])
    return {"energy_cost": cost, "energy_charged": cost, "energy": w.energy}, None


DERIVED_KINDS = ("cover", "remix")


def clean_derived(user, raw):
    """({snapshot}, error). A cover or remix names a PUBLIC post by someone else — credit is the one
    thing it always carries. Nothing is paid to the original here: a royalty split is Corey's call,
    and the screen says so rather than implying one."""
    if not raw:
        return {}, ""
    if not isinstance(raw, dict) or raw.get("kind") not in DERIVED_KINDS:
        return {}, "A cover or remix must say which: cover or remix."
    try:
        orig = Post.objects.select_related("author").filter(pk=int(raw.get("id"))).first()
    except (TypeError, ValueError):
        orig = None
    if not orig or orig.visibility != "public":
        return {}, "That original isn't a public post, so it can't be covered or remixed."
    if orig.author_id == user.id:
        return {}, "That's your own post — post it as new work instead."
    return {"id": orig.id, "kind": raw["kind"], "title": orig.title[:160], "author": orig.author.username}, ""


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
    # A coach read posted WITH the song, and who may see it. Checked before
    # anything below is charged: a token that is not the member's own refuses
    # the whole post and costs nothing, and the read itself costs nothing extra
    # (it was paid for when the coach gave it).
    coach_score, score_vis, coach_err = for_new_post(user, d)
    if coach_err:
        return None, {}, (coach_err, status.HTTP_400_BAD_REQUEST)
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
    if coach_score:
        score = coach_score        # the server's copy of the read, never a body's
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
                {"detail": f"Daily submission limit reached ({used}/{cap}). Upgrade for more, or add {SUBMISSION_PACK} for {SUBMISSION_PACK_ENERGY} \u26a1.",
                 "used": used, "cap": cap},
                status.HTTP_429_TOO_MANY_REQUESTS,
            )
    # Posting costs energy = combined skill price (cents). Deduct what's there.
    w = wallet_for(user)
    charged = min(cost, max(0, w.energy))
    if charged:
        w.energy -= charged
        w.save(update_fields=["energy", "updated_at"])
        from .models import Transaction, log_resource
        log_resource(user, Transaction.RES_ENERGY, -charged, f"Post: {title[:60]}",
                     app_key="postz", target="postz:compose")
    derived, derr = clean_derived(user, d.get("derived"))
    if derr:
        return None, {}, ({"detail": derr}, status.HTTP_400_BAD_REQUEST)
    p = Post.objects.create(
        author=user, title=title, derived=derived,
        description=str(d.get("description", ""))[:4000],
        links=d.get("links") or [], media_type=media_type, media_url=media_url,
        is_album=is_album, items=items,
        score=score, score_visibility=score_vis, visibility=vis, skill_cost_cents=cost,
        genre=str(d.get("genre", ""))[:40],
        freestyle=freestyle,
        skills_used=skills,
        allow_in_playlists=bool(d.get("allow_in_playlists", True)),
        gates=clean_gates(d.get("gates")),
    )
    if is_submission:
        record_submission(user)

    # ZodiacZ. Four signs are nudged at something a post can be, so they are
    # decided here where the post's shape is already known rather than by four
    # callers each re-deriving it. `try_award` no-ops for every other sign.
    from .signbonus import try_award
    if freestyle:                                   # Pisces — out of nowhere
        try_award(user, "freestyle",
                  stretch=Post.objects.filter(author=user, freestyle=True).count() >= 3)
    if score:                                       # Scorpio — judged on purpose
        try:
            overall = int(score.get("score") or 0)
        except (TypeError, ValueError):
            overall = 0
        try_award(user, "post_scored", stretch=overall >= 8)
    if len(items) > 1:                              # Gemini — more than one work
        try_award(user, "post_album", stretch=len(items) >= 4)
    if skills:                                      # Virgo — named the craft
        try_award(user, "post_with_skills", stretch=len(skills) >= 3)

    return p, {"energy_charged": charged, "energy": w.energy}, None


class VisibilityRefused(Exception):
    def __init__(self, payload, status):
        super().__init__(payload.get("detail", ""))
        self.payload, self.status = payload, status


def change_visibility(user, p, new_vis, *, share_private_track=False, strict_funds=False,
                      backdate_to=None):
    """THE one way a post's visibility changes (PostZ edit and the SoundCloud
    library manager both come through here).

    Leaving private is the first moment a post can reach anybody, so that is
    where the shortfall of its skill cost is charged (imports owe nothing: no
    skills). A track private on SoundCloud needs `share_private_track`.
    `strict_funds` refuses (402) instead of taking what is there, for batches.
    `backdate_to` only ever moves created_at EARLIER, never later, so it cannot
    bump a post or re-earn the fresh-post royalty boost.
    Returns {"was", "now", "charged", "owed", "backdated"}.
    """
    with transaction.atomic():
        row = Post.objects.select_for_update().get(pk=p.pk)
        p.visibility, p.skill_cost_cents = row.visibility, row.skill_cost_cents
        was = p.visibility
        leaving = was == "private" and new_vis != "private"
        if leaving:
            from .soundcloud_import import has_private_track
            if has_private_track(p) and not share_private_track:
                raise VisibilityRefused({
                    "detail": "This track is private on SoundCloud. Publishing shares its secret "
                              "link with everyone who can see the post.",
                    "needs_confirm": "share_private_track",
                }, status.HTTP_409_CONFLICT)
        charged = owed = 0
        fields = ["visibility"]
        if leaving:
            cost, _lines = post_cost_cents(user, p.skills_used)
            owed = max(0, cost - p.skill_cost_cents)
            if owed:
                Wallet.objects.get_or_create(user=user)
                w = Wallet.objects.select_for_update().get(user=user)
                have = max(0, w.energy or 0)
                if strict_funds and have < owed:
                    raise VisibilityRefused({
                        "detail": f"Publishing this costs {owed} \u26a1 more and you have {have}. Nothing was charged.",
                        "insufficient": True, "energy_needed": owed, "energy_available": have,
                    }, status.HTTP_402_PAYMENT_REQUIRED)
                charged = min(owed, have)
                if charged:
                    w.energy = have - charged
                    w.save(update_fields=["energy", "updated_at"])
                    p.skill_cost_cents += charged
                    fields.append("skill_cost_cents")
                    log_resource(user, Transaction.RES_ENERGY, -charged,
                                 note=f"Published '{p.title}' (post #{p.id})"[:200],
                                 app_key="postz", target=f"postz:{p.id}")
        p.visibility = new_vis
        p.save(update_fields=fields)
        backdated = False
        if leaving and backdate_to and backdate_to < p.created_at:
            Post.objects.filter(pk=p.pk).update(created_at=backdate_to)
            p.created_at = backdate_to
            backdated = True
    return {"was": was, "now": new_vis, "charged": charged, "owed": owed, "backdated": backdated}


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

    def _state(self, user):
        cap = submission_cap_for(user)
        used = submissions_used_today(user)
        row = DailySubmission.objects.filter(user=user, day=timezone.localdate()).first()
        packs = (row.bonus // SUBMISSION_PACK) if row else 0
        return {"used": used, "cap": cap, "remaining": max(0, cap - used),
                # What more costs, said before it is pressed: a pack adds to TODAY only.
                "buy": {"pack": SUBMISSION_PACK, "cost_energy": SUBMISSION_PACK_ENERGY,
                        "packs_left": max(0, SUBMISSION_PACKS_MAX - packs),
                        "energy": max(0, wallet_for(user).energy or 0)}}

    def get(self, request):
        return Response(self._state(request.user))

    def post(self, request):
        """Buy one pack of extra submissions for today."""
        user = request.user
        with transaction.atomic():
            row, _ = DailySubmission.objects.select_for_update().get_or_create(user=user, day=timezone.localdate())
            if row.bonus // SUBMISSION_PACK >= SUBMISSION_PACKS_MAX:
                return Response({"detail": f"You have already added the most extra submissions allowed today "
                                           f"({SUBMISSION_PACK * SUBMISSION_PACKS_MAX}). Nothing was charged.",
                                 **self._state(user)}, status=status.HTTP_400_BAD_REQUEST)
            if spend_energy(user, SUBMISSION_PACK_ENERGY, f"{SUBMISSION_PACK} more submissions today",
                            app_key="postz", target="postz:submissions") is None:
                have = max(0, wallet_for(user).energy or 0)
                return Response({
                    "detail": f"{SUBMISSION_PACK} more submissions cost {SUBMISSION_PACK_ENERGY} \u26a1 and you have {have}. Nothing was charged.",
                    "insufficient": True, "resource": "energy",
                    "cost": {"resource": "energy", "amount": SUBMISSION_PACK_ENERGY},
                    "energy_needed": SUBMISSION_PACK_ENERGY, "energy_available": have,
                    "energy_short": SUBMISSION_PACK_ENERGY - have,
                }, status=status.HTTP_402_PAYMENT_REQUIRED)
            row.bonus += SUBMISSION_PACK
            row.save(update_fields=["bonus"])
        return Response({**self._state(user), "bought": SUBMISSION_PACK})


def _boost_state(post, user):
    """What boosting this post would do right now, said before it is pressed."""
    now = timezone.now()
    until = post.boosted_until if post.boosted_until and post.boosted_until > now else None
    base = until or now
    new_until = base + timedelta(hours=BOOST_HOURS)
    ahead = (new_until - now).total_seconds() / 3600
    why = ""
    if post.author_id != user.id:
        why = "You can only boost your own post."
    elif post.visibility not in ("public", ""):
        why = "Only a public post can be boosted: a private or members-only post is not in the open feed."
    elif ahead > BOOST_MAX_AHEAD_HOURS:
        why = f"It is already boosted for more than {BOOST_MAX_AHEAD_HOURS - BOOST_HOURS} hours. Come back when that is nearly up."
    return {"cost_energy": BOOST_ENERGY, "hours": BOOST_HOURS, "slots": BOOST_SLOTS,
            "boosted_until": until.isoformat() if until else None,
            "new_until": new_until.isoformat(), "allowed": not why, "why_not": why,
            "energy": max(0, wallet_for(user).energy or 0),
            "what_you_get": f"A place near the top of the feed for {BOOST_HOURS} hours, labelled Boosted. "
                            "It buys visibility only: it does not change ratings, plays or royalties. "
                            f"At most {BOOST_SLOTS} boosted posts lead the feed at once."}


class PostBoostView(APIView):
    """GET /postz/<id>/boost/ — the price and whether it can be bought. POST — boost it."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        post = Post.objects.filter(pk=pk).first()
        if not post or (post.author_id != request.user.id and post.visibility not in ("public", "")):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_boost_state(post, request.user))

    def post(self, request, pk):
        post = Post.objects.filter(pk=pk, author=request.user).first()
        if not post:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        st = _boost_state(post, request.user)
        if not st["allowed"]:
            return Response({"detail": st["why_not"], **st}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            if spend_energy(request.user, BOOST_ENERGY, f"Boost: {post.title[:60]}",
                            app_key="postz", target=f"post:{post.id}") is None:
                have = st["energy"]
                return Response({
                    "detail": f"Boosting costs {BOOST_ENERGY} \u26a1 and you have {have}. Nothing was charged.",
                    "insufficient": True, "resource": "energy",
                    "cost": {"resource": "energy", "amount": BOOST_ENERGY},
                    "energy_needed": BOOST_ENERGY, "energy_available": have,
                    "energy_short": BOOST_ENERGY - have,
                }, status=status.HTTP_402_PAYMENT_REQUIRED)
            Post.objects.filter(pk=post.pk).update(boosted_until=timezone.now() + (
                (post.boosted_until - timezone.now() if post.boosted_until and post.boosted_until > timezone.now()
                 else timedelta(0)) + timedelta(hours=BOOST_HOURS)))
        post.refresh_from_db()
        return Response({**_boost_state(post, request.user), "boosted": True})


class PostsView(APIView):
    """GET the visible feed; POST creates a post (charges the skill-cost energy).

    sort=hot (default, vibe×recency), new (chronological), or top (by rating).
    Likes/dislikes rank reach here; ratings drive value elsewhere.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        sort = (request.query_params.get("sort") or "hot").lower()
        qs = Post.objects.select_related("author", "author__membership").exclude(visibility="private").order_by("-created_at")[:300]
        # ?mine=1 — only my own posts, all of them rather than the newest 300
        # platform-wide. DistributeZ starts a release from one of YOUR posts,
        # and an older track must not fall out of reach because the platform
        # grew past it (the same bug CollabParticipant fixed for deals).
        if request.query_params.get("mine") in ("1", "true"):
            qs = Post.objects.select_related("author", "author__membership").filter(
                author=request.user).exclude(visibility="private").order_by("-created_at")[:500]
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
        # What a coached take costs this member, read ONCE. Every card offers
        # SingZ and RapZ, and pricing each of them per row would be two hundred
        # wallet reads to print the same two numbers.
        price = coach_price(request.user)
        # The take ceiling for this member, read once for the same reason the
        # price is: it reads their membership row, and every card shows it.
        cap = coach_cap(request.user)
        # How big each post's take is, in one query for the whole feed. Without
        # it the coach door is offered on a track the coach cannot read, and the
        # member finds out by pressing the button — see take_state_for.
        sizes = take_state_for([(p, media_slots(p)) for p in visible])
        ids = [p.id for p in visible]
        # The last three per-card counts. Each was one query per post on a
        # feed that re-polls every 30 seconds: measured at 2 queries per post
        # and 108 queries for 50 posts before this, which is ~3.6 queries a
        # second of idle load from a single open tab.
        shares = dict(PostShare.objects.filter(post_id__in=ids)
                      .values_list("post_id").annotate(n=Count("id")))
        joins = dict(PostJoin.objects.filter(post_id__in=ids)
                     .values_list("post_id").annotate(n=Count("id")))
        ratings = item_rating_medians([f"post:{i}" for i in ids])
        bought = _bought_ids(request, ids)
        plays = plays_for(visible)
        marks = marks_for_posts(visible)
        posts = [_post_dict(p, request, *reactions.get(p.id, (0, 0)),
                            marks=marks,
                            collabs=deals.get(p.id, 0), price=price, cap=cap,
                            take_state=sizes.get(p.id),
                            shares=shares.get(p.id, 0),
                            joins=joins.get(p.id, 0) if p.visibility == "restricted" else 0,
                            rating=ratings.get(f"post:{p.id}"),
                            bought=p.id in bought,
                            plays=plays.get(p.id, 0))
                 for p in visible]

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
        # Paid placement: up to BOOST_SLOTS active boosted posts lead, most recently
        # boosted first, and every one says so on its card. The rest keep their place.
        live = sorted((d for d in posts if d["boosted"] and not d["flagged"]),
                      key=lambda d: d["boosted_until"], reverse=True)[:BOOST_SLOTS]
        if live:
            lead = {d["id"] for d in live}
            posts = live + [d for d in posts if d["id"] not in lead]
        from .ratez import rating_reward
        return Response({"posts": posts[:100], "sort": sort,
                         "rating_reward": rating_reward(request.user)})

    def post(self, request):
        d = request.data
        # A body never supplies the coach's read. `score` is what a post shows as
        # "the coach gave this 9/10", so a number typed into a request would be
        # a forged one — a read is attached from the member's own ScoreShare by
        # `coach_token` (create_post) or postz/<id>/coach/. Server-built callers
        # of create_post (OCC's provenance) still pass their own `score`.
        if "score" in d:
            d = {k: v for k, v in d.items() if k != "score"}
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
        if "score_visibility" in d:
            # Who may see the coach's read: a setting about a score, held to no
            # edit window. The AUTHOR's alone — the platform owner may fix a
            # broken media link on anyone's post, but who gets to see somebody's
            # score is their privacy, not a repair.
            if not mine:
                return Response({"detail": "Only the member who published this can change who "
                                           "sees its coach read."},
                                status=status.HTTP_403_FORBIDDEN)
            new_cv, bad = clean_visibility(d["score_visibility"])
            if bad or new_cv is None:
                return Response({"detail": bad or "Choose who sees the coach's read."},
                                status=status.HTTP_400_BAD_REQUEST)
            p.score_visibility = new_cv
            p.save(update_fields=["score_visibility"])
            # Handled; what is left of the request is judged as if it were not there.
            d = {k: v for k, v in d.items() if k != "score_visibility"}
            if len(d) <= 1:            # edit_id alone
                return Response(_post_dict(p, request))
        # Playlist consent is a SETTING, not content, so it is not held to the
        # tier's edit window. Locking an author out of withdrawing their work
        # four minutes after posting would make the switch useless.
        if "allow_in_playlists" in d:
            p.allow_in_playlists = bool(d["allow_in_playlists"])
            p.save(update_fields=["allow_in_playlists"])
            if len(d) <= 2:            # edit_id + the flag: nothing else to do
                return Response(_post_dict(p, request))
        if "price_cents" in d:
            # A setting, like visibility: pricing old work is the point.
            # Only the publisher prices it — every credited member is paid.
            if not mine:
                return Response({"detail": "Only the member who published this can price it."},
                                status=status.HTTP_403_FORBIDDEN)
            try:
                p.price_cents = clean_post_price(d["price_cents"])
            except ValueError as e:
                return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            p.save(update_fields=["price_cents"])
            if len(d) <= 2:
                return Response(_post_dict(p, request))
        if "visibility" in d:
            # Also a SETTING, not content, and held to no edit window for the
            # same reason `allow_in_playlists` isn't — a private import sitting
            # for two years must still be publishable. Junk is ignored rather
            # than defaulting to "public" the way creation does: a typo here
            # should never be the thing that publishes a draft.
            new_vis = str(d.get("visibility") or "").strip().lower()
            if new_vis in dict(Post.VIS_CHOICES):
                try:
                    change_visibility(request.user, p, new_vis,
                                      share_private_track=bool(d.get("share_private_track")))
                except VisibilityRefused as refused:
                    return Response(refused.payload, status=refused.status)
            # edit_id + visibility (+ the private-track confirmation): nothing
            # else to do. Counting the confirmation would push a plain publish
            # into the content-edit path and its edit window.
            if len([k for k in d if k != "share_private_track"]) <= 2:
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


class PostOpenView(APIView):
    """GET /api/economy/postz/<pk>/open/ — where this post can go next.

    The feed already carries the same list on every row, so this exists for the
    surfaces that hold ONE post (a shared /p/ link, a card reopened after an
    edit) and for re-reading a price that moves during a session: today's free
    prompts run out while you are scrolling, and a menu still offering "free"
    after the last one was spent is quoting a price that no longer exists.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        p = Post.objects.filter(pk=pk).select_related("author", "author__membership").first()
        if not p:
            return Response({"detail": "post not found"}, status=status.HTTP_404_NOT_FOUND)
        if not can_view_post(p, request.user):
            return Response({"detail": "you can't view this post"},
                            status=status.HTTP_403_FORBIDDEN)
        media = media_slots(p)
        state = take_state_for([(p, media)]).get(p.id) or {}
        dests = destinations_for(p, request.user, media,
                                 collabs=p.collab_deals.count(),
                                 take_bytes=state.get("bytes"),
                                 take_missing=bool(state.get("missing")))
        return Response({
            "post_id": p.id,
            "title": p.title,
            "destinations": dests,
            # Said plainly rather than left to be counted off the list: a member
            # looking at a lyrics-only post should read why the coach is greyed
            # out, not conclude the feature is broken.
            "open_count": sum(1 for d in dests if d["available"]),
        })


class PostJoinView(APIView):
    """Record a join on a restricted post. First join from a distinct non-author
    IP rewards the author 300 SpinAZ. Repeat calls update active time only."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        p = Post.objects.filter(pk=pk).select_related("author", "author__membership").first()
        if not p:
            return Response({"detail": "post not found"}, status=status.HTTP_404_NOT_FOUND)
        if p.visibility != "restricted":
            return Response({"detail": "post is not restricted"}, status=status.HTTP_400_BAD_REQUEST)
        if p.gates and request.user.id != p.author_id:
            from .models import profile_for
            ap = profile_for(p.author)
            origin = (ap.lat, ap.lng) if (ap.share_location and ap.lat is not None) else (None, None)
            failed = failing_gate(member_metrics(profile_for(request.user), origin), p.gates)
            if failed:
                return Response(refusal(failed, p.gates), status=status.HTTP_403_FORBIDDEN)
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
        from .postsplit import post_shares
        for who, share, _b in post_shares(p, RESTRICTED_JOIN_REWARD_SPINAZ):
            if share > 0:
                award_spinaz(who, share, note=f"Restricted join on '{p.title}'", app_key="postz")
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
        p = Post.objects.filter(pk=pk).select_related("author", "author__membership").first()
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
        p = Post.objects.filter(pk=pk).select_related("author", "author__membership").first()
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


class PostProgressionView(APIView):
    """GET /api/economy/postz/<pk>/progression/ — progress toward BattleZ/CollabZ.

    Returns what's needed to unlock each tier and current progress.
    Drives UI that shows progress bars and "X of 5 ratings needed" messaging.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        p = Post.objects.filter(pk=pk).select_related("author", "author__membership").first()
        if not p:
            return Response({"detail": "post not found"}, status=status.HTTP_404_NOT_FOUND)
        if not can_view_post(p, request.user):
            return Response({"detail": "you can't view this post"}, status=status.HTTP_403_FORBIDDEN)

        # THREE bugs lived in these two lines, and the tab they broke is the
        # one every member lands on after signing in.
        #
        # `p.ratings` is not a relation — a Post has no reverse accessor by
        # that name, because a rating is an `ItemRating` keyed by the opaque
        # "post:<id>" the whole social layer uses. It raised AttributeError,
        # so this endpoint answered 500 for every post card on the feed.
        #
        # `item_rating_median(p)` was handed the POST where every other caller
        # in the codebase passes that same item key string. Filtering
        # `item_id=<Post object>` matches nothing, so it returned None and the
        # `or 0.0` turned it into a number — which means the CollabZ progress
        # on this endpoint has been a hard zero for its whole life, and would
        # have stayed zero and looked deliberate if the line above it had not
        # been loud enough to 500.
        item = f"post:{p.id}"
        rating_count = ItemRating.objects.filter(item_id=item).count()
        rating_avg = item_rating_median(item) or 0.0

        battle_needed = BATTLE_RATING_THRESHOLD
        collab_needed = post_collab_threshold(p)

        battle_eligible = post_is_battle_eligible(p)
        collab_eligible = post_is_collab_eligible(p)

        return Response({
            "post_id": p.id,
            "battle": {
                "needed": battle_needed,
                "current": rating_count,
                "eligible": battle_eligible,
                "eligible_at": p.battle_eligible_at.isoformat() if p.battle_eligible_at else None,
                "progress_percent": min(100, round((rating_count / battle_needed) * 100)) if battle_needed > 0 else 0,
            },
            "collab": {
                "needed": collab_needed,
                "current": rating_avg,
                "eligible": collab_eligible,
                "eligible_at": p.collab_eligible_at.isoformat() if p.collab_eligible_at else None,
                "progress_percent": min(100, round((rating_avg / collab_needed) * 100)) if collab_needed > 0 else 0,
            },
        })


class DiscoveryFeedView(APIView):
    """GET personalized discovery feed based on listening behavior.

    Returns posts tailored to the member's taste:
    - Posts from members with similar listening patterns
    - Ranked by creator affinity, post quality, and recency
    - Excludes posts they've already heard

    This solves: "How do I discover new music I'll actually like?"
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get personalized discovery recommendations."""
        from .discoveryengine import recommendations_for, genre_recommendations_for

        genre = request.query_params.get("genre")
        limit = min(100, int(request.query_params.get("limit", 30)))

        # Get recommendations (either personalized or genre-based)
        if genre:
            recommendations = genre_recommendations_for(request.user, genre, limit)
        else:
            recommendations = recommendations_for(request.user, limit)

        # Format the response like the main feed does
        if not recommendations:
            return Response({"posts": [], "kind": "discovery"})

        reactions = _reactions_for([p.id for p in recommendations])
        deals = dict(
            CollabDeal.objects.filter(source_post_id__in=[p.id for p in recommendations])
            .values_list("source_post_id")
            .annotate(n=Count("id"))
        )
        price = coach_price(request.user)
        cap = coach_cap(request.user)
        sizes = take_state_for([(p, media_slots(p)) for p in recommendations])
        ids = [p.id for p in recommendations]
        shares = dict(PostShare.objects.filter(post_id__in=ids)
                      .values_list("post_id").annotate(n=Count("id")))
        joins = dict(PostJoin.objects.filter(post_id__in=ids)
                     .values_list("post_id").annotate(n=Count("id")))
        ratings = item_rating_medians([f"post:{i}" for i in ids])
        bought = _bought_ids(request, ids)
        plays = plays_for(recommendations)
        marks = marks_for_posts(recommendations)

        posts = [_post_dict(p, request, *reactions.get(p.id, (0, 0)),
                            marks=marks,
                            collabs=deals.get(p.id, 0), price=price, cap=cap,
                            take_state=sizes.get(p.id),
                            shares=shares.get(p.id, 0),
                            joins=joins.get(p.id, 0) if p.visibility == "restricted" else 0,
                            rating=ratings.get(f"post:{p.id}"),
                            bought=p.id in bought,
                            plays=plays.get(p.id, 0))
                 for p in recommendations]

        return Response({
            "posts": posts,
            "kind": "discovery",
            "note": f"Recommended based on {genre or 'your taste'}"
        })


class PostSaleView(APIView):
    """Buy a post — real money, paid to everyone credited on it.

    GET is the quote: the price, the buyer's balance, and where the money
    goes (the platform fee and what the creators get), so the button can say
    all of it before it is pressed. POST buys, atomically.
    """

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _split(post):
        fee, net = split_cents(post.price_cents or 0,
                               DEV_TAX[membership_for(post.author).tier])
        return fee, net

    def get(self, request, pk):
        post = Post.objects.filter(pk=pk).select_related("author").first()
        if not post:
            return Response({"detail": "Post not found"}, status=status.HTTP_404_NOT_FOUND)
        is_author = post.author_id == request.user.id
        bought = post.sales.filter(buyer_id=request.user.id).exists()
        fee, net = self._split(post)
        from .postsplit import post_shares
        return Response({
            "price_cents": post.price_cents or 0,
            "is_author": is_author,
            "bought": bought,
            "has_access": is_author or bought,
            "balance_cents": wallet_for(request.user).money_cents or 0,
            "fee_cents": fee,
            "creators_cents": net,
            "paid_to": [{"username": who.username, "cents": c, "basis": basis}
                        for who, c, basis in post_shares(post, net) if c > 0],
            "sales": post.sales.count() if is_author else None,
            "min_cents": POST_PRICE_MIN_CENTS, "max_cents": POST_PRICE_MAX_CENTS,
        })

    def post(self, request, pk):
        from django.db import IntegrityError
        from django.db.models import F
        from .models import PostSale, Wallet

        post = Post.objects.filter(pk=pk).select_related("author").first()
        if not post:
            return Response({"detail": "Post not found"}, status=status.HTTP_404_NOT_FOUND)
        if post.author_id == request.user.id:
            return Response({"detail": "You can't buy your own post"},
                            status=status.HTTP_400_BAD_REQUEST)
        price = post.price_cents or 0
        if not price:
            return Response({"detail": "This post is free"}, status=status.HTTP_400_BAD_REQUEST)
        if request.user.post_purchases.filter(post=post).exists():
            return Response({"detail": "You already bought this."},
                            status=status.HTTP_400_BAD_REQUEST)

        wallet_for(request.user)
        fee, net = self._split(post)
        from .postsplit import post_shares
        try:
            with transaction.atomic():
                # Check and debit in ONE statement, so two taps can't both pass
                # the balance check (the old read-modify-write could overdraw).
                moved = Wallet.objects.filter(user=request.user, money_cents__gte=price).update(
                    money_cents=F("money_cents") - price, updated_at=timezone.now())
                if not moved:
                    have = wallet_for(request.user).money_cents or 0
                    return Response(
                        {"detail": f"You need ${price/100:.2f} and have ${have/100:.2f}. "
                                   "Nothing was charged.",
                         "price_cents": price, "balance_cents": have},
                        status=status.HTTP_402_PAYMENT_REQUIRED)
                # unique (post, buyer): a racing second buy fails here and the
                # debit above rolls back with it.
                PostSale.objects.create(post=post, buyer=request.user, price_cents=price)
                for who, cents, basis in post_shares(post, net):
                    if cents <= 0:
                        continue
                    wallet_for(who)
                    Wallet.objects.filter(user=who).update(
                        money_cents=F("money_cents") + cents, updated_at=timezone.now())
                    log_resource(who, Transaction.RES_MONEY, cents,
                                 note=f"Post sale (post #{post.id})"
                                      + ("" if basis == "solo" else f" — your {basis} share"))
                log_resource(request.user, Transaction.RES_MONEY, -price,
                             note=f"Post purchase #{post.id}")
                credit_owner(request.user, fee, f"Post sale platform fee (post #{post.id})")
        except IntegrityError:
            return Response({"detail": "You already bought this. Nothing was charged twice."},
                            status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "success": True,
            "price_cents": price,
            "balance_after": wallet_for(request.user).money_cents,
            "message": f"Bought — {post.author.username} has been paid.",
        }, status=status.HTTP_201_CREATED)
