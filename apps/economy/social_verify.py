"""SocialZ account verification — prove a linked social account (1) really has
the follower count claimed and (2) belongs to THIS member, so nobody games their
reach median by pasting a stranger's big account.

Two layers, most-trusted first:

1. OAuth-connect (definitive) — YouTube (Google OAuth we already have + YouTube
   Data API channels?part=statistics → subscriberCount) and Spotify (Spotify
   OAuth). Logging in proves ownership AND returns the real count. Needs
   provider keys (documented in docs/OAUTH_SETUP.md); returns 503 when a
   provider isn't configured so the client can fall back to layer 2.

2. Code-in-bio + AI read (works everywhere, incl. IG / TikTok / X / SoundCloud)
   — we issue a short code, the member drops it in their public bio, then we
   fetch the public page and ask the model to (a) confirm the code is present
   → proves same-user, and (b) read the displayed follower count → verifies the
   number. Best-effort: some platforms block server fetches; the UI labels
   those links "unverified" and they're excluded from the reach median.
"""
import os
import re
import secrets
from urllib.parse import urlencode, urlparse

import requests
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.utils import timezone

from .models import (SocialReview, energy_rate_per_hour, profile_for,
                     reach_median, social_sources)
from .social import featured_link_for

VERIFY_MODEL = "claude-opus-4-8"
CODE_PREFIX = "MCZ"


def _env(name):
    return os.environ.get(name, "").strip()


def _issue_code():
    return f"{CODE_PREFIX}-{secrets.token_hex(3).upper()}"


def _norm(url):
    return (url or "").strip().rstrip("/").lower()


def _find_link(links, url):
    target = _norm(url)
    for link in links:
        if isinstance(link, dict) and _norm(link.get("url")) == target:
            return link
    return None


def _fetch_public_page(url):
    """Fetch a public profile page's visible text. Returns (text, error)."""
    import requests
    try:
        resp = requests.get(
            url,
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0 (compatible; MusicConnectZ/1.0)"},
        )
        resp.raise_for_status()
    except Exception as exc:  # network, 403 (platform blocks bots), timeout
        return None, f"couldn't reach that page ({exc})"[:160]
    # Strip tags to visible text so the model reads the follower count + bio.
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", resp.text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text[:12000], None


def _ai_verify(page_text, code):
    """Ask the model whether `code` appears on the page and what follower count
    is shown. Returns (found: bool, followers: int|None, error)."""
    try:
        import anthropic
    except ImportError:
        return None, None, "verification backend unavailable"
    prompt = (
        "You are verifying ownership of a social media profile for Music ConnectZ.\n"
        f"The user was asked to place this exact verification code somewhere on their public "
        f"profile/bio: {code}\n\n"
        "Below is the visible text scraped from their public profile page. Answer STRICTLY as "
        "JSON with three keys:\n"
        '  "code_present": true/false — is the exact code above present in the text?\n'
        '  "followers": integer or null — the follower/subscriber count shown for this profile '
        "(expand 1.2k=1200, 3.4M=3400000; null if you can't find one).\n"
        '  "handle": string or null — the profile @handle/username if visible.\n'
        "Return ONLY the JSON object, nothing else.\n\n"
        f"PROFILE TEXT:\n{page_text}"
    )
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=VERIFY_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    except Exception as exc:
        return None, None, f"verification error: {exc}"[:160]
    import json
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None, None, "couldn't read the profile"
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None, None, "couldn't read the profile"
    followers = data.get("followers")
    try:
        followers = int(followers) if followers is not None else None
    except (TypeError, ValueError):
        followers = None
    return bool(data.get("code_present")), followers, None


