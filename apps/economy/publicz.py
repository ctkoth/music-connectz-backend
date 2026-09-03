"""What a logged-out visitor can see.

The client has shipped a public share route (`/p/:id`) since before this file
existed, pointed at `/api/postz/<id>/` with `auth: false`. That endpoint was
never built, so every link a member has ever shared off-platform lands on a
404. A share button that produces a dead link is worse than no share button.

The rule here is narrow on purpose:

* **By link, or by browse of PUBLIC posts only.** `PublicFeedView` is the one
  exception to "by link, not by browse" this file used to hold as absolute —
  it opens discovery, never data: it serves the exact same `public_post_dict`
  every shared link already exposes, filtered to `visibility="public"` only
  (never `restricted`, which `can_view_post` still requires a session for).
  There is still no anonymous MEMBER search — that is the part of the old
  rule that actually mattered, because member search is what carries age and
  attractiveness data. A feed of posts never touches either field.
* **Read-only, and no resource moves.** A visitor has no wallet, so nothing
  here can be priced, rewarded, or farmed. Anonymous views deliberately earn
  the author nothing: a reward you can mint by hitting a URL in a loop is not a
  reward, it's an exploit.
* **Public means public.** `restricted` is members-only and `private` is the
  author's; neither is reachable without a session, which is what
  `can_view_post` already says.
"""
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .badgez import public_badge_chip
from .models import (
    Post,
    Profile,
    badges_for,
    can_view_post,
    item_rating_median,
)
from .social import featured_link_for


def public_post_dict(p):
    """A shared post as a stranger sees it.

    Built field-by-field rather than by stripping the member payload — a
    deny-list quietly leaks whatever gets added to the post later, and this
    response is the one nobody has to log in to read.
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
    return {
        "id": p.id,
        "author": p.author.username,
        "title": p.title,
        "description": p.description,
        "links": p.links or [],
        "media_type": p.media_type,
        "media_url": p.media_url,
        "is_album": p.is_album,
        "items": p.items or [],
        "score": p.score or {},
        "rating": item_rating_median(f"post:{p.id}"),
        "created_at": p.created_at.isoformat(),
        "take_missing": missing,
        "take_kind": state.get("kind", "") if missing else "",
        "public": True,
    }


def public_post_teaser(p):
    """A RESTRICTED post as a stranger sees it: enough to know it exists and
    who made it, nothing of what's actually in it. `can_view_post` already
    refuses the content itself with no session — a teaser must not quietly
    hand over what the door refuses, or it isn't a door.

    Existence is fine to reveal here, unlike a private post: a restricted
    post's whole point is RESTRICTED_JOIN_REWARD_SPINAZ — the author is
    rewarded for a stranger who sees this locked door and joins to open it.
    A 404 for restricted would erase the door instead of showing it.
    """
    return {
        "id": p.id,
        "author": p.author.username,
        "title": p.title,
        "visibility": "restricted",
        "locked": True,
        "created_at": p.created_at.isoformat(),
        "public": True,
    }


def public_profile_dict(p):
    """A member's card as a stranger sees it — the work, not the person.

    Skills carry names and rates, deliberately: what somebody does and what
    they charge is the reason to look them up. Birthday, attractiveness,
    location, substances and wallet are all absent — those exist for matching
    inside the app and are nobody's business from outside it.
    """
    personas = []
    for persona in (p.personas or []):
        if not isinstance(persona, dict):
            continue
        skills = []
        for s in (persona.get("skills") or []):
            if isinstance(s, dict) and s.get("name"):
                entry = {"name": s["name"]}
                if s.get("rate_cents"):
                    entry["rate_cents"] = s["rate_cents"]
                skills.append(entry)
        personas.append({
            "key": persona.get("key", ""),
            "name": persona.get("name", ""),
            "skills": skills,
        })
    return {
        "username": p.user.username,
        "display_name": p.display_name or p.user.username,
        "bio": p.bio or "",
        "personas": personas,
        # BadgeZ travels with the card. A shared profile is somebody's proof
        # they are worth hiring, and "ten deals, no dispute" is exactly the
        # part of that a stranger came to find out. Only badges the member
        # chose to show, and only what the badge is — never what it pays.
        "badge_title": p.badge_title,
        "badges": [public_badge_chip(b) for b in badges_for(p.user, only_visible=True)],
        "links": p.links or [],
        "featured_link": featured_link_for(p),
        "public": True,
    }


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
        if can_view_post(p, request.user):
            return Response(public_post_dict(p))
        if p.visibility == "restricted":
            # A locked door, not an erased one — see public_post_teaser.
            return Response(public_post_teaser(p))
        # private — confirming it exists at all is itself a leak.
        return Response({"detail": "post not found"}, status=status.HTTP_404_NOT_FOUND)


FEED_PAGE = 20


class PublicFeedView(APIView):
    """GET /api/economy/public/feed/?before=<id> — the newest posts, no
    account needed. `before` pages backward in time (pass the previous page's
    `next_before`); omit it for the first page.

    Two shapes ride in the same list: a `public` post is the identical
    `public_post_dict` a shared /p/:id link already serves with no login, and
    a `restricted` one is `public_post_teaser` — a locked door, title and
    author only, the same content-free stub PublicPostView answers with for
    a direct link. Browsing this feed can never show a stranger more than
    following a link to any one of these posts already would. `private`
    posts never appear here regardless of who wrote them.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        qs = (Post.objects.exclude(visibility="private")
              .select_related("author").order_by("-created_at"))
        before = request.query_params.get("before")
        if before:
            try:
                qs = qs.filter(pk__lt=int(before))
            except (TypeError, ValueError):
                pass
        rows = list(qs[:FEED_PAGE + 1])
        has_more = len(rows) > FEED_PAGE
        rows = rows[:FEED_PAGE]
        return Response({
            "posts": [public_post_dict(p) if p.visibility == "public" else public_post_teaser(p)
                     for p in rows],
            "next_before": rows[-1].id if (rows and has_more) else None,
        })


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
        return Response(public_profile_dict(p))
