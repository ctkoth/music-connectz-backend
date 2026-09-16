"""Trial Boss Take — one scored take, no account.

The strongest thing Music ConnectZ can hand a stranger is a number about
THEMSELVES. Reading about a vocal coach persuades nobody; being told your take
is a 6 and exactly which two things cost you the other four is a different
conversation. So the door is a take, not a tour.

Two rules hold it together:

1. **It is graded by the same rubric a member's take is** (`score_take`). A
   trial that grades easier is a lie the first real take exposes.
2. **It is capped, hard.** An unauthenticated endpoint that spends real money
   is a bill anybody with curl can run up. One per address per day, plus a
   global daily ceiling that refuses rather than overspends.

Nothing here moves a member resource — a visitor has no wallet, so there is no
⚡/🍥/🏷️ to state. The cost is ours; the gain is theirs, and the response says
so before asking them to sign up.
"""
import os
import secrets

from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .gemini import _key
from .instruments import DIFFICULTIES, profile_for_app
from .instruments import (LYRIC_SCORE, MIX_SCORE, rates_lyrics, rates_mix,
                          scores_for)
from .models import (
    TRIAL_CLAIM_DAYS,
    TRIAL_MAX_MB,
    TRIAL_PER_BROWSER,
    TRIAL_PER_IP,
    TRIAL_PER_IP_HOURS,
    TrialTake,
    trial_daily_cap,
)
from .vocalcoach import score_take


# How many proxies of OURS sit in front of this app. Render is one; put a CDN
# in front and it is two.
TRUSTED_PROXY_HOPS = max(1, int(os.environ.get("TRUSTED_PROXY_HOPS", "1")))


def client_ip(request):
    """The caller's address, taken from the end of X-Forwarded-For we control.

    This read `[0]` and that is the one entry an attacker owns. Each proxy
    APPENDS the address it saw, so a request arriving with its own
    `X-Forwarded-For: 1.2.3.4` comes out of our proxy as `1.2.3.4, <real>` —
    and `[0]` is the value the client invented. Anything keyed on it (the
    trial's per-address ceiling, for one) was bypassable with a header, while
    still being perfectly binding on honest visitors who send no such header.

    So count from the RIGHT, skipping our own hops. Set TRUSTED_PROXY_HOPS if
    a CDN is added in front; too small over-trusts, too large reads one of our
    own proxies and collapses every visitor onto one address, which is why the
    per-IP ceiling is a loose backstop rather than the thing that decides.
    """
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        chain = [p.strip() for p in fwd.split(",") if p.strip()]
        if chain:
            return chain[-min(TRUSTED_PROXY_HOPS, len(chain))][:64]
    return (request.META.get("REMOTE_ADDR") or "")[:64]


def client_anon_id(request):
    """The browser's own funnel UUID, if it sent one.

    Blank is normal and must never be treated as a match: private-mode
    browsers throw on localStorage and `track.js` returns "" there, so a
    blank id is "we don't know", not "everyone who didn't say".
    """
    raw = (request.data.get("anon_id") if hasattr(request, "data") else None) \
        or request.query_params.get("anon_id", "")
    return str(raw or "").strip()[:64]


def _trial_ip_exempted(ip):
    """Check if this IP is exempt from per-IP trial rate limits."""
    import os
    exempted = os.environ.get("TRIAL_EXEMPT_IPS", "").strip()
    if not exempted or not ip:
        return False
    exempt_list = [i.strip() for i in exempted.split(",") if i.strip()]
    return ip in exempt_list


