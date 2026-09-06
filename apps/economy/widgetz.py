"""WidgetZ — a link that opens ON the screen instead of taking the member off it.

A profile link was a `<a target="_blank">` and nothing else, which is the exact
dead end the cross-pollination rule exists to close: the member leaves, the
screen they were reading is behind a tab they now have to find again, and
whatever they were going to do with the link's contents happens somewhere we
cannot help with. A widget keeps it on the same screen, beside everything else
they had open.

**There are three ways a link can open, and the difference is who wrote the
URL we frame.**

* **`player`** — a provider with a documented embed endpoint (YouTube, Spotify,
  SoundCloud, Apple Music, Deezer, Vimeo, Mixcloud, TikTok, Instagram). We do
  not frame the page the member pasted; we read an id out of it and build the
  PROVIDER'S OWN player URL. The address in the frame is one this file wrote,
  so there is nothing a member can put in a link that changes what loads.
  Available at every tier, for that reason.
* **`internal`** — one of our own public addresses (`/p/…`, `/u/…`, `/pl/…`).
  Never framed at all: the client opens the real screen in-app, which is
  strictly better than an iframe of ourselves.
* **`page`** — anything else: an arbitrary third-party page, framed whole.
  **This one is StatZ, and only for a URL that has come back clean from the
  malware/phishing scan.** Both halves of that are Corey's call and both are
  about the same risk: a page rendered inside our own chrome borrows our
  chrome's credibility, which is what makes a framed login form worth building
  for somebody who wants one. A scan verdict is the floor, and the tier is who
  we are willing to hand a general-purpose frame to.

Nobody loses the link. `page` refused — wrong tier, unscanned, or flagged —
still returns the link with `mode: "outside"`, which is precisely what every
tier has today: it opens in a new tab. The tier buys where it opens, not
whether it opens, which is the ladder rule this file has to answer to.

**An unscanned link has not cleared anything.** With no `SAFE_BROWSING_API_KEY`
configured there is no verdict, and a `page` widget is refused for everyone,
including StatZ, with that as the stated reason. Treating "we never looked" as
"it's fine" would make the scan requirement decorative — and a decorative
safety check is worse than none, because it is the one people trust.

The frame itself is sandboxed and the client says so; see `SANDBOX`.
"""
import re
from urllib.parse import parse_qs, quote, urlparse

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .links import safe_browsing_check, scan_available
from .models import (
    LINK_CLICK_MIN_ACTIVE_SECONDS,
    LINK_CLICK_REWARD_DAILY_CAP,
    LINK_CLICK_REWARD_ENERGY,
    TIER_DEBUG,
    TIER_STATZ,
    LinkCounter,
    membership_for,
)
from .personaz import clean_link

# Who may frame an arbitrary third-party page. Players and our own screens are
# not on this ladder — they are available to everybody.
PAGE_TIERS = (TIER_STATZ, TIER_DEBUG)

# What the frame is allowed to do. `allow-scripts` + `allow-same-origin` is the
# combination that lets a sandboxed frame remove its own sandbox, so the pair is
# never granted together: a page widget gets scripts and no same-origin, which
# is what makes it a viewer rather than a tenant. `allow-popups` is out — a
# framed page that can open windows is a framed page that can open a window
# over ours.
SANDBOX = "allow-scripts allow-forms allow-popups-to-escape-sandbox"

# Players are the provider's own embed, so they get the referrer they expect
# and the permissions their players need. Nothing else does.
PLAYER_ALLOW = "accelerometer; autoplay; clipboard-write; encrypted-media; picture-in-picture; fullscreen"

# Our own public addresses, and the in-app screen each one IS. A widget for one
# of these is not a frame — it is the real screen, which the client already has.
OUR_ROUTES = [
    (re.compile(r"^/p/([^/]+)/?$"), "post"),
    (re.compile(r"^/u/([^/]+)/?$"), "member"),
    (re.compile(r"^/pl/([^/]+)/?$"), "playlist"),
]


def _host(url):
    try:
        h = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def _is(host, *suffixes):
    return any(host == s or host.endswith("." + s) for s in suffixes)


