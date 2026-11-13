"""RateZ — every rating in the app, each one classified for what it is.

Five different things were all called "a rating", and a number with no label is
a number nobody can act on. A member seeing "8.4" had no way to know whether
that was their work, their mixing, their face or them.

    post           the WORK          given directly on a post
    skill          a SKILL you used  derived from the posts that used it
    contribution   your PART of a deal   given by people not on the deal
    overall        YOU               given directly on a profile
    attractiveness YOU               kept apart on purpose

The one that changed: a post rating used to land on the post and stop. It now
lands on the skills that made the post too, for the person who brought each —
so a mix engineer with forty well-rated posts has a rated skill to show for it,
and the price they charge is backed by something.

Nothing here is rated directly except what the member chose to rate. A skill
rating exists only because somebody rated a piece of work that used it, which
is what keeps it a measure of work rather than an opinion about a person.
"""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from .models import (
    ItemRating,
    OverallRating,
    POST_RATE_UNLOCK_SEC,
    Post,
    RATING_KINDS,
    RATING_NOTE,
    RATING_REWARD_DAILY_CAP,
    RATING_REWARD_ENERGY,
    SkillRating,
    _median,
    adult_only_reason,
    attractiveness_median,
    badge_effects,
    can_view_post,
    heard_enough_required,
    item_rating_medians,
    overall_median,
    skill_rating_median,
    Transaction,
)

User = get_user_model()


def skills_of(user):
    """Every skill this member has been rated on, with the median and the count.

    Sorted by how much work is behind it, not by score — a 10 from one rating
    should not outrank a 9 from thirty, and showing the count is what lets a
    reader tell those apart.
    """
    rows = {}
    for r in SkillRating.objects.filter(subject=user).values_list("skill", "score"):
        rows.setdefault(r[0], []).append(r[1])
    out = []
    from . import royaltyfactor as rf
    opted = rf.opted_in(user)
    for skill, scores in rows.items():
        rating, detail = (rf.blended_skill_rating(user, skill) if opted and rf.coach_skill_key(skill)
                          else (skill_rating_median(user, skill), None))
        out.append({
            "skill": skill,
            "rating": rating,
            "count": len(scores),
            "kind": "skill",
            # Said when the AI coach is part of the number, so the rating is never unexplained.
            **({"coach": detail["coach"]} if detail and detail.get("coach") else {}),
        })
    out.sort(key=lambda r: (-r["count"], -(r["rating"] or 0)))
    return out


WORK_PER_SKILL = 5      # how many pieces of work are named beside a skill's rating
WORK_SCAN = 600         # newest rating rows read in total — bounds the work one request can do

DECLARED_NOTE = (
    "Only skills you have added to your profile can be picked here. A skill's rating is the "
    "median of what members scored the posts that used it, and each rating links to that work."
)


