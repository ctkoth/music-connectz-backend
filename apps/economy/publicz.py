"""What a logged-out visitor can see.

The client has shipped a public share route (`/p/:id`) since before this file
existed, pointed at `/api/postz/<id>/` with `auth: false`. That endpoint was
never built, so every link a member has ever shared off-platform lands on a
404. A share button that produces a dead link is worse than no share button.

The rule here is narrow on purpose:

* **By link, not by browse.** One public post, one public profile, each fetched
  by its own identifier. There is no anonymous feed and no anonymous member
  search — the feed is the product, and search carries age and attractiveness
  data that has no business leaving the login.
* **Read-only, and no resource moves.** A visitor has no wallet, so nothing
  here can be priced, rewarded, or farmed. Anonymous views deliberately earn
  the author nothing: a reward you can mint by hitting a URL in a loop is not a
  reward, it's an exploit.
* **Public means public.** `restricted` is members-only and `private` is the
  author's; neither is reachable without a session, which is what
  `can_view_post` already says.
"""
from .inventoryz import inventory_shown
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .badgez import public_badge_chip
from .coachshare import coach_read_for, legacy_score
from .visibility import redact
from .models import (
    Post,
    Profile,
    badges_for,
    public_name,
    can_view_post,
    item_rating_median,
)
from .personaz import links_of, personas_of, rate_unit_of
from .ratez import skills_of


def public_post_dict(p, viewer=None):
    """A shared post as a stranger sees it.

    Built field-by-field rather than by stripping the member payload — a
    deny-list quietly leaks whatever gets added to the post later, and this
    response is the one nobody has to log in to read.

    `viewer` is the person opening the link, or None for a crawler and the edge
    function that builds link previews. It only ever changes ONE thing — the
    coach's read, which the author may have kept for members — and a signed-in
    member opening the same link sees what they are entitled to rather than
    the stranger's locked card.
    """
    from .crosspost import take_state_for
    from .postz import media_slots

    # One query, on a single post, to answer the question a shared link asks
    # loudest. Somebody followed this link to hear a track; if the recording is
    # gone they get a player that sits at 0:00 and concludes the artist posted
    # silence. That is the member's name on a stranger's screen, so it is worth
    # a query to say whose failure it actually was.
    state = take_state_for([(p, media_slots(p))]).get(p.id) or {}
    missing = bool(state.get("missing"))
    coach = coach_read_for(p, viewer)
    if coach["state"] == "shown" and coach.get("public"):
        # The card image is a public address, so it is only named when a
        # stranger could fetch it. A member-only read has no image to link.
        coach["card_image"] = f"/api/economy/postz/{p.id}/coach-card.png"
        coach["story_image"] = f"/api/economy/postz/{p.id}/coach-card.png?format=story"
    return {
        "id": p.id,
        "author": p.author.username,
        "title": p.title,
        "description": p.description,
        "links": links_of(p),
        "media_type": p.media_type,
        "media_url": p.media_url,
        "is_album": p.is_album,
        "items": p.items or [],
        # The whole stored read ONLY when `coach` says it is shown — see
        # coachshare.legacy_score. Beside it, `coach` carries the labelled read
        # or the locked card, never both an old and a new copy of the number.
        "score": legacy_score(p, coach),
        "coach": coach,
        "rating": item_rating_median(f"post:{p.id}"),
        "created_at": p.created_at.isoformat(),
        "take_missing": missing,
        "take_kind": state.get("kind", "") if missing else "",
        "public": True,
    }


from apps.economy.social import _pinned, cover_abs  # noqa: E402


def _skill_name(s):
    """The key a declared skill is rated under: trimmed and at most 60 characters, the cut
    `postz.declared_skill_names` makes, because that is the width `SkillRating.skill` is stored at.
    "" for anything that is not a named skill."""
    if not isinstance(s, dict):
        return ""
    return str(s.get("name") or "").strip()[:60]