def _our_hosts():
    """Every host that is us. FRONTEND_URL is the deployed one; the rest are
    what a member actually types when they paste their own profile link."""
    out = {_host(getattr(settings, "FRONTEND_URL", "") or "")}
    out.add("musicconnectz.net")
    return {h for h in out if h}


# ---- Players ----------------------------------------------------------------
#
# Each builder takes the parsed URL and returns the frame spec, or None when the
# link is that provider's but not something the provider will play (a Spotify
# user page, a YouTube channel). None means `outside`, never a blank frame:
# a widget that loads nothing is worse than a link that opened a tab.
#
# `aspect` sizes a frame that scales with its column. `height` sizes one whose
# player is a fixed bar and looks wrong stretched. A spec has exactly one.


def _youtube(u):
    host, path, q = _host(u.geturl()), u.path, parse_qs(u.query or "")
    vid = ""
    if _is(host, "youtu.be"):
        vid = path.strip("/").split("/")[0]
    elif path.startswith("/watch"):
        vid = (q.get("v") or [""])[0]
    elif path.startswith("/embed/") or path.startswith("/shorts/") or path.startswith("/live/"):
        vid = path.split("/")[2] if len(path.split("/")) > 2 else ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid or ""):
        return None
    # youtube-nocookie, because a widget the member opened to hear a track
    # should not also be the thing that plants an ad profile on them. It plays
    # identically; the only difference is what it stores.
    short = path.startswith("/shorts/")
    return {
        "provider": "youtube", "label": "YouTube",
        "src": f"https://www.youtube-nocookie.com/embed/{vid}",
        "aspect": "9/16" if short else "16/9", "min_px": 260 if short else 300,
    }


_SPOTIFY_KINDS = {"track": 152, "episode": 232, "album": 380, "playlist": 380,
                  "artist": 380, "show": 232}


def _spotify(u):
    parts = [p for p in u.path.split("/") if p]
    # /intl-de/track/<id> — Spotify localises its own share links.
    if parts and parts[0].startswith("intl-"):
        parts = parts[1:]
    if len(parts) < 2 or parts[0] not in _SPOTIFY_KINDS:
        return None
    kind, sid = parts[0], parts[1]
    if not re.fullmatch(r"[A-Za-z0-9]{16,32}", sid):
        return None
    return {
        "provider": "spotify", "label": "Spotify",
        "src": f"https://open.spotify.com/embed/{kind}/{sid}",
        "height": _SPOTIFY_KINDS[kind], "min_px": 280,
    }


def _soundcloud(u):
    # SoundCloud's widget takes the track URL itself, so there is no id to read
    # — but it is still OUR url that gets framed: the player origin is fixed
    # here and the member's link only ever reaches it as a query parameter.
    parts = [p for p in u.path.split("/") if p]
    if not parts:
        return None
    # `on.soundcloud.com/xyz` is a redirect, not an address the widget can
    # resolve — following it would mean a server-side fetch of a link a member
    # supplied, which is a much bigger thing than a player. It opens outside.
    if _host(u.geturl()) != "soundcloud.com":
        return None
    clean = f"https://soundcloud.com{u.path}"
    return {
        "provider": "soundcloud", "label": "SoundCloud",
        "src": ("https://w.soundcloud.com/player/?url=" + quote(clean, safe="")
                + "&color=%23ff5500&auto_play=false&show_comments=true&show_user=true"),
        "height": 166 if len(parts) >= 2 else 400, "min_px": 260,
    }


def _apple(u):
    if not u.path.strip("/"):
        return None
    # `?i=<track id>` is how Apple points at ONE song inside an album, and it
    # is the difference between a 175px bar and a 450px track list. Read from
    # the parsed query rather than by looking for "i=" in the string, which
    # also matches the tail of every other parameter name.
    one_song = bool(parse_qs(u.query or "").get("i"))
    return {
        "provider": "apple", "label": "Apple Music",
        "src": f"https://embed.music.apple.com{u.path}" + (f"?{u.query}" if u.query else ""),
        "height": 175 if one_song else 450,
        "min_px": 280,
    }


_DEEZER_KINDS = {"track": 92, "album": 300, "playlist": 300, "artist": 300, "episode": 92}


