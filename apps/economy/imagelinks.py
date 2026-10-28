"""A photo from Facebook, Instagram, X and the rest — fetched by its IMAGE address, safely.

LookZMaxZ reads a photo the member chose. Their photos already live on the social apps, so a
member can paste a picture's own address instead of saving and re-uploading it (Corey's ask).

Three rules hold it:

* **Only the platforms' own image hosts, and only https.** The host list is ours (`IMAGE_HOSTS`),
  so nothing a member types can point this server at an address of its choosing — the usual
  shape of a server-side request forgery. Redirects are refused rather than followed, for the
  same reason: the host that answers must be the host that was checked.
* **A post or profile PAGE is not a photo.** `instagram.com/p/…`, `x.com/…/status/…` and a
  Facebook photo page answer with a page, and the platforms do not serve those to anybody else's
  server. That is said BEFORE anything runs, with how to get the image itself (`page_hint`):
  copy the image address, or save the photo and attach it.
* **Bounded, checked, kept nowhere.** Streamed up to the caller's byte ceiling, refused unless the
  answer says it is an image, and returned as bytes for one reading. Nothing is written to storage.
"""
from urllib.parse import urlparse

import requests

# The platforms' image CDNs. A suffix match on a dot boundary: `cdninstagram.com` covers
# `scontent-lax3-1.cdninstagram.com`; `evilcdninstagram.com` is not covered.
IMAGE_HOSTS = {
    "fbcdn.net": "Facebook",
    "cdninstagram.com": "Instagram",
    "twimg.com": "X",
    "tiktokcdn.com": "TikTok", "tiktokcdn-us.com": "TikTok",
    "sc-cdn.net": "Snapchat",
    "licdn.com": "LinkedIn",
    "pinimg.com": "Pinterest",
    "googleusercontent.com": "Google",
    "ggpht.com": "YouTube",
}
# Page hosts: a link to a post or profile on these is a web page, never the image.
PAGE_HOSTS = {
    "facebook.com": "Facebook", "fb.com": "Facebook", "fb.watch": "Facebook",
    "instagram.com": "Instagram", "instagr.am": "Instagram", "threads.net": "Threads",
    "x.com": "X", "twitter.com": "X", "tiktok.com": "TikTok", "snapchat.com": "Snapchat",
    "linkedin.com": "LinkedIn", "pinterest.com": "Pinterest", "pin.it": "Pinterest",
}
TIMEOUT = 10
PAGE_HINT = ("That's a link to a {label} post or page, and {label} doesn't hand the photo to anyone "
             "else's server. Open the photo, then copy the IMAGE address (long-press or right-click "
             "the picture → Copy image address) and paste that — or save the photo and attach it.")
NOT_SUPPORTED = ("Paste the photo's own image address from Facebook, Instagram, X, TikTok, Snapchat, "
                 "LinkedIn or Pinterest — or attach the photo.")


def _match(host, table):
    for domain, label in table.items():
        if host == domain or host.endswith("." + domain):
            return label
    return None


def classify(url):
    """{"ok": True, "label"} for an image address we fetch; {"ok": False, "why"} otherwise."""
    raw = str(url or "").strip()[:2000]
    try:
        u = urlparse(raw)
    except ValueError:
        return {"ok": False, "why": NOT_SUPPORTED}
    host = (u.hostname or "").lower()
    if u.scheme != "https" or u.username or u.password or u.port not in (None, 443):
        return {"ok": False, "why": NOT_SUPPORTED}
    label = _match(host, IMAGE_HOSTS)
    if label:
        return {"ok": True, "label": label, "url": raw}
    page = _match(host, PAGE_HOSTS)
    if page:
        return {"ok": False, "label": page, "why": PAGE_HINT.format(label=page)}
    return {"ok": False, "why": NOT_SUPPORTED}


def fetch(url, max_bytes):
    """(bytes, content_type, None) or (None, None, sentence). Never follows a redirect."""
    c = classify(url)
    if not c["ok"]:
        return None, None, c["why"]
    try:
        with requests.get(c["url"], timeout=TIMEOUT, stream=True, allow_redirects=False,
                          headers={"Accept": "image/*", "User-Agent": "MusicConnectZ/1"}) as r:
            if r.status_code != 200:
                return None, None, (f"{c['label']} didn't hand that photo over ({r.status_code}). Image "
                                    "addresses from these apps expire — copy it again, or save the photo and attach it.")
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if not ctype.startswith("image/"):
                return None, None, "That address isn't a photo. Copy the image address itself, or attach the photo."
            out = bytearray()
            for chunk in r.iter_content(64 * 1024):
                out.extend(chunk)
                if len(out) > max_bytes:
                    return None, None, "That photo is bigger than the coach reads in one go."
            if not out:
                return None, None, "That address gave back an empty photo."
            return bytes(out), ctype, None
    except requests.RequestException:
        return None, None, f"Couldn't reach {c['label']} for that photo. Try again, or attach it."
