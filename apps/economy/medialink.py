"""A take from a link: what each kind of link can honestly give the coach.

Members asked to score "any media" by pasting a link. Three answers, and the
difference is whether we can lawfully get at the performance:

- **YouTube** — Gemini reads a public YouTube URL itself (`file_data.file_uri`),
  so nothing is downloaded here and no copy is kept. A private or unlisted-
  and-blocked video simply fails the run, and a failed run is not charged.
- **A direct file** (an .mp3/.wav/.mp4 URL, a Dropbox/Drive direct link) — we
  fetch it with the member's own size cap, refusing private network addresses
  so a pasted link can never make this server reach anything internal.
- **Streaming services** (Spotify, Apple Music, SoundCloud, Tidal, Deezer, Amazon)
  — refused with a sentence saying why. Spotify and Apple give apps no audio at
  all, and SoundCloud's terms forbid pulling a stream without their approval.
  A button that pretended otherwise would be the dead control this app keeps
  removing; the sentence points at the two doors that do work.
"""
import io
import ipaddress
import socket
from urllib.parse import urlparse, urljoin

import requests

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
NO_AUDIO = {
    "spotify": ("open.spotify.com", "spotify.com", "spotify.link"),
    "Apple Music": ("music.apple.com",),
    "SoundCloud": ("soundcloud.com", "on.soundcloud.com", "m.soundcloud.com"),
    "Tidal": ("tidal.com", "listen.tidal.com"),
    "Deezer": ("deezer.com", "www.deezer.com", "deezer.page.link"),
    "Amazon Music": ("music.amazon.com",),
}
NO_AUDIO_WHY = (
    "{name} doesn't give apps the audio, so the coach has nothing to listen to. "
    "Paste a YouTube link to the same performance, or attach the file itself. Nothing was charged."
)
MAX_REDIRECTS = 3
FETCH_TIMEOUT = 10


class YouTubeTake(io.BytesIO):
    """Stands in for a file: Gemini fetches the video from `youtube_uri` itself."""
    def __init__(self, uri):
        super().__init__(b"")
        self.youtube_uri = uri
        self.name = "youtube"
        self.size = 0


def _host(url):
    return (urlparse(url).hostname or "").lower()


def classify(url):
    """('youtube', url) | ('file', url) | ('refused', sentence) | ('bad', sentence)."""
    url = str(url or "").strip()
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return "bad", "That isn't a web link. Paste a full https:// address."
    host = p.hostname.lower()
    if host in YOUTUBE_HOSTS:
        return "youtube", url
    for name, hosts in NO_AUDIO.items():
        if host in hosts or any(host.endswith("." + h) for h in hosts):
            return "refused", NO_AUDIO_WHY.format(name=name.capitalize() if name == "spotify" else name)
    return "file", url


def _public(host):
    """True only when every address the host resolves to is a public one."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False
    return bool(infos)


def fetch_file(url, cap_bytes):
    """(file, content_type, None) or (None, None, sentence). Redirects are
    followed by hand so every hop's host is checked, not just the first."""
    for _ in range(MAX_REDIRECTS + 1):
        if urlparse(url).scheme not in ("http", "https") or not _public(_host(url)):
            return None, None, "That link points somewhere this server won't fetch from."
        try:
            r = requests.get(url, stream=True, timeout=FETCH_TIMEOUT, allow_redirects=False,
                             headers={"User-Agent": "MusicConnectZ-coach/1"})
        except requests.RequestException:
            return None, None, "That link didn't answer. Check it opens in a browser, or attach the file."
        if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, r.headers.get("Location", ""))
            r.close()
            continue
        break
    else:
        return None, None, "That link redirected too many times."
    if r.status_code != 200:
        r.close()
        return None, None, f"That link answered {r.status_code}, so there's nothing to score."
    ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if not (ctype.startswith("audio/") or ctype.startswith("video/")):
        r.close()
        return None, None, ("That link is a web page, not an audio or video file. "
                            "Use a direct file link, a YouTube link, or attach the file.")
    declared = int(r.headers.get("Content-Length") or 0)
    if declared and declared > cap_bytes:
        r.close()
        return None, None, f"That file is {declared / (1024 * 1024):.0f}MB, over your coach limit."
    buf = io.BytesIO()
    for chunk in r.iter_content(64 * 1024):
        buf.write(chunk)
        if buf.tell() > cap_bytes:
            r.close()
            return None, None, "That file is over your coach limit."
    r.close()
    if buf.tell() == 0:
        return None, None, "That link gave back an empty file."
    buf.seek(0)
    buf.name = (urlparse(url).path.rsplit("/", 1)[-1] or "linked-take")[:100]
    buf.size = len(buf.getvalue())
    return buf, ctype, None