def _deezer(u):
    parts = [p for p in u.path.split("/") if p]
    # /en/track/123 — Deezer prefixes a language.
    if parts and len(parts[0]) == 2:
        parts = parts[1:]
    if len(parts) < 2 or parts[0] not in _DEEZER_KINDS or not parts[1].isdigit():
        return None
    return {
        "provider": "deezer", "label": "Deezer",
        "src": f"https://widget.deezer.com/widget/dark/{parts[0]}/{parts[1]}",
        "height": _DEEZER_KINDS[parts[0]], "min_px": 280,
    }


def _vimeo(u):
    m = re.search(r"/(\d{6,})", u.path)
    if not m:
        return None
    return {
        "provider": "vimeo", "label": "Vimeo",
        "src": f"https://player.vimeo.com/video/{m.group(1)}",
        "aspect": "16/9", "min_px": 300,
    }


def _mixcloud(u):
    parts = [p for p in u.path.split("/") if p]
    if len(parts) < 2:
        return None
    feed = quote("/" + "/".join(parts) + "/", safe="")
    return {
        "provider": "mixcloud", "label": "Mixcloud",
        "src": f"https://www.mixcloud.com/widget/iframe/?feed={feed}&hide_cover=1",
        "height": 120, "min_px": 280,
    }


def _tiktok(u):
    m = re.search(r"/video/(\d{6,})", u.path)
    if not m:
        return None
    return {
        "provider": "tiktok", "label": "TikTok",
        "src": f"https://www.tiktok.com/embed/v2/{m.group(1)}",
        "aspect": "9/16", "min_px": 260,
    }


def _instagram(u):
    m = re.match(r"^/(?:p|reel|tv)/([A-Za-z0-9_-]+)", u.path)
    if not m:
        return None
    return {
        "provider": "instagram", "label": "Instagram",
        "src": f"https://www.instagram.com/p/{m.group(1)}/embed",
        "aspect": "4/5", "min_px": 300,
    }


# Host suffix → builder. Order does not matter; a host matches one of these or
# it is not a player.
PLAYERS = [
    (("youtube.com", "youtu.be"), _youtube),
    (("spotify.com",), _spotify),
    (("soundcloud.com",), _soundcloud),
    (("music.apple.com", "embed.music.apple.com"), _apple),
    (("deezer.com",), _deezer),
    (("vimeo.com",), _vimeo),
    (("mixcloud.com",), _mixcloud),
    (("tiktok.com",), _tiktok),
    (("instagram.com",), _instagram),
]

# What the client may advertise before a member opens anything. Names only —
# the ladder and the reasons are published by GET, so no screen retypes them.
PLAYER_LABELS = ["YouTube", "Spotify", "SoundCloud", "Apple Music", "Deezer",
                 "Vimeo", "Mixcloud", "TikTok", "Instagram"]


def _player_for(url):
    host = _host(url)
    if not host:
        return None
    try:
        u = urlparse(url)
    except ValueError:
        return None
    for suffixes, build in PLAYERS:
        if _is(host, *suffixes):
            try:
                return build(u)
            except (ValueError, IndexError, AttributeError):
                return None
    return None


def _internal_for(url):
    """One of our own public addresses, as the in-app screen it really is."""
    try:
        u = urlparse(url)
    except ValueError:
        return None
    if _host(url) not in _our_hosts():
        return None
    for pattern, kind in OUR_ROUTES:
        m = pattern.match(u.path or "/")
        if m:
            return {"kind": kind, "key": m.group(1)}
    # Our own site, but not a public permalink: /post, /sing, an app tab.
    slug = (u.path or "/").strip("/").split("/")[0]
    return {"kind": "tab", "key": slug} if slug else {"kind": "tab", "key": "postz"}


def can_frame_pages(tier):
    return tier in PAGE_TIERS


def scan_verdict(url, owner=None):
    """(scanned, safe, threat) for a URL, scanning once and remembering it.

    The verdict lives on `LinkCounter`, which is the same row the click tally
    uses, so a link scanned for a widget is a link already scanned for a click
    and neither pays for the other's lookup.
    """
    counter, _ = LinkCounter.objects.get_or_create(owner=owner, url=url[:600])
    if not counter.scanned:
        if not scan_available():
            return False, counter.safe, ""
        safe, threat = safe_browsing_check(url)
        counter.safe, counter.threat, counter.scanned = safe, threat, True
        counter.save(update_fields=["safe", "threat", "scanned"])
    return counter.scanned, counter.safe, counter.threat