def public_profile_dict(p, request=None):
    """A member's card as a stranger sees it — the work, not the person.

    Skills carry names, rates and how each has been rated, deliberately: what
    somebody does, what they charge and how it has landed are the reasons to look
    them up. Birthday, attractiveness, location, substances and wallet are all
    absent — those exist for matching inside the app and are nobody's business
    from outside it.
    """
    listed = personas_of(p)
    # Every declared skill's rating, read once for the whole card. `skills_of` is THE rating
    # (median, count, and the AI coach's share when the member opted in), so a card joins on the
    # skill's name and never computes a second number. A card that names no skill reads none.
    rated = {}
    if any(_skill_name(s) for per in listed for s in (per.get("skills") or [])):
        rated = {r["skill"]: r for r in skills_of(p.user)}
    personas = []
    for persona in listed:
        skills = []
        for s in (persona.get("skills") or []):
            if isinstance(s, dict) and s.get("name"):
                entry = {"name": s["name"]}
                if s.get("rate_cents"):
                    entry["rate_cents"] = s["rate_cents"]
                    entry["rate_unit"] = rate_unit_of(s)
                if s.get("genres"):
                    entry["genres"] = s["genres"]
                # Unrated says so: `rating` None and `count` 0, never a 0 that reads as a verdict.
                # `coached` says the AI coach is part of the number, so it is never unexplained.
                key = _skill_name(s)
                r = rated.get(key) if key else None
                entry["rating"] = r["rating"] if r else None
                entry["count"] = r["count"] if r else 0
                entry["coached"] = bool(r and r.get("coach"))
                skills.append(entry)
        personas.append({
            "key": persona.get("key", ""),
            "name": persona.get("name", ""),
            "skills": skills,
            **({"roles": persona["roles"]} if persona.get("roles") else {}),
        })
    # Redacted for the anonymous audience: a member who moved bio or links to
    # "member" must be honoured on the one page a stranger can open, which is
    # the page this control exists for.
    return redact({
        "username": p.user.username,
        "display_name": p.display_name or p.user.username,
        # "" unless the member opted in — see public_name()'s note on why this
        # never falls back to the handle.
        "real_name": public_name(p),
        "bio": p.bio or "",
        "personas": personas,
        # The work-facing popular-site fields. Timezone stays off the
        # logged-out card: it narrows where somebody lives for no hiring gain.
        "pronouns": p.pronouns, "headline": p.headline, "genres": p.genres or [],
        "influences": p.influences or [], "gear": p.gear or [], "label": p.label,
        # Logged out, so only an owner who set "what it's worth" to Public shows prices here.
        "inventory": inventory_shown(p, None), 
        "cover_url": cover_abs(p.cover_url, request),
        "pinned_post": _pinned(p),
        # BadgeZ travels with the card. A shared profile is somebody's proof
        # they are worth hiring, and "ten deals, no dispute" is exactly the
        # part of that a stranger came to find out. Only badges the member
        # chose to show, and only what the badge is — never what it pays.
        "badge_title": p.badge_title,
        "badges": [public_badge_chip(b) for b in badges_for(p.user, only_visible=True)],
        "links": links_of(p),
        "public": True,
    }, p, None)


class PublicPostView(APIView):
    """GET /api/postz/<pk>/ — one post, no account needed if it's public.

    Also answers for signed-in members, so the share link behaves the same
    whether or not the person opening it happens to be logged in.
    """

    permission_classes = [AllowAny]

    def get(self, request, pk):
        p = Post.objects.select_related("author").filter(pk=pk).first()
        if not p:
            return Response({"detail": "post not found"}, status=status.HTTP_404_NOT_FOUND)
        if not can_view_post(p, request.user):
            # 404, not 403 — confirming a private post exists is itself a leak.
            return Response({"detail": "post not found"}, status=status.HTTP_404_NOT_FOUND)
        resp = Response(public_post_dict(p, request.user))
        # The body now depends on WHO is asking (a members-only read is shown to
        # a member and locked to a stranger), so a shared cache must never hand
        # one reader's copy to another.
        resp["Cache-Control"] = "private"
        resp["Vary"] = "Authorization"
        return resp


class PublicProfileView(APIView):
    """GET /api/economy/public/members/<username>/ — a read-only member card.

    Without this the author line on a shared post is a dead name, which is the
    exact dead end the cross-pollination rule exists to prevent.
    """

    permission_classes = [AllowAny]

    def get(self, request, username):
        p = (Profile.objects.select_related("user")
             .filter(user__username__iexact=str(username)[:150]).first())
        if not p:
            return Response({"detail": "profile not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(public_profile_dict(p, request))


# ---- Browse without an account (Corey's call) ----
#
# The note at the top of this file said "by link, not by browse". Corey asked for a visitor to be able to
# look around before joining, so this is the narrowest browse that answers it:
#
# * PUBLIC posts only, newest first, paged. Members-only and private stay behind the login.
# * A light card (title, author, a description snippet, what kind of media), never the full read: the
#   card links to /p/<id>, which already decides what a stranger may see of the coach's read.
# * NO member search. It carries age, location and attractiveness data that stays inside the login.
# * Posts by members we know are under 18 are left out of this stranger-facing list. Their posts are
#   still public by link, as before; this only stops an anonymous feed from surfacing teenagers to
#   anybody on the internet. Unknown ages count as adults, matching `is_minor`.
BROWSE_PAGE = 24
BROWSE_SNIPPET = 160


def browse_card(p):
    d = " ".join((p.description or "").split())
    return {"id": p.id, "author": p.author.username, "title": p.title or "",
            "snippet": d[:BROWSE_SNIPPET] + ("…" if len(d) > BROWSE_SNIPPET else ""),
            "media_type": p.media_type or "", "genre": getattr(p, "genre", "") or "",
            "created_at": p.created_at.isoformat(), "open": f"/p/{p.id}"}


class PublicBrowseView(APIView):
    """GET /api/economy/public/browse/?before=<id> — public posts for a visitor, newest first."""

    permission_classes = [AllowAny]

    def get(self, request):
        from .models import profile_is_minor
        qs = (Post.objects.filter(visibility="public").select_related("author", "author__mcz_profile")
              .order_by("-id"))
        try:
            before = int(request.query_params.get("before") or 0)
        except ValueError:
            before = 0
        if before > 0:
            qs = qs.filter(id__lt=before)
        cards, last = [], None
        # Read a few pages' worth so dropping posts by minors cannot leave a page empty.
        for p in qs[: BROWSE_PAGE * 3]:
            last = p.id
            prof = getattr(p.author, "mcz_profile", None)
            if prof is not None and profile_is_minor(prof):
                continue
            cards.append(browse_card(p))
            if len(cards) >= BROWSE_PAGE:
                break
        more = qs.filter(id__lt=last).exists() if last else False
        resp = Response({"posts": cards, "next": last if more else None,
                         "note": "Public posts from members. Join free to rate, comment, and get your own take scored."})
        resp["Cache-Control"] = "public, max-age=60"
        return resp
