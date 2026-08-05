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
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Post,
    Profile,
    can_view_post,
    item_rating_median,
)


def public_post_dict(p):
    """A shared post as a stranger sees it.

    Built field-by-field rather than by stripping the member payload — a
    deny-list quietly leaks whatever gets added to the post later, and this
    response is the one nobody has to log in to read.
    """
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
        "links": p.links or [],
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
        if not can_view_post(p, request.user):
            # 404, not 403 — confirming a private post exists is itself a leak.
            return Response({"detail": "post not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(public_post_dict(p))


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
