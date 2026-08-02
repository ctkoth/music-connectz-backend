"""Public, read-only Music ConnectZ — the storefront you can see without an account.

Everything behind the login was invisible to anyone who hadn't already signed
up, which is backwards for a platform that wants members: nobody joins a room
they can't see into. Google couldn't index a single post either, so the only
way to find Music ConnectZ was to already know about it.

The rule is narrow and one-directional:

    You can READ what a member chose to publish. You cannot read anything
    else, and you cannot write, spend, rate, message or join anything.

Three things are deliberately NOT public, even though a signed-in member sees
them, because they are about a person rather than a work:

  * **Location.** `share_location` is consent to be found by other members, not
    consent to be on the open internet. Distance is dropped entirely here.
  * **Attractiveness.** Opt-in among members is not opt-in to being ranked by
    strangers who never made an account.
  * **Anything age-related on a minor's profile**, and the birthday itself.

Everything served here is also what a search engine will cache, so "we can
un-publish it later" is not true in the way it is inside the app.
"""
from django.contrib.auth import get_user_model
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Post, Profile, follow_counts, overall_median, profile_for
from .social import _avatar_url

User = get_user_model()

# Only posts the author marked public. "restricted" means members-only by
# design and "private" is nobody — serving either here would publish to the
# open web something the author deliberately narrowed.
PUBLIC_POSTS = Post.objects.filter(visibility="public")

# A stranger gets a page of results, not the whole database. Without a cap this
# is a bulk export endpoint with no account attached to the scraping.
PAGE = 24
MAX_PAGE = 60


def _page_size(request):
    try:
        return max(1, min(int(request.query_params.get("limit", PAGE)), MAX_PAGE))
    except (TypeError, ValueError):
        return PAGE


def public_post(post):
    """One post, reduced to what a stranger may see."""
    return {
        "id": post.id,
        "title": post.title,
        "description": post.description,
        "author": post.author.username,
        "media_type": post.media_type,
        "media_url": post.media_url,
        "is_album": post.is_album,
        "created_at": post.created_at,
    }


def public_profile(profile, request=None):
    """One member, reduced to what a stranger may see.

    No birthday, no age, no location, no distance, no attractiveness, no
    wallet, no email. A rating median is included because it describes their
    work; an attractiveness median describes their body, and a stranger who
    never made an account has no business with it.
    """
    user = profile.user
    counts = follow_counts(user)
    return {
        "username": user.username,
        "display_name": getattr(profile, "display_name", "") or user.username,
        "bio": getattr(profile, "bio", "") or "",
        "avatar": _avatar_url(profile, request) if request else None,
        "personas": getattr(profile, "personas", None) or [],
        "genres": getattr(profile, "genres", None) or [],
        "skill_rating": overall_median(user),
        "followers": counts.get("followers", 0),
        "following": counts.get("following", 0),
    }


class PublicFeedView(APIView):
    """GET /api/public/feed/ — the newest published work. No account needed."""

    permission_classes = [AllowAny]

    def get(self, request):
        limit = _page_size(request)
        qs = (PUBLIC_POSTS.select_related("author")
              .order_by("-created_at")[:limit])
        return Response({
            "posts": [public_post(p) for p in qs],
            "limit": limit,
            "note": "Public, read-only. Sign in to react, collab, or post.",
        })


class PublicProfileView(APIView):
    """GET /api/public/members/<username>/ — a member's public page."""

    permission_classes = [AllowAny]

    def get(self, request, username):
        user = User.objects.filter(username__iexact=username).first()
        if not user:
            return Response({"detail": "No such member."}, status=404)
        profile = profile_for(user)
        posts = (PUBLIC_POSTS.filter(author=user)
                 .order_by("-created_at")[:_page_size(request)])
        return Response({
            "member": public_profile(profile, request),
            "posts": [public_post(p) for p in posts],
        })


class PublicMembersView(APIView):
    """GET /api/public/members/ — who's on here.

    No filters. The five range gates read age, location and attractiveness,
    and none of those may be queryable by somebody with no account — a
    stranger being able to search "18-22 within 5km" is a different product
    from members finding collaborators.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        limit = _page_size(request)
        qs = Profile.objects.select_related("user").order_by("-id")[:limit]
        return Response({
            "members": [public_profile(p, request) for p in qs],
            "limit": limit,
            "filters": None,
            "note": ("Search filters need an account — they read age, distance "
                     "and ratings that members share with other members, not "
                     "with the open web."),
        })


class PublicOverviewView(APIView):
    """GET /api/public/ — what this place is, for someone who just arrived.

    Also the honest answer to "what can I do without signing up", which is a
    question the app should answer before asking for an email.
    """

    permission_classes = [AllowAny]

    def get(self, _request):
        from apps.tabz import registry

        return Response({
            "name": "Music ConnectZ",
            "public": {
                "readable": ["feed", "member profiles", "member list",
                             "tabs", "personas", "genres", "VST catalog"],
                "requires_account": [
                    "posting", "reacting", "commenting", "messaging",
                    "collabs", "battles", "venues", "ratings", "the wallet",
                    "search filters",
                ],
            },
            "tabs": [{"name": t["name"], "url": t["url"]}
                     for t in registry.all_tabs()],
            "note": ("Everything here is read-only and was published by the "
                     "member it belongs to. Nothing private is served."),
        })