def trial_state(ip, anon_id=""):
    """(taken_today_globally, this_browser_is_done, this_address_is_over).

    Three numbers because there are three genuinely different "no"s and they
    need three different sentences. Telling somebody they have had their free
    take when what actually happened is that their phone carrier's shared
    address is busy is a false accusation on the one screen a stranger sees.

    A blank `anon_id` never matches anything — a browser that cannot reach
    localStorage has not identified itself, and counting all of them as one
    visitor would shut the door on every private-mode window at once.
    """
    from datetime import timedelta
    now = timezone.now()
    window = now - timedelta(hours=TRIAL_PER_IP_HOURS)
    today = TrialTake.objects.filter(created_at__gte=now - timedelta(hours=24)).count()

    if _trial_ip_exempted(ip):
        return today, False, False

    # SCORED takes only. An unscorable one cost them a performance and paid
    # them nothing, so it is not the take they came for — see TrialTake.scored.
    browser_done = bool(anon_id) and TrialTake.objects.filter(
        anon_id=anon_id, scored=True, created_at__gte=window
    ).count() >= TRIAL_PER_BROWSER
    ip_over = bool(ip) and TrialTake.objects.filter(
        ip=ip, created_at__gte=window
    ).count() >= TRIAL_PER_IP
    return today, browser_done, ip_over


