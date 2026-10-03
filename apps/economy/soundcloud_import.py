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
from urllib.parse import urlparse

import requests
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.oauth import OAuthError, access_token_for

from .catalog import limits_for, over_char_limit, UNLIMITED_CHARS, TIER_LIMITS
from .deadline import Deadline
from .models import Post, membership_for
from .widgetz import _player_for

# SoundCloud's own listing endpoint for the authorised member.
ME_TRACKS = "https://api.soundcloud.com/me/tracks"

# Their page size cap, and ours is whichever is smaller — asking for more than
# they serve just silently truncates, which would read here as "the member has
# fewer tracks than they do".
PAGE_LIMIT = 200


# One import may keep the member waiting this long. A StatZ catalogue of a
# thousand tracks is five pages; the budget is for a slow SoundCloud, not a
# big account. Running out is not a failure: what came in is kept, and a second
# run picks up the rest because already-imported tracks are skipped.
IMPORT_BUDGET_SECONDS = 60
# Pages are only followed on SoundCloud's own API host. `next_href` comes from
# their response, and the member's token rides on every request that follows
# it — a link anywhere else would hand the token to whoever served it.
API_HOST = "api.soundcloud.com"


def import_cap(tier):
    """How many tracks one import may bring in; None is the whole catalogue.

    A ladder on volume, not on access: one-at-a-time posting of a SoundCloud
    link is free at every tier and always has been. Free is 5 rather than 0
    because an importer that imports nothing is a button that lies.
    """
    return limits_for(tier)["soundcloud_import"]


def _get(url, token, params, deadline):
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"OAuth {token}", "Accept": "application/json"},
            params=params, timeout=deadline.remaining(cap=20),
        )
    except requests.RequestException:
        raise OAuthError("Could not reach SoundCloud to read your tracks.")
    if r.status_code != 200:
        raise OAuthError("SoundCloud refused to list your tracks. Try authorising again.")
    try:
        return r.json()
    except ValueError:
        raise OAuthError("SoundCloud returned something this couldn't read.")


def _tracks(token, limit, deadline=None):
    """The member's tracks, newest first, following every page up to `limit`
    (None = all of them). Returns (tracks, complete).

    It used to read ONE page of 200 and stop, so a catalogue past 200 was cut
    short with nothing saying so — "the whole catalogue" on StatZ was the
    first page of it. `complete` is False when the budget ran out first, and
    the caller says so rather than calling a partial import done.
    Raises OAuthError if the FIRST page fails; a later page failing keeps what
    was already read.
    """
    deadline = deadline or Deadline(IMPORT_BUDGET_SECONDS)
    page = PAGE_LIMIT if limit is None else min(int(limit), PAGE_LIMIT)
    out = []
    body = _get(ME_TRACKS, token, {"limit": page, "linked_partitioning": 1}, deadline)
    while True:
        # `linked_partitioning` wraps the list in an object; without it the
        # list is bare. Accept both rather than depending on which they send.
        batch = body.get("collection", []) if isinstance(body, dict) else (body or [])
        out.extend(t for t in batch if isinstance(t, dict))
        if limit is not None and len(out) >= limit:
            return out[:limit], True
        nxt = body.get("next_href") if isinstance(body, dict) else None
        if not nxt or not batch:
            return out, True
        if urlparse(nxt).hostname != API_HOST:
            return out, True
        if deadline.expired():
            return out, False
        try:
            body = _get(nxt, token, None, deadline)
        except OAuthError:
            return out, False


def _already_here(user, widget_urls):
    """Which of these WIDGET urls this member has already imported, so a
    second run is a no-op.

    Matched on the widget `src` inside `embeds` — the same value both this
    import and the one-at-a-time "add a track" flow in `views.PostEmbedsView`
    now store — rather than on a title: two different mixes of one song
    share a name, and re-importing must not silently drop the second. One
    query for the whole batch.
    """
    seen = set()
    for post in Post.objects.filter(author=user).exclude(embeds=[]).only("embeds"):
        for e in (post.embeds or []):
            if isinstance(e, dict) and e.get("url") in widget_urls:
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
            # None means the whole catalogue (StatZ). Said as a flag so a client
            # never renders "Up to null tracks".
            "whole_catalogue": import_cap(tier) is None,
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
            tracks, complete = _tracks(token, cap)
        except OAuthError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        finally:
            token = None

        char_cap = TIER_LIMITS.get(tier, {}).get("char_limit", UNLIMITED_CHARS)
        wanted, private = [], 0
        for t in tracks if isinstance(tracks, list) else []:
            permalink = (t.get("permalink_url") or "").strip()
            title = (t.get("title") or "").strip()[:160]
            if not (permalink and title):
                continue
            # A private track's public player shows "track not found": the
            # widget needs its secret token, and putting that token into a
            # post the member might later publish would leak a track they
            # chose to keep private. Skipped and COUNTED, so the member is
            # told why their catalogue came in short rather than left to find
            # holes in it.
            if (t.get("sharing") or "public") != "public":
                private += 1
                continue
            # Resolved through the SAME widget builder `views._parse_embed_url`
            # and the manual "add a track" flow use, so an imported post and a
            # hand-added one store the identical embed shape. Storing the raw
            # `permalink_url` here once meant an imported post framed
            # soundcloud.com itself instead of `w.soundcloud.com/player` — the
            # provider's real site, not built to be framed that way, where a
            # hand-added link was always routed through the actual widget.
            spec = _player_for(permalink)
            if not spec:
                continue
            desc = (t.get("description") or "").strip()
            if over_char_limit(desc, tier):
                desc = desc[:char_cap]
            wanted.append({"url": spec["src"], "title": title, "aspect": spec.get("aspect", ""),
                           "height": spec.get("height", 0), "genre": (t.get("genre") or "").strip()[:40],
                           "description": desc})
            if cap is not None and len(wanted) >= cap:
                break

        skipped = _already_here(request.user, {w["url"] for w in wanted})
        with transaction.atomic():
            made = [
                Post.objects.create(
                    author=request.user,
                    title=w["title"],
                    description=w["description"],
                    genre=w["genre"],
                    # The player, not a copy of the audio. SoundCloud stays the
                    # host; this is a post that frames their track.
                    embeds=[{"type": "soundcloud", "url": w["url"], "title": w["title"],
                             "aspect": w["aspect"], "height": w["height"]}],
                    visibility="private",
                )
                for w in wanted if w["url"] not in skipped
            ]

        parts = [f"{len(made)} track{'' if len(made) == 1 else 's'} imported as drafts. "
                 "They're private until you publish them."]
        if skipped:
            parts.append(f"{len(skipped)} were already here.")
        if private:
            parts.append(f"{private} private track{'' if private == 1 else 's'} left on SoundCloud — "
                         "make them public there to bring them in.")
        if not complete:
            parts.append("SoundCloud was slow, so this stopped partway — run it again for the rest; "
                         "nothing already imported comes in twice.")
        return Response({
            "imported": len(made),
            "already_here": len(skipped),
            "private_skipped": private,
            "complete": complete,
            "max_tracks": cap,
            "whole_catalogue": cap is None,
            # Said out loud because it is the whole reason this is safe to use:
            # the member handed over an authorisation and gets to see that
            # nothing was kept from it.
            "token_kept": False,
            "detail": " ".join(parts),
        }, status=status.HTTP_201_CREATED)