def widget_for(url, tier, owner=None):
    """How one link opens, and — when it cannot open on the screen — why not.

    Always returns a widget. `mode: "outside"` is not a failure; it is the
    behaviour every link has today, carried through with the reason attached so
    the client can say it rather than leaving a control that quietly does
    something else than the one beside it.
    """
    link = clean_link({"url": url})
    if not link:
        return {"mode": "refused", "url": "", "reason": "That link isn't one we'll open."}
    url = link["url"]
    host = _host(url)
    base = {"url": url, "host": host, "sandbox": SANDBOX}

    internal = _internal_for(url)
    if internal:
        return {**base, "mode": "internal", "target": internal,
                "label": "Music ConnectZ",
                "reason": "This one is ours — it opens as the real screen, not a frame."}

    player = _player_for(url)
    if player:
        return {**base, "mode": "player", "allow": PLAYER_ALLOW, "may_refuse": False, **player}

    # An arbitrary page from here down: the tier gate and the scan.
    if not can_frame_pages(tier):
        return {**base, "mode": "outside", "label": host or "Link",
                "gate": "tier", "needs_tier": TIER_STATZ,
                "reason": "Outside pages open as widgets on StatZ. This one opens in a new tab."}
    scanned, safe, threat = scan_verdict(url, owner)
    if not scanned:
        return {**base, "mode": "outside", "label": host or "Link",
                "gate": "unscanned",
                "reason": "We can't scan links for malware right now, and an unscanned "
                          "page doesn't get framed. It opens in a new tab."}
    if not safe:
        return {**base, "mode": "outside", "label": host or "Link",
                "gate": "unsafe", "threat": threat,
                "reason": f"The scan flagged this link ({threat or 'unsafe'}). "
                          "It won't open on the screen, and think twice about opening it at all."}
    return {**base, "mode": "page", "label": host or "Link", "src": url,
            "aspect": "4/3", "min_px": 320, "scanned": True, "safe": True,
            # X-Frame-Options and frame-ancestors are decided by the site, not
            # by us, and there is no way to ask ahead of time — a refused frame
            # and a slow one look identical from here. So the client is told
            # this can still come up empty, and keeps the way out on screen.
            "may_refuse": True}


class WidgetZView(APIView):
    """GET — the whole policy, before a member opens anything.

    Published rather than hardcoded for the same reason every other ladder is:
    the tier that buys page widgets, the scan requirement and the ⚡ a genuine
    visit pays all belong to one place, and a screen that retypes them is a
    screen that drifts from them.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        m = membership_for(request.user)
        return Response({
            "tier": m.tier,
            "players": PLAYER_LABELS,
            "page_widgets": {
                "allowed": can_frame_pages(m.tier),
                "needs_tier": TIER_STATZ,
                "scan_available": scan_available(),
                "why": "A framed page borrows this app's chrome, so it's StatZ and "
                       "only for links the malware scan has cleared. Every tier can "
                       "still open any link in a new tab.",
            },
            # The gain, up front: this is what a genuine visit to another
            # member's link pays, and it is the reason to open one at all.
            "reward": {
                "energy": LINK_CLICK_REWARD_ENERGY,
                "after_seconds": LINK_CLICK_MIN_ACTIVE_SECONDS,
                "daily_cap": LINK_CLICK_REWARD_DAILY_CAP,
            },
        })


class WidgetOpenView(APIView):
    """POST {url, owner} — how this one link opens.

    One link per call on purpose: the scan is a network round trip and a member
    opens widgets one at a time. A list endpoint would scan a whole profile's
    links because somebody looked at the profile.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        d = request.data or {}
        url = str(d.get("url", "")).strip()[:600]
        if not url:
            return Response({"detail": "url required"}, status=status.HTTP_400_BAD_REQUEST)
        owner = None
        oname = str(d.get("owner", "")).strip()
        if oname:
            from django.contrib.auth import get_user_model
            owner = get_user_model().objects.filter(username=oname).first()
        m = membership_for(request.user)
        return Response(widget_for(url, m.tier, owner))