def _ai_identity(page_text, user, profile):
    """Is this profile the same person as this member?

    Corey's rule: same name or same email means the same person. The model is
    asked for a verdict AND its reasoning, because "no" here sends a member to
    a queue and an unexplained refusal is not something anyone can act on.

    Deliberately NOT a yes/no: an artist whose stage name differs from their
    legal name is the normal case, and forcing a binary would make the model
    guess. `unsure` is a real answer and it routes to a human.
    """
    try:
        import anthropic
    except ImportError:
        return None, "", "verification backend unavailable"
    known = {
        "username": user.username,
        "display_name": getattr(profile, "display_name", "") or "",
        "email": (user.email or ""),
        "links": [l.get("url") for l in (profile.links or []) if isinstance(l, dict)][:10],
    }
    prompt = (
        "You are checking whether a public social profile belongs to a Music ConnectZ "
        "member, so their follower count can count toward their reach.\n\n"
        "Say YES only when the profile plausibly belongs to this person — a matching "
        "name, stage name, handle, or email. An artist's stage name differing from "
        "their username is COMMON and is not by itself a reason to say no. Say NO when "
        "it clearly belongs to somebody else (a different well-known person, a brand "
        "unrelated to them). Say UNSURE when there isn't enough to tell.\n\n"
        "Answer STRICTLY as JSON:\n"
        '  "same_person": "yes" | "no" | "unsure"\n'
        '  "reason": a short sentence a human reviewer can act on\n'
        '  "followers": integer or null (expand 1.2k=1200, 3.4M=3400000)\n'
        '  "handle": string or null\n'
        "Return ONLY the JSON object.\n\n"
        f"MEMBER: {known}\n\nPROFILE TEXT:\n{page_text}"
    )
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(model=VERIFY_MODEL, max_tokens=400,
                                      messages=[{"role": "user", "content": prompt}])
        raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    except Exception as exc:
        return None, "", f"verification error: {exc}"[:160]
    import json
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None, "", "couldn't read the profile"
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None, "", "couldn't read the profile"
    verdict = str(data.get("same_person", "")).lower()
    if verdict not in ("yes", "no", "unsure"):
        verdict = "unsure"
    followers = data.get("followers")
    try:
        followers = int(followers) if followers is not None else None
    except (TypeError, ValueError):
        followers = None
    return {"verdict": verdict, "followers": followers,
            "handle": str(data.get("handle") or "")[:120]}, str(data.get("reason") or "")[:500], None


def _energy_delta_for_link(user, links, link):
    """The ⚡/hour swing from this ONE link counting toward reach vs not —
    the number the cost/gain chip on each link is built from.

    A verified link shows what you'd LOSE by removing it (usually negative,
    but not always: dropping a low source can raise a median, same as it can
    for any set of numbers — the real arithmetic decides, never an assumed
    sign). An unverified link with a known claimed count (from a pending
    AI-flagged match) shows what you'd GAIN once it clears. None when there's
    no real number behind it yet — no fabricated projection for a link that
    is just a bare URL so far.
    """
    number = link.get("verified_count") if link.get("verified") else link.get("claimed_followers")
    if number is None:
        return None
    current = energy_rate_per_hour(user, links)
    toggled_link = (
        {**link, "verified": False}
        if link.get("verified")
        else {**link, "verified": True, "verified_count": number}
    )
    toggled = [toggled_link if ln is link else ln for ln in links]
    return energy_rate_per_hour(user, toggled) - current


