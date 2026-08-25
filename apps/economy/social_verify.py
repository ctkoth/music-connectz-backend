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
import logging
import re
import secrets

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.utils import timezone

from .models import SocialReview, profile_for, reach_median, social_sources

VERIFY_MODEL = "claude-opus-4-8"
CODE_PREFIX = "MCZ"

log = logging.getLogger(__name__)


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
    """Fetch a public profile page's visible text. Returns (text, error).

    The error is written for the member, not for us. It used to be the raw
    exception truncated to 160 characters, which on a real failure reached the
    screen as `couldn't reach that page (HTTPSConnectionPool(host='…', port=443):
    Max retries exceeded with url: /koth (Caused by ProxyError('Unable to
    connect to` — cut off mid-word, and telling nobody anything. The stack goes
    to the log where it's useful; the sentence goes to the person.
    """
    import requests
    try:
        resp = requests.get(
            url,
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0 (compatible; MusicConnectZ/1.0)"},
        )
        resp.raise_for_status()
    except requests.HTTPError as exc:
        code = getattr(getattr(exc, "response", None), "status_code", 0)
        log.warning("social verify: %s answered %s", url, code)
        return None, (
            "That page is private, gone, or blocking us."
            if code in (401, 403, 404, 451)
            else f"That page answered {code} instead of loading."
        )
    except requests.Timeout:
        log.warning("social verify: %s timed out", url)
        return None, "That page took too long to answer."
    except Exception as exc:  # DNS, TLS, connection reset, a malformed URL
        log.warning("social verify: couldn't fetch %s (%s)", url, exc)
        return None, "We couldn't open that page."
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
        # Same rule as the fetch above: the stack is ours, the sentence is theirs.
        log.warning("social verify: code read failed (%s)", exc)
        return None, None, "The checker didn't answer. Nothing was charged — try again in a minute."
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
        log.warning("social verify: identity read failed (%s)", exc)
        return None, "", "The checker didn't answer. Nothing was charged — try again in a minute."
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

        return Response({"detail": "action must be start|check|match"},
                        status=status.HTTP_400_BAD_REQUEST)


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
        # A member sees their OWN pending reviews — waiting without being able
        # to see that you're waiting is its own small cruelty. EVERYONE gets
        # `mine`, the owner included: the owner is also a member with links of
        # their own, and returning only the queue to them meant their own
        # screen was the one place that couldn't show why a link was waiting.
        mine = SocialReview.objects.filter(user=request.user)[:50]
        out = {"mine": [self._row(r) for r in mine], "queue": None}
        if self._is_owner(request.user):
            qs = SocialReview.objects.filter(status=SocialReview.STATUS_PENDING)
            out["queue"] = [self._row(r) for r in qs[:200]]
            out["pending"] = qs.count()
        return Response(out)

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