def declared_skills(user):
    """The skills this member has LEARNED (declared on their profile), each with its rating
    and the work that earned it. What the "Skills used on this" picker offers.

    The picker used to offer the whole catalogue, so a member could tick a skill they had never
    said they had, and the skill rating then landed on a claim nobody had made. Now the list IS
    the profile: a skill not on it is not here, and the way to get it here is PersonaZ.

    The rating is the same number everywhere (`skills_of`, which is `skill_rating_median` and the
    opt-in coach blend), never a second formula. `None`, never 0, when nothing has rated it yet —
    an empty rating invites a real one and a fake one ends the question.

    Work is read from the rating rows (`SkillRating.item_id`), so a link is only ever to a post
    that actually produced a rating, and only one this member may open.
    """
    from .models import profile_for
    from .personaz import personas_of

    personas = personas_of(profile_for(user))
    seen, names = set(), []
    for persona in personas:
        for s in persona.get("skills") or []:
            name = str((s or {}).get("name") or "").strip()[:60] if isinstance(s, dict) else ""
            if name and name not in seen:
                seen.add(name)
                names.append(name)

    rated = {r["skill"]: r for r in skills_of(user) if r["skill"] in seen}

    # Which posts gave each skill its rating: one query for the rows, one for the posts.
    rows = list(SkillRating.objects.filter(subject=user, skill__in=names, item_id__startswith="post:")
                .order_by("-created_at").values_list("skill", "item_id", "score")[:WORK_SCAN])
    by_pair = {}
    for skill, item_id, score in rows:
        pid = item_id.split(":", 1)[1]
        if pid.isdigit():
            by_pair.setdefault((skill, int(pid)), []).append(score)
    posts = {p.id: p for p in Post.objects.filter(pk__in={pid for _, pid in by_pair})}
    work = {}
    for (skill, pid), scores in by_pair.items():           # newest first, as read
        p = posts.get(pid)
        if p is None or not can_view_post(p, user):        # a deleted or unopenable post is no link
            continue
        scores = sorted(scores)
        n = len(scores)
        work.setdefault(skill, []).append({
            "id": p.id, "title": p.title, "url": f"/p/{p.id}", "item_key": f"post:{p.id}",
            "rating": scores[n // 2] if n % 2 else round((scores[n // 2 - 1] + scores[n // 2]) / 2, 1),
            "count": n,
        })

    out, claimed = [], set()
    for persona in personas:
        skills = []
        for s in persona.get("skills") or []:
            name = str((s or {}).get("name") or "").strip()[:60] if isinstance(s, dict) else ""
            if not name or name in claimed:
                continue
            claimed.add(name)
            r = rated.get(name)
            pieces = sorted(work.get(name, []), key=lambda w: -w["count"])   # stable: ties stay newest-first
            skills.append({
                "skill": name,
                "rating": r["rating"] if r else None,
                "count": r["count"] if r else 0,
                **({"coach": r["coach"]} if r and r.get("coach") else {}),
                "work": pieces[:WORK_PER_SKILL],
                "work_total": len(pieces),
            })
        if skills:
            out.append({"key": persona.get("key") or persona.get("name") or "",
                        "name": persona.get("name") or persona.get("key") or "",
                        "skills": skills})
    return out


class DeclaredSkillsView(APIView):
    """GET /api/economy/ratez/skills/ — the caller's own learned skills, for the picker.

    Own only: there is no username parameter, because this is a list to pick FROM and nobody
    posts as somebody else. `open_in` is the control that adds a skill when the list is empty
    or short, so the screen offers the jump rather than a dead end.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        personas = declared_skills(request.user)
        skills = [s for p in personas for s in p["skills"]]
        return Response({
            "personas": personas,
            "total": len(skills),
            "rated": sum(1 for s in skills if s["rating"] is not None),
            "note": DECLARED_NOTE,
            "open_in": {"tab": "personaz", "target": "", "label": "Add skills in PersonaZ"},
        })


def posts_of(user, viewer, limit=50):
    """The member's posts the VIEWER may see, and what each scored.

    It listed every post the member had ever made, private ones included, to
    anybody who asked by username — title, score and all. The feed's own
    visibility rule decides now, the same check /p/<id> runs.

    Medians and counts are fetched once for the whole list, not once per post:
    fifty posts used to be a hundred queries.
    """
    posts = [p for p in Post.objects.filter(author=user).order_by("-created_at")[:limit]
             if can_view_post(p, viewer)]
    keys = [f"post:{p.id}" for p in posts]
    medians = item_rating_medians(keys)
    counts = dict(ItemRating.objects.filter(item_id__in=keys)
                  .values_list("item_id").annotate(n=Count("id")))
    return [{
        "id": p.id, "title": p.title, "kind": "post",
        "item_key": f"post:{p.id}",
        "rating": medians.get(f"post:{p.id}"),
        "count": counts.get(f"post:{p.id}", 0),
        "skills_used": p.skills_used or [],
        "co_owned": bool(p.contributors),
        "url": f"/p/{p.id}",
    } for p in posts]


def contribution_of(user):
    """What the room thought this member did on their deals.

    Contribution ratings are ItemRatings keyed `collab:<deal>:<username>`,
    given by people NOT on the deal — the number that re-cuts a split when a
    deal pays on rating. RATING_KINDS has always declared this kind and the
    dashboard never served it.
    """
    suffix = f":{user.username}"
    rows = (ItemRating.objects.filter(item_id__startswith="collab:", item_id__endswith=suffix)
            .values_list("item_id", "score"))
    by_deal = {}
    for item_id, score in rows:
        parts = item_id.split(":")
        if len(parts) == 3 and parts[2] == user.username:
            by_deal.setdefault(parts[1], []).append(score)
    all_scores = [x for v in by_deal.values() for x in v]
    return {
        "kind": "contribution", "of": "your part of a deal",
        "median": _median(all_scores) if all_scores else None,
        "count": len(all_scores), "deals": len(by_deal),
    }


class RatezView(APIView):
    """GET /api/economy/ratez/ — every rating about a member, by kind.

    `?username=` reads someone else's; without it, your own.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        username = (request.query_params.get("username") or "").strip()
        user = (User.objects.filter(username__iexact=username).first()
                if username else request.user)
        if not user:
            return Response({"detail": "member not found"}, status=status.HTTP_404_NOT_FOUND)

        skills = skills_of(user)
        posts = posts_of(user, request.user)
        rated_posts = [p for p in posts if p["rating"] is not None]

        return Response({
            "username": user.username,
            "mine": user.id == request.user.id,
            # The taxonomy itself, served rather than hardcoded on the client,
            # so a label can't drift from what the number actually measures.
            "kinds": RATING_KINDS,
            "post": {
                "kind": "post", "of": "the work",
                "posts": posts,
                # The average of what their work scored — NOT an average of
                # averages across skills, which would double-count a post that
                # used four of them.
                "median": (round(sum(p["rating"] for p in rated_posts) / len(rated_posts), 1)
                           if rated_posts else None),
                "rated": len(rated_posts), "total": len(posts),
            },
            "skill": {
                "kind": "skill", "of": "a skill you used",
                "skills": skills,
                "note": "Nobody rates a skill directly. Rating a post rates "
                        "every skill that went into it, for whoever brought it.",
            },
            "overall": {
                "kind": "overall", "of": "you",
                "median": overall_median(user),
                "count": OverallRating.objects.filter(target=user).count(),
            },
            "contribution": contribution_of(user),
            # Rating people on looks is adults-only in BOTH directions (Play
            # Families) — AttractivenessRateView and FaceZ already hold that
            # line, and this read did not: anybody could read anybody's,
            # a minor's included, by username. Locked with the reason now.
            "attractiveness": (
                {"kind": "attractiveness", "of": "you", "median": None,
                 "locked": adult_only_reason(request.user) or adult_only_reason(user)}
                if (adult_only_reason(request.user) or adult_only_reason(user)) else
                {"kind": "attractiveness", "of": "you",
                 "median": attractiveness_median(user),
                 "note": "Kept apart from the rest on purpose — it is not a "
                         "judgement of anybody's work."}),
        })


def rating_reward(user):
    """The gain a rating pays this member right now, for showing BEFORE they rate."""
    left, cap = rating_reward_left(user)
    return {"resource": "energy", "amount": RATING_REWARD_ENERGY if left else 0,
            "left_today": left, "cap": cap,
            "public_bonus_pct": 25, "per_collaborator_pct": 10}


def rating_reward_left(user):
    """How many more ratings today still pay, so the gain is stated honestly.

    Same count reward_for_rating makes: a +1 ⚡ that the cap has already
    used up is not a gain, and showing it beside the button would be a promise
    the server then breaks.
    """
    day_ago = timezone.now() - timedelta(hours=24)
    paid = Transaction.objects.filter(
        user=user, resource=Transaction.RES_ENERGY,
        note__startswith=RATING_NOTE, created_at__gte=day_ago,
    ).count()
    cap = RATING_REWARD_DAILY_CAP + badge_effects(user).get("rating_cap_bonus", 0)
    return max(0, cap - paid), cap


class RateQueueView(APIView):
    """GET /api/economy/ratez/queue/ — work by other members you haven't rated.

    The other half of RateZ: the dashboard shows what you've been given, this
    is where you give. Only posts the rate endpoint would ACCEPT — not yours,
    past the unlock window, visible to you — so nothing here is a button that
    answers 403.

    `needs_listen` is the substance rule carried through: a track you have not
    heard is not one you can score, so those rows open the post's own player
    rather than offering a number beside the title.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        me = request.user
        cutoff = timezone.now() - timedelta(seconds=POST_RATE_UNLOCK_SEC)
        rated = ItemRating.objects.filter(user=me, item_id__startswith="post:").values_list("item_id", flat=True)
        rated_ids = {int(k.split(":", 1)[1]) for k in rated if k.split(":", 1)[1].isdigit()}
        qs = (Post.objects.exclude(author=me).exclude(visibility="private")
              .filter(created_at__lte=cutoff).exclude(pk__in=rated_ids)
              .select_related("author").order_by("-created_at")[:60])
        posts = [p for p in qs if can_view_post(p, me)][:20]
        keys = [f"post:{p.id}" for p in posts]
        medians = item_rating_medians(keys)
        counts = dict(ItemRating.objects.filter(item_id__in=keys)
                      .values_list("item_id").annotate(n=Count("id")))
        left, cap = rating_reward_left(me)
        # How much of each one this member has already heard — one query, so
        # the queue can say "8s to go" and unlock rating in place.
        from .models import LISTEN_REQUIRED_SEC, ListenProgress
        heard = {lp.item_id: lp for lp in ListenProgress.objects.filter(user=me, item_id__in=keys)}

        def play(p):
            """The recording to play in the queue card itself, so rating never
            means leaving the queue to find the post."""
            if p.media_type in ("audio", "video") and p.media_url:
                return p.media_type, p.media_url
            for it in (p.items or []):
                kind = (it.get("type") or "").lower()
                if kind in ("audio", "video") and it.get("url"):
                    return kind, it["url"]
            return "", ""

        def listened(p):
            lp = heard.get(f"post:{p.id}")
            return (lp.seconds if lp else 0), bool(lp and lp.finished)

        rows = []
        for p in posts:
            gated = heard_enough_required(p)
            secs, done = listened(p)
            kind, url = play(p)
            rows.append({
                "id": p.id, "item_key": f"post:{p.id}", "title": p.title,
                "author": p.author.username, "media_type": p.media_type or "",
                # Gated AND not yet heard enough — the rate endpoint's own rule.
                "needs_listen": gated and not (done or secs >= LISTEN_REQUIRED_SEC),
                "listen_gated": gated,
                "listened_sec": min(secs, LISTEN_REQUIRED_SEC),
                "listen_required_sec": LISTEN_REQUIRED_SEC,
                "play_kind": kind, "play_url": url,
                "genre": p.genre or "",
                "rating": medians.get(f"post:{p.id}"),
                "count": counts.get(f"post:{p.id}", 0),
                "skills_used": p.skills_used or [],
                "url": f"/p/{p.id}",
            })
        return Response({
            "reward": {"resource": "energy", "amount": RATING_REWARD_ENERGY if left else 0,
                       "left_today": left, "cap": cap},
            "posts": rows,
        })


class RatingKindsView(APIView):
    """GET /api/economy/ratez/kinds/ — what each rating in this app measures."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"kinds": RATING_KINDS})
