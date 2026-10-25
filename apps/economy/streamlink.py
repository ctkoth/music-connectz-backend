"""Name a SoundCloud, Spotify or Apple Music link for the instrument coach.

This reads a link's PUBLIC title, artist and artwork and nothing else. None of
the three hands over audio an app may analyse, so the coach still hears only
what the member records or uploads; the link is context for the take.

The member's URL is never fetched. It is parsed, the service is decided by an
exact host match, and the only request made goes to that service's own oEmbed
endpoint (built here) with the link as a query parameter, so a crafted URL
cannot point the server at anything else. Apple Music has no public oEmbed, so
its title is read from the link's own slug and the artist is left blank.
"""
import re
from urllib.parse import unquote, urlparse

import requests
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

SERVICES = {
    "soundcloud": {"label": "SoundCloud", "hosts": {"soundcloud.com", "www.soundcloud.com", "on.soundcloud.com"},
                   "oembed": "https://soundcloud.com/oembed"},
    "spotify": {"label": "Spotify", "hosts": {"open.spotify.com"},
                "oembed": "https://open.spotify.com/oembed"},
    "apple": {"label": "Apple Music", "hosts": {"music.apple.com"}, "oembed": None},
}
NO_AUDIO = ("{label} doesn't give apps the audio, so the coach can't hear this track from the link. "
            "Record or upload your take below and the link stays as context.")


def classify(url):
    """(service_key, clean_url) for an https link on an exact service host, else (None, None)."""
    try:
        u = urlparse((url or "").strip())
    except ValueError:
        return None, None
    if u.scheme != "https" or u.username or u.password or u.port not in (None, 443):
        return None, None
    host = (u.hostname or "").lower()
    for key, s in SERVICES.items():
        if host in s["hosts"]:
            return key, u._replace(fragment="").geturl()
    return None, None


def _apple_title(url):
    parts = [p for p in urlparse(url).path.split("/") if p]
    # /us/album/<slug>/<id> or /us/song/<slug>/<id>
    for i, p in enumerate(parts):
        if p in ("album", "song", "playlist") and i + 1 < len(parts):
            return unquote(parts[i + 1]).replace("-", " ").strip().title()
    return ""


def describe(url):
    key, clean = classify(url)
    if not key:
        return None
    s = SERVICES[key]
    out = {"service": key, "label": s["label"], "url": clean, "title": "", "artist": "",
           "thumbnail": "", "audio_note": NO_AUDIO.format(label=s["label"])}
    if key == "apple":
        out["title"] = _apple_title(clean)
        return out
    try:
        r = requests.get(s["oembed"], params={"url": clean, "format": "json"}, timeout=5)
        d = r.json() if r.status_code == 200 else {}
    except (requests.RequestException, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    out["title"] = str(d.get("title") or "")[:200]
    out["artist"] = str(d.get("author_name") or "")[:120]
    thumb = str(d.get("thumbnail_url") or "")
    out["thumbnail"] = thumb if thumb.startswith("https://") else ""
    return out


class StreamLinkView(APIView):
    """GET /api/economy/streamlink/?url= — what the link is called, and what the coach can do with it."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        info = describe(request.query_params.get("url", ""))
        if not info:
            return Response({"detail": "That isn't a SoundCloud, Spotify or Apple Music link."},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(info)
