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
import re
import secrets

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import profile_for, reach_median, social_sources

VERIFY_MODEL = "claude-opus-4-8"
CODE_PREFIX = "MCZ"


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


class SocialVerifyView(APIView):
    """POST /api/economy/social/verify/

    action="start" {url}  → issue a code to paste in the profile bio.
    action="check" {url}  → fetch the public page, AI-confirm the code + read the
                            real follower count, mark the link verified.

    Returns the refreshed {sources, reach_median} so the client can redraw the
    median readout with the green ▲ / red ▼ delta.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        action = str(request.data.get("action", "start")).strip().lower()
        url = str(request.data.get("url", "")).strip()
        if not url:
            return Response({"detail": "url required"}, status=status.HTTP_400_BAD_REQUEST)

        p = profile_for(request.user)
        links = list(p.links or [])
        link = _find_link(links, url)
        if link is None:
            # Allow verifying a URL that isn't saved yet by adding a stub link.
            link = {"label": str(request.data.get("label", "")).strip() or url, "url": url}
            links.append(link)

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
            from django.utils import timezone
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

        return Response({"detail": "action must be start|check"}, status=status.HTTP_400_BAD_REQUEST)
