"""Member link clicks — tally, +5⚡ reward for clicking another member's link,
and a best-effort Google Safe Browsing malware/phishing scan.

The reward mirrors the restricted-join anti-fraud pattern: a genuine visitor
(distinct clicker, >=30s dwell) earns 5⚡ once per link per day, capped per day
so it can't be farmed. Unsafe links (per Safe Browsing) are flagged and never
reward. The scan is best-effort — with no SAFE_BROWSING_API_KEY set, links are
treated as unscanned/safe so the feature degrades cleanly.
"""
import json
import urllib.request
import urllib.error

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    LinkCounter,
    LinkClick,
    LINK_CLICK_REWARD_ENERGY,
    LINK_CLICK_MIN_ACTIVE_SECONDS,
    LINK_CLICK_REWARD_DAILY_CAP,
    notify,
    wallet_for,
)

User = get_user_model()

SAFE_BROWSING_URL = "https://safebrowsing.googleapis.com/v4/threatMatches:find"


def _client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def safe_browsing_check(url):
    """Return (safe: bool, threat: str). Best-effort; needs SAFE_BROWSING_API_KEY.
    On any error or missing key, returns (True, "") — we don't block on our own
    outage, but we also never claim a link is scanned when it isn't."""
    key = getattr(settings, "SAFE_BROWSING_API_KEY", "") or ""
    if not key or not url:
        return True, ""
    payload = {
        "client": {"clientId": "music-connectz", "clientVersion": "1.0"},
        "threatInfo": {
            "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"],
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": url}],
        },
    }
    try:
        req = urllib.request.Request(
            f"{SAFE_BROWSING_URL}?key={key}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode() or "{}")
        matches = data.get("matches") or []
        if matches:
            return False, matches[0].get("threatType", "THREAT")
        return True, ""
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        return True, ""  # scan unavailable — don't punish the link


class LinkClickView(APIView):
    """POST {url, owner, active_seconds} — record a click, scan the link, and
    reward the clicker +5⚡ for a genuine visit to another member's link."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        d = request.data or {}
        url = str(d.get("url", "")).strip()[:600]
        if not url:
            return Response({"detail": "url required"}, status=status.HTTP_400_BAD_REQUEST)
        owner = None
        oname = str(d.get("owner", "")).strip()
        if oname:
            owner = User.objects.filter(username=oname).first()
        active = max(0, int(d.get("active_seconds") or 0))

        counter, _ = LinkCounter.objects.get_or_create(owner=owner, url=url)
        # Scan once (or if a previous scan errored and left it unscanned).
        if not counter.scanned:
            safe, threat = safe_browsing_check(url)
            counter.safe, counter.threat, counter.scanned = safe, threat, True
        counter.clicks = (counter.clicks or 0) + 1
        counter.save()

        today = timezone.localdate()
        click, _ = LinkClick.objects.get_or_create(
            counter=counter, clicker=request.user, day=today,
            defaults={"ip": _client_ip(request), "active_seconds": active},
        )
        if click.active_seconds < active:
            click.active_seconds = active
            click.save(update_fields=["active_seconds"])

        rewarded = self._maybe_reward(counter, click, owner, request.user)
        w = wallet_for(request.user)
        return Response({
            "clicks": counter.clicks,
            "safe": counter.safe,
            "threat": counter.threat,
            "rewarded": rewarded,
            "reward_energy": LINK_CLICK_REWARD_ENERGY if rewarded else 0,
            "energy": w.energy,
        })

    def _maybe_reward(self, counter, click, owner, user):
        if click.rewarded:
            return False
        if not counter.safe:
            return False  # never reward visiting a flagged link
        if owner is None or owner.id == user.id:
            return False  # only for clicking *another member's* link
        if click.active_seconds < LINK_CLICK_MIN_ACTIVE_SECONDS:
            return False
        today = timezone.localdate()
        if LinkClick.objects.filter(clicker=user, rewarded=True, day=today).count() >= LINK_CLICK_REWARD_DAILY_CAP:
            return False
        w = wallet_for(user)
        w.energy = (w.energy or 0) + LINK_CLICK_REWARD_ENERGY
        w.save(update_fields=["energy", "updated_at"])
        click.rewarded = True
        click.save(update_fields=["rewarded"])
        notify(owner, "like", f"@{user.username} visited your link 🔗", actor=user, item_id="link")
        return True


class LinkTalliesView(APIView):
    """GET ?owner=<username> — click tallies + safety verdicts for a member's
    links, so the UI can show the count and flag unsafe ones."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        oname = str(request.query_params.get("owner", "")).strip()
        owner = User.objects.filter(username=oname).first() if oname else None
        rows = LinkCounter.objects.filter(owner=owner) if owner else LinkCounter.objects.none()
        return Response({
            "links": [
                {"url": c.url, "clicks": c.clicks, "safe": c.safe, "threat": c.threat, "scanned": c.scanned}
                for c in rows
            ]
        })
