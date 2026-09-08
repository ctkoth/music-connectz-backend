"""Member link clicks — tally, +5⚡ reward for clicking another member's link,
and a best-effort malware/phishing scan.

The reward mirrors the restricted-join anti-fraud pattern: a genuine visitor
(distinct clicker, >=30s dwell) earns 5⚡ once per link per day, capped per day
so it can't be farmed. Unsafe links are flagged and never reward. The scan is
best-effort — with no key set, links are treated as unscanned so the feature
degrades cleanly and WidgetZ refuses to frame a page nobody checked.

## Two scanners, and which one this platform is actually allowed to use

**Web Risk (`WEB_RISK_API_KEY`) is the one to set.** Google's own terms put
Safe Browsing v4 at "non-commercial use only — not for sale or revenue
generating purposes", and Music ConnectZ sells subscriptions, so v4 is the
wrong product here however well it works. v4 is also deprecated. Web Risk is
its commercial successor: same verdicts, a Cloud project with billing enabled,
free to 100k lookups a month.

Safe Browsing (`SAFE_BROWSING_API_KEY`) is still supported because it was here
first and because a non-commercial deployment of this code is entitled to it.
When both keys are set Web Risk wins — the licensed one should be the one that
answers.

**Neither key was readable until now.** `settings.SAFE_BROWSING_API_KEY` was
looked up with a `getattr` default and never defined in `settings.py`, so the
lookup returned "" on every deploy no matter what the dashboard said. Every
link on the platform went unscanned, silently, and setting the variable would
have changed nothing. Both names are read from the environment now.
"""
import json
import urllib.parse
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
WEB_RISK_URL = "https://webrisk.googleapis.com/v1/uris:search"

# The same four verdicts from both scanners, so a caller never has to know
# which one answered. Web Risk has no POTENTIALLY_HARMFUL_APPLICATION — that
# one is Android-specific and v4-only — so it asks for the three it has.
THREAT_TYPES = ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE"]


def _key(name):
    return (getattr(settings, name, "") or "").strip()


def scanner():
    """Which scanner is configured: "webrisk", "safebrowsing", or "".

    Web Risk wins when both are set. It is the one this platform is licensed
    for — Safe Browsing v4 is non-commercial-only by Google's terms — so if
    somebody has gone to the trouble of setting it, it should be the one that
    answers rather than sitting behind a key that happened to be there first.
    """
    if _key("WEB_RISK_API_KEY"):
        return "webrisk"
    if _key("SAFE_BROWSING_API_KEY"):
        return "safebrowsing"
    return ""


def scan_available():
    """Whether a scan can actually happen — i.e. whether a key is configured.

    Separated from the scan itself because `safe_browsing_check` answers
    "safe" when it cannot look, which is the right answer for a click (we do
    not block a member on our own outage) and the wrong one for anything that
    treats a verdict as a permission. WidgetZ frames a page only when the scan
    CLEARED it, and a link nobody scanned cleared nothing.
    """
    return bool(scanner())


def _client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


NETWORK_ERRORS = (urllib.error.URLError, ValueError, TimeoutError, OSError)


def _web_risk(url, key):
    """Web Risk `uris:search` — a GET, and an empty body means clean."""
    query = urllib.parse.urlencode(
        [("key", key), ("uri", url)] + [("threatTypes", t) for t in THREAT_TYPES])
    req = urllib.request.Request(f"{WEB_RISK_URL}?{query}")
    with urllib.request.urlopen(req, timeout=4) as resp:
        data = json.loads(resp.read().decode() or "{}")
    threats = ((data.get("threat") or {}).get("threatTypes")) or []
    return (False, threats[0]) if threats else (True, "")


def _safe_browsing(url, key):
    """Safe Browsing v4 `threatMatches:find` — a POST, no matches means clean."""
    payload = {
        "client": {"clientId": "music-connectz", "clientVersion": "1.0"},
        "threatInfo": {
            # POTENTIALLY_HARMFUL_APPLICATION is v4-only, so it is asked for
            # here and not in the shared list.
            "threatTypes": THREAT_TYPES + ["POTENTIALLY_HARMFUL_APPLICATION"],
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": url}],
        },
    }
    req = urllib.request.Request(
        f"{SAFE_BROWSING_URL}?key={key}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=4) as resp:
        data = json.loads(resp.read().decode() or "{}")
    matches = data.get("matches") or []
    return (False, matches[0].get("threatType", "THREAT")) if matches else (True, "")


def safe_browsing_check(url):
    """Return (safe: bool, threat: str) from whichever scanner is configured.

    Best-effort by design: on any error, a timeout or no key at all it returns
    (True, "") — we do not block a member on our own outage. That is why it is
    never the thing that decides a permission; `scan_available()` and the
    `scanned` column are, and they say whether anybody actually looked.

    The name is unchanged although it now speaks to two scanners: it is the
    call site vocabulary across links, widgetz and the tests, and renaming it
    to say "google" or "webrisk" would tie every caller to whichever product
    the billing account happens to be on.
    """
    which = scanner()
    if not which or not url:
        return True, ""
    try:
        if which == "webrisk":
            return _web_risk(url, _key("WEB_RISK_API_KEY"))
        return _safe_browsing(url, _key("SAFE_BROWSING_API_KEY"))
    except NETWORK_ERRORS:
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
            counter.safe, counter.threat = safe, threat
            # Only a scan that RAN marks the row scanned. This used to set the
            # flag either way, so a deploy with no key recorded every link as
            # checked and clean — the docstring above already said we never
            # claim a link is scanned when it isn't, and the column said we do.
            # Nothing read it closely enough to catch that until WidgetZ, which
            # frames a page only on a real verdict.
            counter.scanned = scan_available()
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
