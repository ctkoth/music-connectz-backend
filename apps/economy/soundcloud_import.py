"""Bring a member's SoundCloud catalogue in as draft posts.

Posting a SoundCloud link one at a time already works at every tier — WidgetZ
reads the id out of the URL and frames the provider's own player. So this is
not a new capability, it is the same one in bulk, and the tier buys HOW MANY
come in at once rather than whether any do.

THE TOKEN IS NEVER STORED
-------------------------
`OAuthIdentity` holds a provider, a uid and an email. It has never held an
access token and this does not change that: the member re-authorises at import
time, the fresh token is used once to list their tracks, and it goes out of
scope with the request.

The alternative — storing it so imports can run unattended — was considered and
refused. A SoundCloud token can post and delete on its owner's account, so a
stored one turns a database breach from "emails leaked" into "somebody else's
catalogue deleted". A feature run a handful of times a year does not earn that
liability, and the cost of not storing it is one consent screen.

THEY ARRIVE AS DRAFTS
---------------------
`visibility="private"` — visible to nobody but their owner until they publish.
A member with two hundred tracks publishing all of them at once would land two
hundred posts in everybody's feed in the same minute, which reads as spam and
buries every other member that day. The import is the easy part; deciding what
to actually show people is the member's.

WHAT IT COSTS
-------------
Nothing. Importing is not posting: an imported draft has been shown to no one.
The normal cost of a post applies when they publish one, which is the moment it
reaches anybody.
"""
import requests
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.oauth import OAuthError, access_token_for

from .catalog import limits_for
from .models import Post, membership_for

# SoundCloud's own listing endpoint for the authorised member.
ME_TRACKS = "https://api.soundcloud.com/me/tracks"

# Their page size cap, and ours is whichever is smaller — asking for more than
# they serve just silently truncates, which would read here as "the member has
# fewer tracks than they do".
PAGE_LIMIT = 200


def import_cap(tier):
    """How many tracks one import may bring in.

    A ladder on volume, not on access: one-at-a-time posting of a SoundCloud
    link is free at every tier and always has been. Free is 5 rather than 0
    because an importer that imports nothing is a button that lies.
    """
    return limits_for(tier)["soundcloud_import"]


def _tracks(token, limit):
    """The member's public tracks, newest first. Raises OAuthError on failure."""
    try:
        r = requests.get(
            ME_TRACKS,
            headers={"Authorization": f"OAuth {token}", "Accept": "application/json"},
            params={"limit": min(int(limit), PAGE_LIMIT), "linked_partitioning": 1},
            timeout=20,
        )
    except requests.RequestException:
        raise OAuthError("Could not reach SoundCloud to read your tracks.")
    if r.status_code != 200:
        raise OAuthError("SoundCloud refused to list your tracks. Try authorising again.")
    try:
        body = r.json()
    except ValueError:
        raise OAuthError("SoundCloud returned something this couldn't read.")
    # `linked_partitioning` wraps the list in an object; without it the list is
    # bare. Accept both rather than depending on which one they send today.
    return body.get("collection", body) if isinstance(body, dict) else body


def _already_here(user, urls):
    """Permalinks this member has already imported, so a second run is a no-op.

    Matched on the URL inside `embeds` rather than on a title: two different
    mixes of one song share a name, and re-importing must not silently drop
    the second. One query for the whole batch.
    """
    seen = set()
    for post in Post.objects.filter(author=user).exclude(embeds=[]).only("embeds"):
        for e in (post.embeds or []):
            if isinstance(e, dict) and e.get("url") in urls:
                seen.add(e["url"])
    return seen


class SoundCloudImportView(APIView):
    """POST /api/economy/soundcloud/import/ — {code, redirect_uri} → drafts.

    The code comes from a SoundCloud authorisation the CLIENT just completed.
    It is exchanged here rather than there so the client secret stays on the
    server, and the resulting token never leaves this function.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """What an import would do, before the member authorises anything."""
        tier = membership_for(request.user).tier
        return Response({
            "tier": tier,
            "max_tracks": import_cap(tier),
            "cost": 0,
            "lands_as": "draft",
            "why": "Imported tracks are private until you publish them. Posting "
                   "two hundred at once would bury everyone else's, so what to "
                   "show people stays your call.",
            "stores_token": False,
        })

    def post(self, request):
        d = request.data or {}
        tier = membership_for(request.user).tier
        cap = import_cap(tier)
        try:
            token = access_token_for(
                "soundcloud", str(d.get("code") or ""),
                str(d.get("redirect_uri") or ""), str(d.get("code_verifier") or ""))
            tracks = _tracks(token, cap)
        except OAuthError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        finally:
            token = None

        wanted = []
        for t in tracks if isinstance(tracks, list) else []:
            if not isinstance(t, dict):
                continue
            url = (t.get("permalink_url") or "").strip()
            title = (t.get("title") or "").strip()[:160]
            if url and title:
                wanted.append((url, title))
            if len(wanted) >= cap:
                break

        skipped = _already_here(request.user, {u for u, _ in wanted})
        made = [
            Post.objects.create(
                author=request.user,
                title=title,
                # The player, not a copy of the audio. SoundCloud stays the
                # host; this is a post that frames their track.
                embeds=[{"type": "soundcloud", "url": url, "title": title}],
                visibility="private",
            )
            for url, title in wanted if url not in skipped
        ]

        return Response({
            "imported": len(made),
            "already_here": len(skipped),
            "max_tracks": cap,
            # Said out loud because it is the whole reason this is safe to use:
            # the member handed over an authorisation and gets to see that
            # nothing was kept from it.
            "token_kept": False,
            "detail": (f"{len(made)} track{'' if len(made) == 1 else 's'} imported as "
                       f"drafts. They're private until you publish them."
                       + (f" {len(skipped)} were already here." if skipped else "")),
        }, status=status.HTTP_201_CREATED)
