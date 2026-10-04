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
import re
from urllib.parse import quote, urlparse

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


_SECRET_TRACK = re.compile(r"^/tracks/\d+$")


def _private_player(t):
    """The widget for a PRIVATE track, built from its secret address, or None.

    SoundCloud's public player shows "track not found" for a private track;
    it plays one only when handed the track's API uri with its secret token.
    Built here, never from member input, and only on SoundCloud's own API host
    — the same rule `widgetz` follows for every player: we decide the origin
    that gets framed and a link only ever arrives as a query parameter.
    """
    secret = (t.get("secret_uri") or "").strip()
    if not secret and t.get("id") and t.get("secret_token"):
        secret = f"https://api.soundcloud.com/tracks/{int(t['id'])}?secret_token={t['secret_token']}"
    u = urlparse(secret)
    if u.scheme != "https" or u.hostname != API_HOST or not _SECRET_TRACK.match(u.path) \
            or not u.query.startswith("secret_token="):
        return None
    return {"src": ("https://w.soundcloud.com/player/?url=" + quote(secret, safe="")
                    + "&color=%23ff5500&auto_play=false&show_comments=true&show_user=true"),
            "height": 166}


def has_private_track(post):
    """True when a post frames a track that is private on SoundCloud.

    Publishing such a post shares its secret link with everyone who can see
    it, so `postz` asks before letting it out of draft.
    """
    return any(isinstance(e, dict) and e.get("private_on_sc") for e in (post.embeds or []))


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


def _already_here(user, widget_urls, sc_ids=()):
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
            if not isinstance(e, dict):
                continue
            if e.get("url") in widget_urls:
                seen.add(e["url"])
            # Matched on the SoundCloud id as well: a track imported while
            # private and later made public there has a different player
            # address, and must not come in a second time.
            if e.get("sc_id") and e["sc_id"] in sc_ids:
                seen.add(("id", e["sc_id"]))
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
            # A private track comes in as a PRIVATE draft, played through its
            # secret address. It is flagged on the embed, because publishing
            # it would hand that secret link to everybody who can see the
            # post — `postz` refuses to publish one without being told the
            # member means it. One with no usable secret address is left on
            # SoundCloud and counted, rather than imported as a dead player.
            is_private = (t.get("sharing") or "public") != "public"
            if is_private:
                spec = _private_player(t)
                if not spec:
                    private += 1
                    continue
            else:
                # Resolved through the SAME widget builder `views._parse_embed_url`
                # and the manual "add a track" flow use, so an imported post and
                # a hand-added one store the identical embed shape. Storing the
                # raw `permalink_url` once framed soundcloud.com itself instead
                # of `w.soundcloud.com/player`.
                spec = _player_for(permalink)
            if not spec:
                continue
            desc = (t.get("description") or "").strip()
            if over_char_limit(desc, tier):
                desc = desc[:char_cap]
            wanted.append({"url": spec["src"], "title": title, "aspect": spec.get("aspect", ""),
                           "height": spec.get("height", 0), "genre": (t.get("genre") or "").strip()[:40],
                           "description": desc, "private": is_private,
                           "sc_id": str(t.get("id") or "")})
            if cap is not None and len(wanted) >= cap:
                break

        skipped = _already_here(request.user, {w["url"] for w in wanted},
                                {w["sc_id"] for w in wanted if w["sc_id"]})

        def here(w):
            return w["url"] in skipped or (w["sc_id"] and ("id", w["sc_id"]) in skipped)
        fresh = [w for w in wanted if not here(w)]
        already = len(wanted) - len(fresh)
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
                             "aspect": w["aspect"], "height": w["height"], "sc_id": w["sc_id"],
                             **({"private_on_sc": True} if w["private"] else {})}],
                    visibility="private",
                )
                for w in fresh
            ]
        private_in = sum(1 for w in fresh if w["private"])

        parts = [f"{len(made)} track{'' if len(made) == 1 else 's'} imported as drafts. "
                 "They're private until you publish them."]
        if already:
            parts.append(f"{already} were already here.")
        if private_in:
            parts.append(f"{private_in} of them {'is' if private_in == 1 else 'are'} private on SoundCloud "
                         "and marked so — publishing one shares its secret link, so you'll be asked first.")
        if private:
            parts.append(f"{private} private track{'' if private == 1 else 's'} couldn't come in "
                         "(SoundCloud gave no secret link for them).")
        if not complete:
            parts.append("SoundCloud was slow, so this stopped partway — run it again for the rest; "
                         "nothing already imported comes in twice.")
        return Response({
            "imported": len(made),
            "already_here": already,
            "private_imported": private_in,
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