class TrialCoachView(APIView):
    """GET what the trial offers and whether it's available; POST one take.

    `app_key` is bound per-route, exactly as SingZCoachView's is, so SingZ and
    RapZ both get a door without either owning it.
    """

    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]
    app_key = "singz"

    def get(self, request):
        profile = profile_for_app(self.app_key)
        today, mine, ip_over = trial_state(client_ip(request),
                                           client_anon_id(request))
        cap = trial_daily_cap()
        return Response({
            "app_key": self.app_key,
            "label": profile["label"],
            "configured": bool(_key()),
            # Free to them, and it costs them nothing they own — say so plainly
            # rather than letting them wonder what they're about to spend.
            "free": True,
            "available": bool(_key()) and not mine and not ip_over and today < cap,
            "already_used": mine,
            # A FOURTH "no", and the one that used to masquerade as the first.
            # The address is busy — a shared carrier address, an office, a
            # campus — and the person reading this has not used anything. It
            # gets its own flag so the screen can say so instead of accusing
            # them of spending a take they never had.
            "address_busy": ip_over,
            # Which "no" it is. `available: false` covers three completely
            # different situations — the visitor spent today's take, the
            # platform spent today's takes, or nobody set GEMINI_API_KEY — and
            # a client that cannot tell them apart has to guess, which is how
            # a screen ends up telling somebody the coach is down when their
            # own allowance is simply used up.
            "cap_reached": today >= cap,
            # RapZ has a style picker and this door never sent the list, so
            # the control did not render at all — the trial was quietly a less
            # capable coach than the member one, on the screen whose whole job
            # is showing strangers the product. Same shape as `ranges` above.
            "style_label": profile["style_label"],
            "styles": [{"key": k, "label": l} for k, l in profile["styles"]],
            "per_address": (f"one free take per browser every {TRIAL_PER_IP_HOURS} hours "
                            f"({TRIAL_PER_IP} per network address)"),
            "max_mb": TRIAL_MAX_MB,
            "claim_days": TRIAL_CLAIM_DAYS,
            # `scores_for`, not `profile["scores"]`: every take is scored
            # against the style or genre it was aimed at, so Style Match is
            # always in the set. Publishing the profile's five while the
            # response carries six is how a chip row ends up one short of
            # the answer.
            "scores": scores_for(self.app_key),
            "range_label": profile["range_label"],
            "ranges": [{"key": k, "label": l} for k, l in profile["ranges"]],
            "difficulties": DIFFICULTIES,
            # Published here too, or the trial recorder cannot render the
            # toggle and the door offers less than the product again — which
            # is the gap the style picker comment above is about.
            "rates_lyrics": rates_lyrics(self.app_key),
            "lyric_scores": LYRIC_SCORE if rates_lyrics(self.app_key) else {},
            # The mix toggle, published the same way and for the same reason:
            # the screen must not keep its own copy of which dimensions exist.
            "rates_mix": rates_mix(self.app_key),
            "mix_scores": MIX_SCORE if rates_mix(self.app_key) else {},
            "caveat": profile["caveat"],
        })

    def post(self, request):
        ip = client_ip(request)
        anon_id = client_anon_id(request)
        today, mine, ip_over = trial_state(ip, anon_id)
        if mine:
            return Response(
                {"detail": "You've had your free take for today. Make an account and the coach is yours whenever you want it.",
                 "already_used": True},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if ip_over:
            # Never "you've had yours" — they have not. This fires when the
            # ADDRESS is busy, which on a mobile carrier means somebody they
            # have never met is behind the same CGNAT. Blaming the visitor for
            # it is a lie, and an account genuinely is the fix, so say both.
            return Response(
                {"detail": "This network has used up today's free takes — that's the connection "
                           "you're on, not you. An account gets you the coach on any connection.",
                 "address_busy": True},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if today >= trial_daily_cap():
            return Response(
                {"detail": "Free takes are all spoken for today — they're limited so we can keep giving them away. Try tomorrow, or make an account.",
                 "retry_tomorrow": True},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        f = request.FILES.get("take")
        if not f:
            return Response({"detail": "Record or attach a take first."},
                            status=status.HTTP_400_BAD_REQUEST)
        content_type = (getattr(f, "content_type", "") or "").lower()
        if not (content_type.startswith("audio/") or content_type.startswith("video/")):
            return Response({"detail": "That isn't audio or video. Record a take, or attach an "
                                       "audio or video file."},
                            status=status.HTTP_400_BAD_REQUEST)
        if f.size > TRIAL_MAX_MB * 1024 * 1024:
            return Response({"detail": f"That take is too big for a free run — keep it under {TRIAL_MAX_MB}MB."},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        data = request.data
        payload, err = score_take(
            self.app_key, f, content_type,
            genre=data.get("genre"), target=data.get("range"),
            difficulty=data.get("difficulty"),
            # The other half of the same gap: even once the picker renders,
            # this door was not forwarding the answer. A trial that grades on
            # a different input than the product is the same lie as one that
            # grades on an easier rubric, which is why score_take is shared.
            style=data.get("style"),
            # And the same for the lyrics toggle, for the same reason the
            # comment above gives: a trial graded on different inputs than the
            # product is a lie about the product. It is the visitor's take —
            # if they wrote words and want them read, that is the take they
            # came to have scored.
            lyrics=str(data.get("rate_lyrics", "")).lower() in ("1", "true", "yes", "on"),
            # Same reason as lyrics above: the trial is the product, so a
            # visitor who wants the mix read gets the mix read.
            mix=str(data.get("rate_mix", "")).lower() in ("1", "true", "yes", "on"),
        )
        if err:
            # A take the coach couldn't read doesn't burn the visitor's one
            # free run — nothing is written, so they can try again.
            body, code = err
            return Response(body, status=code)

        # Every call we paid for is written down — the address ceiling and the
        # global cap both count these rows, and a model call that left no row
        # would be money spent off the books. `scored` is what decides whether
        # it also used up the visitor's own free take.
        take = TrialTake.objects.create(
            token=secrets.token_urlsafe(24), app_key=self.app_key, ip=ip,
            anon_id=anon_id, result=payload,
            scored=payload.get("score") is not None,
        )
        return Response({
            **payload,
            "trial": True,
            "cost_cents": 0,
            "claim_token": take.token,
            # Not a dead end: the take they just made opens inside the app once
            # they join, rather than vanishing with the tab.
            "open_in": f"{self.app_key}:coach",
            "claim_hint": f"Sign up within {TRIAL_CLAIM_DAYS} days and this take is saved to your account.",
        }, status=status.HTTP_201_CREATED)


class TrialTakeDetailView(APIView):
    """GET /api/trial/<token>/ — read a trial take back.

    Lets the client survive a reload before signup, and lets a freshly claimed
    take render inside the app afterwards.
    """

    permission_classes = [AllowAny]

    def get(self, request, token):
        take = TrialTake.objects.filter(token=str(token)[:64]).first()
        if not take:
            return Response({"detail": "That trial take has expired or never existed."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response({
            **(take.result or {}),
            "app_key": take.app_key,
            "trial": True,
            "claimed": bool(take.claimed_by_id),
            "open_in": f"{take.app_key}:coach",
            "created_at": take.created_at.isoformat(),
        })


class TrialPublicStatsView(APIView):
    """GET /api/economy/trial/public/stats/ — honest social proof for the door.

    This shipped querying `visitor_id`, which is not a field on FunnelEvent
    (it is `anon_id`), in four places — so every request was a FieldError and
    a 500, and it has never once answered. The client made it worse by asking
    for `/api/trial/public/stats/`, which is not where it is mounted, so the
    call 404'd before it could even reach the 500. Both ends broken, and
    invisible because the caller swallows the failure.

    What it served was the second problem, and the one worth more than the
    fix. It published the JOIN FUNNEL'S conversion rates to the very people in
    it — "Tried → Scored: 1 of 18". That is a measurement of how well OUR door
    works, not of whether the product is any good, and handing it to a
    stranger at the moment they are deciding whether to try argues against
    trying. The three rates belong in FunnelZ, where the owner reads them, and
    FunnelZ already has them.

    So this serves COUNTS of things that actually happened: takes scored, and
    how many instruments have a door. Both are true, neither is a percentage
    somebody can be on the wrong side of, and both go UP as the platform works
    rather than down.

    And it stays silent below `MIN_TO_SHOW`. "3 takes scored" is worse than no
    panel at all — the same rule the funnel's own `pct: None` follows, because
    an empty measurement and a bad one need opposite answers.
    """

    permission_classes = [AllowAny]

    # Below this, the honest thing to render is nothing.
    MIN_TO_SHOW = 25

    def get(self, request):
        from datetime import timedelta

        from .trialdoorz import door_keys

        try:
            days = max(1, min(365, int(request.query_params.get("days", "30"))))
        except (TypeError, ValueError):
            days = 30
        start = timezone.now() - timedelta(days=days)

        scored_window = TrialTake.objects.filter(created_at__gte=start).count()
        scored_total = TrialTake.objects.count()
        doors = len(door_keys())

        return Response({
            "days": days,
            # The client renders nothing when this is false. It is the
            # server's call because the server is the only end that knows the
            # number, and a threshold in a screen would be the second place it
            # lives.
            "enough": scored_total >= self.MIN_TO_SHOW,
            "takes_scored": scored_total,
            "takes_scored_window": scored_window,
            "doors": doors,
            # No rates, deliberately. See the docstring: a conversion
            # percentage is a fact about our funnel, not about the coach, and
            # the owner already reads those in FunnelZ.
        })


class PublicTiersView(APIView):
    """GET /api/economy/tiers/ — public membership tier options for trial door.

    Non-authenticated endpoint showing all public tiers (Free, Premium, StatZ)
    with their key features so visitors see membership options before creating
    an account. Includes founding StatZ pricing and seat availability.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        from .catalog import tier_ladder, TIER_FREE, TIER_PREMIUM, TIER_STATZ
        from .models import founding_status

        ladder = tier_ladder()
        founding = founding_status()

        tiers = []
        for tier_key in [TIER_FREE, TIER_PREMIUM, TIER_STATZ]:
            limits = ladder[tier_key]
            price = limits.pop("month_cents", 0)
            tier_data = {
                "key": tier_key,
                "label": {"free": "Free", "premium": "Premium", "statz": "StatZ"}.get(tier_key, tier_key),
                "price_cents": price,
                "upload_mb": limits["upload_mb"],
                "storage_mb": limits["storage_mb"],
                "char_limit": limits["char_limit"],
                "embeds_per_post": limits["embeds_per_post"],
            }

            # Add founding info for StatZ
            if tier_key == TIER_STATZ:
                tier_data["founding"] = {
                    "lifetime_cents": founding["price_cents"],
                    "year_cents": founding["year_cents"],
                    "month_cents": founding["month_cents"],
                    "remaining": founding["remaining"],
                    "sold_out": founding["sold_out"],
                }

            tiers.append(tier_data)

        return Response({"tiers": tiers})