class SocialVerifyView(APIView):
    """GET /api/economy/social/verify/ — every link + its verification state.

    POST /api/economy/social/verify/
    action="save"  {url, label?} → add/relabel a link, unverified, no checks run.
    action="remove" {url}        → drop a link entirely (un-features it too, if it was).
    action="feature" {url}       → pin one of your EXISTING links to the top of ProfileZ.
    action="unfeature"           → clear it (no url needed).
    action="start" {url}  → issue a code to paste in the profile bio.
    action="check" {url}  → fetch the public page, AI-confirm the code + read the
                            real follower count, mark the link verified.
    action="match" {url}  → no code needed; AI judges identity from the page.

    Returns the refreshed {sources, reach_median} so the client can redraw the
    median readout with the green ▲ / red ▼ delta.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Every link the member has added, with its verification state —
        the read nothing else here provides, since every POST action only
        returns this as a side effect of doing something to a link."""
        p = profile_for(request.user)
        links = p.links or []
        annotated = [{**ln, "energy_delta": _energy_delta_for_link(request.user, links, ln)}
                    for ln in links if isinstance(ln, dict)]
        return Response({
            "links": annotated,
            "sources": social_sources(request.user),
            "reach_median": reach_median(request.user),
            "featured_url": p.featured_url,
            "featured_link": featured_link_for(p),
        })

    def post(self, request):
        action = str(request.data.get("action", "start")).strip().lower()
        url = str(request.data.get("url", "")).strip()

        p = profile_for(request.user)
        links = list(p.links or [])

        if action == "unfeature":
            p.featured_url = ""
            p.save(update_fields=["featured_url", "updated_at"])
            return Response({"featured_url": "", "featured_link": None})

        if not url:
            return Response({"detail": "url required"}, status=status.HTTP_400_BAD_REQUEST)

        if action == "feature":
            if not any(_norm(ln.get("url")) == _norm(url) for ln in links if isinstance(ln, dict)):
                return Response({"detail": "Save this link first, then feature it."},
                                status=status.HTTP_400_BAD_REQUEST)
            p.featured_url = url
            p.save(update_fields=["featured_url", "updated_at"])
            return Response({"featured_url": url, "featured_link": featured_link_for(p)})

        if action == "remove":
            links = [ln for ln in links if _norm(ln.get("url")) != _norm(url)]
            p.links = links
            # A removed link can't stay pinned — nothing left for it to point at.
            if _norm(p.featured_url) == _norm(url):
                p.featured_url = ""
                p.save(update_fields=["links", "featured_url", "updated_at"])
            else:
                p.save(update_fields=["links", "updated_at"])
            SocialReview.objects.filter(user=request.user, url=url).delete()
            return Response({"removed": True, "sources": social_sources(request.user),
                             "reach_median": reach_median(request.user)})

        link = _find_link(links, url)
        if link is None:
            # Allow verifying (or just saving) a URL that isn't stored yet.
            link = {"label": str(request.data.get("label", "")).strip() or url, "url": url}
            links.append(link)

        if action == "save":
            # Add or relabel a link WITHOUT verifying it yet — verification
            # can come later (or never); a link is allowed to just sit on a
            # profile unverified, same as it always could once one existed.
            label = str(request.data.get("label", "")).strip()
            if label:
                link["label"] = label[:80]
            # `service` came from LinkDetectView (a domain match or an AI
            # guess) — stored so the client's icon lookup survives a reload
            # without re-detecting the same URL every time the page loads.
            service = str(request.data.get("service", "")).strip()
            if service:
                link["service"] = service[:40]
            link.setdefault("verified", False)
            p.links = links
            p.save(update_fields=["links", "updated_at"])
            return Response({"link": link, "sources": social_sources(request.user),
                             "reach_median": reach_median(request.user)})

        if action == "start":
            code = link.get("code") or _issue_code()
            link["code"] = code
            link["verified"] = False
            p.links = links
            p.save(update_fields=["links", "updated_at"])
            return Response({
                "code": code,
                "instructions": (
                    f"Add {code} anywhere in your public bio/description on that profile, "
                    "then tap Verify. We check it's really you and read your live follower "
                    "count — no typing numbers, no gaming it."
                ),
                "sources": social_sources(request.user),
                "reach_median": reach_median(request.user),
            })

        if action == "check":
            code = link.get("code")
            if not code:
                return Response({"detail": "start verification first"}, status=status.HTTP_400_BAD_REQUEST)
            page_text, err = _fetch_public_page(url)
            if err:
                return Response({
                    "detail": err,
                    "verified": False,
                    "hint": "Some platforms block automated checks. Try a public page, or connect via OAuth where available.",
                }, status=status.HTTP_502_BAD_GATEWAY)
            found, followers, err = _ai_verify(page_text, code)
            if err:
                return Response({"detail": err, "verified": False}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            if not found:
                return Response({
                    "detail": f"Couldn't find {code} on that profile yet. Add it to your bio and try again.",
                    "verified": False,
                }, status=status.HTTP_400_BAD_REQUEST)
            link["verified"] = True
            link["verified_at"] = timezone.now().isoformat()
            if followers is not None:
                link["verified_count"] = followers
                link["followers"] = followers
            p.links = links
            p.save(update_fields=["links", "updated_at"])
            return Response({
                "verified": True,
                "followers": followers,
                "sources": social_sources(request.user),
                "reach_median": reach_median(request.user),
            })

        if action == "match":
            # The quick route: no code to paste. The model reads the public page
            # and says whether it's the same person. A `no` or an `unsure` does
            # NOT refuse — it queues for a human, because most artists' stage
            # names don't match their legal names and refusing would strand them.
            page_text, err = _fetch_public_page(url)
            if err:
                return Response({
                    "detail": err, "verified": False,
                    "hint": "Some platforms block automated checks — use the code-in-bio route instead.",
                }, status=status.HTTP_502_BAD_GATEWAY)
            result, reason, err = _ai_identity(page_text, request.user, p)
            if err:
                return Response({"detail": err, "verified": False},
                                status=status.HTTP_503_SERVICE_UNAVAILABLE)

            if result["verdict"] == "yes":
                link["verified"] = True
                link["verified_at"] = timezone.now().isoformat()
                link["verified_by"] = "identity-match"
                if result["followers"] is not None:
                    link["verified_count"] = result["followers"]
                    link["followers"] = result["followers"]
                p.links = links
                p.save(update_fields=["links", "updated_at"])
                SocialReview.objects.filter(user=request.user, url=url).delete()
                return Response({
                    "verified": True, "verdict": "yes", "reason": reason,
                    "followers": result["followers"],
                    "sources": social_sources(request.user),
                    "reach_median": reach_median(request.user),
                })

            # Flagged. Saved unverified so it shows on the profile without
            # counting toward reach — being in the queue must not pay.
            link["verified"] = False
            link["review"] = "pending"
            # Stashed on the link itself (not only the SocialReview row) so
            # the ⚡/hour projection has a real number to project FROM the
            # moment it's flagged, not only once a human clears it.
            if result["followers"] is not None:
                link["claimed_followers"] = result["followers"]
            p.links = links
            p.save(update_fields=["links", "updated_at"])
            SocialReview.objects.update_or_create(
                user=request.user, url=url,
                defaults={"handle": result["handle"],
                          "claimed_followers": result["followers"] or 0,
                          "ai_verdict": result["verdict"], "ai_reason": reason,
                          "status": SocialReview.STATUS_PENDING, "decided_at": None},
            )
            return Response({
                "verified": False, "verdict": result["verdict"], "reason": reason,
                "review": "pending",
                "detail": "We couldn't confirm that account is yours, so it's gone to a "
                          "person to check. It doesn't count toward your reach until it "
                          "clears.",
                "faster": "Or paste our code in that profile's bio and verify instantly — "
                          "start the code route and it settles in a minute.",
                "sources": social_sources(request.user),
                "reach_median": reach_median(request.user),
            }, status=status.HTTP_202_ACCEPTED)

        return Response({"detail": "action must be save|remove|feature|unfeature|start|check|match"},
                        status=status.HTTP_400_BAD_REQUEST)


# host -> (service key, display label). The service key is what the client
# looks up a logo by, so it has to be stable — never rename one without
# updating the client's icon registry alongside it.
KNOWN_SERVICES = {
    "spotify.com": ("spotify", "Spotify"),
    "open.spotify.com": ("spotify", "Spotify"),
    "soundcloud.com": ("soundcloud", "SoundCloud"),
    "youtube.com": ("youtube", "YouTube"),
    "youtu.be": ("youtube", "YouTube"),
    "music.youtube.com": ("youtube", "YouTube"),
    "instagram.com": ("instagram", "Instagram"),
    "tiktok.com": ("tiktok", "TikTok"),
    "twitter.com": ("twitter", "Twitter / X"),
    "x.com": ("twitter", "Twitter / X"),
    "facebook.com": ("facebook", "Facebook"),
    "bandcamp.com": ("bandcamp", "Bandcamp"),
    "music.apple.com": ("apple_music", "Apple Music"),
    "discord.gg": ("discord", "Discord"),
    "discord.com": ("discord", "Discord"),
    "twitch.tv": ("twitch", "Twitch"),
    "patreon.com": ("patreon", "Patreon"),
    "linkedin.com": ("linkedin", "LinkedIn"),
    "github.com": ("github", "GitHub"),
    "threads.net": ("threads", "Threads"),
}


def _service_for_domain(host):
    host = (host or "").lower()
    if host.startswith("www."):
        host = host[4:]
    for domain, hit in KNOWN_SERVICES.items():
        if host == domain or host.endswith(f".{domain}"):
            return hit
    return None


def _ai_detect_service(host, url):
    """Ask the model what platform an UNRECOGNIZED domain belongs to. Only
    reached when KNOWN_SERVICES misses — the common case (Spotify, YouTube,
    Instagram, ...) never costs a call. Best-effort: a model that can't tell,
    or isn't configured, falls back to a generic 'website' link rather than
    blocking the member from saving it."""
    try:
        import anthropic
    except ImportError:
        return None, None
    prompt = (
        "What platform or service does this URL belong to?\n"
        f"URL: {url}\nHost: {host}\n\n"
        "Answer STRICTLY as JSON with two keys:\n"
        '  "service": a short lowercase_snake_case key for the platform (e.g. "bandcamp", '
        '"apple_music", "personal_website"), or null if you genuinely cannot tell\n'
        '  "label": a short human-readable name (e.g. "Bandcamp", "Apple Music", "Website")\n'
        "Return ONLY the JSON object."
    )
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(model=VERIFY_MODEL, max_tokens=100,
                                      messages=[{"role": "user", "content": prompt}])
        raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    except Exception:
        return None, None
    import json
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None, None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None, None
    service = str(data.get("service") or "")[:40].strip() or None
    label = str(data.get("label") or "")[:60].strip() or None
    return service, label


class LinkDetectView(APIView):
    """POST {url} -> {service, label, source} — recognize which platform a
    pasted link belongs to, so the client can show the right logo without
    the member hand-picking one from a list. A known domain (the common
    case) matches instantly and for free against KNOWN_SERVICES; an
    unrecognized one asks the model once rather than falling back to a bare
    "website" immediately — a hand-rolled domain list can never keep up with
    every platform a member might paste.

    Detection only — it does not save anything. The client still calls
    SocialVerifyView's action="save" (or a verify action) to actually add
    the link, using the service/label this returns.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        url = str(request.data.get("url", "")).strip()
        if not url:
            return Response({"detail": "url required"}, status=status.HTTP_400_BAD_REQUEST)
        parsed = urlparse(url if "://" in url else f"https://{url}")
        host = parsed.netloc or parsed.path.split("/")[0]

        hit = _service_for_domain(host)
        if hit:
            service, label = hit
            return Response({"service": service, "label": label, "source": "domain"})

        service, label = _ai_detect_service(host, url)
        return Response({
            "service": service or "website",
            "label": label or host or url,
            "source": "ai" if service else "fallback",
        })


YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"


class YouTubeVerifyView(APIView):
    """OAuth-connect verification for a member's own YouTube channel — the
    "layer 1" this module's docstring always described but never built. This
    module's other verification (code-in-bio + AI) exists precisely because
    OAuth-connect wasn't implemented for anything; it works everywhere but is
    best-effort (platforms block scraping) and can land a member in a human
    review queue. Signing in with Google and granting read-only YouTube access
    is definitive AND immediate: it proves ownership and returns the real
    subscriberCount in the same step — no queue, no code to paste, no page to
    fetch. Energy's hourly regen rate is reach ÷ tier, and reach is the
    median of VERIFIED sources — so a fast, sure way to verify one matters
    for more than just a badge on a profile.

    POST {action: "start", redirect_uri}
        -> {auth_url, state} — send the member to auth_url.
    POST {action: "finish", code, redirect_uri}
        -> exchanges the code, reads the channel's real statistics, and marks
           the matching Profile.links entry verified (creating one if the
           member hadn't already added a YouTube link).

    Needs GOOGLE_OAUTH_CLIENT_ID *and* GOOGLE_OAUTH_CLIENT_SECRET. The ID
    alone is enough for "Sign in with Google" (an ID-token check, no API
    access) but reading a channel's statistics needs an access-token
    exchange, which requires a confidential client — the secret "Sign in
    with Google" never needed.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        action = str(request.data.get("action", "")).strip().lower()
        client_id = _env("GOOGLE_OAUTH_CLIENT_ID")
        client_secret = _env("GOOGLE_OAUTH_CLIENT_SECRET")
        if not client_id or not client_secret:
            return Response(
                {"detail": "YouTube verification isn't configured on the server yet."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if action == "start":
            redirect_uri = str(request.data.get("redirect_uri", ""))
            if not redirect_uri:
                return Response({"detail": "redirect_uri required"}, status=status.HTTP_400_BAD_REQUEST)
            state = secrets.token_urlsafe(24)
            params = urlencode({
                "client_id": client_id, "redirect_uri": redirect_uri,
                "response_type": "code", "scope": YOUTUBE_SCOPE,
                "access_type": "online", "prompt": "consent", "state": state,
            })
            return Response({"auth_url": f"https://accounts.google.com/o/oauth2/v2/auth?{params}",
                             "state": state})

        if action == "finish":
            code = str(request.data.get("code", ""))
            redirect_uri = str(request.data.get("redirect_uri", ""))
            if not code:
                return Response({"detail": "code required"}, status=status.HTTP_400_BAD_REQUEST)
            try:
                token_resp = requests.post(
                    "https://oauth2.googleapis.com/token",
                    data={"code": code, "client_id": client_id, "client_secret": client_secret,
                          "redirect_uri": redirect_uri, "grant_type": "authorization_code"},
                    timeout=10,
                )
                access_token = (token_resp.json() or {}).get("access_token")
            except (requests.RequestException, ValueError):
                return Response({"detail": "Couldn't reach Google to verify that."},
                                status=status.HTTP_502_BAD_GATEWAY)
            if not access_token:
                return Response({"detail": "Google didn't grant access — try again."},
                                status=status.HTTP_400_BAD_REQUEST)

            try:
                yt_resp = requests.get(
                    "https://www.googleapis.com/youtube/v3/channels",
                    params={"part": "snippet,statistics", "mine": "true"},
                    headers={"Authorization": f"Bearer {access_token}"}, timeout=10,
                )
                data = yt_resp.json() or {}
            except (requests.RequestException, ValueError):
                return Response({"detail": "Couldn't reach YouTube to read the channel."},
                                status=status.HTTP_502_BAD_GATEWAY)
            items = data.get("items") or []
            if not items:
                return Response(
                    {"detail": "That Google account doesn't have a YouTube channel."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            channel = items[0]
            stats = channel.get("statistics") or {}
            channel_id = channel.get("id", "")
            title = (channel.get("snippet") or {}).get("title", "") or "YouTube"
            url = f"https://www.youtube.com/channel/{channel_id}"

            p = profile_for(request.user)
            links = list(p.links or [])
            link = _find_link(links, url)
            if link is None:
                link = {"label": title, "url": url}
                links.append(link)
            else:
                link["label"] = title
            link["verified_by"] = "oauth"
            link.pop("review", None)

            # A channel owner can hide their subscriber count. We've PROVEN
            # ownership either way — that's what the OAuth grant means — but
            # "verified" on a source means "real count", and there is none to
            # show. Marking it verified with a followers of 0 would drag the
            # reach median down for a number we were simply never told, which
            # is worse than not counting the source at all.
            followers = stats.get("subscriberCount")
            if followers is not None:
                followers = int(followers)
                link["verified"] = True
                link["verified_at"] = timezone.now().isoformat()
                link["verified_count"] = followers
                link["followers"] = followers
                link.pop("count_hidden", None)
            else:
                link["verified"] = False
                link["count_hidden"] = True
                link.pop("verified_count", None)

            p.links = links
            p.save(update_fields=["links", "updated_at"])
            SocialReview.objects.filter(user=request.user, url=url).delete()

            return Response({
                "verified": bool(followers is not None),
                "count_hidden": followers is None,
                "followers": followers,
                "label": title,
                "detail": None if followers is not None else (
                    "We confirmed this is your channel, but its subscriber count is hidden. "
                    "Make it public in YouTube Studio, then verify again, to have it count "
                    "toward your reach."
                ),
                "sources": social_sources(request.user),
                "reach_median": reach_median(request.user),
            })

        return Response({"detail": "action must be start|finish"}, status=status.HTTP_400_BAD_REQUEST)


class SocialReviewQueueView(APIView):
    """The manual verification queue — owner only.

    GET  lists what the model couldn't confirm, each with its reasoning.
    POST {id, decision: approve|reject, note} settles one.

    Approving marks the link verified, which is what lets its followers count
    toward reach and therefore toward Energy. That is the whole reason this
    queue exists rather than an auto-approve: reach pays, so a claim on
    somebody else's audience has to be somebody's decision.
    """

    permission_classes = [IsAuthenticated]

    def _is_owner(self, user):
        from .views import is_owner
        return is_owner(user)

    def get(self, request):
        if not self._is_owner(request.user):
            # A member sees their OWN pending reviews — waiting without being
            # able to see that you're waiting is its own small cruelty.
            mine = SocialReview.objects.filter(user=request.user)[:50]
            return Response({"mine": [self._row(r) for r in mine], "queue": None})
        qs = SocialReview.objects.filter(status=SocialReview.STATUS_PENDING)
        return Response({"queue": [self._row(r) for r in qs[:200]],
                         "pending": qs.count()})

    def _row(self, r):
        return {
            "id": r.id, "username": r.user.username, "url": r.url,
            "handle": r.handle, "claimed_followers": r.claimed_followers,
            "ai_verdict": r.ai_verdict, "ai_reason": r.ai_reason,
            "status": r.status, "note": r.note,
            "created_at": r.created_at.isoformat(),
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        }

    def post(self, request):
        if not self._is_owner(request.user):
            return Response({"detail": "Only the platform owner reviews these."},
                            status=status.HTTP_403_FORBIDDEN)
        d = request.data or {}
        r = SocialReview.objects.filter(pk=d.get("id")).select_related("user").first()
        if not r:
            return Response({"detail": "review not found"}, status=status.HTTP_404_NOT_FOUND)
        decision = str(d.get("decision", "")).lower()
        if decision not in ("approve", "reject"):
            return Response({"detail": "decision must be approve|reject"},
                            status=status.HTTP_400_BAD_REQUEST)

        p = profile_for(r.user)
        links = list(p.links or [])
        link = _find_link(links, r.url)
        if link is not None:
            link.pop("review", None)
            if decision == "approve":
                link["verified"] = True
                link["verified_at"] = timezone.now().isoformat()
                link["verified_by"] = "manual"
                if r.claimed_followers:
                    link["verified_count"] = r.claimed_followers
                    link["followers"] = r.claimed_followers
            else:
                link["verified"] = False
            p.links = links
            p.save(update_fields=["links", "updated_at"])

        r.status = (SocialReview.STATUS_APPROVED if decision == "approve"
                    else SocialReview.STATUS_REJECTED)
        r.reviewer = request.user
        r.note = str(d.get("note", ""))[:500]
        r.decided_at = timezone.now()
        r.save(update_fields=["status", "reviewer", "note", "decided_at"])

        from .models import notify
        notify(r.user, "verify",
               (f"Your {r.handle or 'social'} account was verified — its followers now "
                "count toward your reach ⚡" if decision == "approve"
                else f"We couldn't verify that account as yours. {r.note}".strip()),
               actor=request.user)
        return Response({"review": self._row(r),
                         "reach_median": reach_median(r.user)})
