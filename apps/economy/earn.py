"""What pays right now — one server-side answer.

Written because the app said four things that weren't true at once. AdZ said
"watch and earn" while AdMob was unconfigured. OfferZ said the same. The
working notes said rating pays +1 ⚡ and no rating view awarded anything. The
profile published an hourly Energy rate that nothing ever credited. A member
looked at 0 ⚡ / 0 🍥 and had no way to find out why, because every screen that
could have told them was itself switched off with a "check back soon" and no
onward link.

So this is the list, from the constants themselves rather than from UI copy —
the same reason tier limits moved to catalog.py after "20 free prompts" drifted
into nine places. Every entry states its gain the way the cost/gain rule
requires, says whether it is available *right now*, and carries where to go do
it, so a switched-off earner is never a dead end.
"""
from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    AD_REWARD_DAILY_CAP_PER_USER,
    LINK_CLICK_REWARD_ENERGY,
    ONBOARD_REWARD_ENERGY,
    ONBOARD_REWARD_SPINAZ,
    RATING_REWARD_DAILY_CAP,
    RATING_REWARD_ENERGY,
    REFERRAL_REWARD_JOINEE_SPINAZ,
    REFERRAL_REWARD_REFERRER_SPINAZ,
    RESTRICTED_JOIN_REWARD_SPINAZ,
    SHARE_REWARD_ENERGY,
    Transaction,
    energy_rate_per_hour,
    profile_for,
)


def _way(key, label, gain, resource, *, tab, target="", available=True,
         reason="", note="", cap=""):
    return {
        "key": key,
        "label": label,
        "gain": gain,
        "resource": resource,     # spinaz | energy — the client renders 🍥 / ⚡
        "available": available,
        "reason": reason,         # why not, when unavailable
        "note": note,
        "cap": cap,
        # Where to actually do it. `goToSpot(tab, target)` lands on the control,
        # not just the tab — a link to an app you then have to search is barely
        # a link at all.
        "tab": tab,
        "target": target,
    }


def _raise_rate(user, rate):
    """The upgrade offer, priced in the thing being asked for: ⚡ per hour.

    "Upgrade for more Energy" is a slogan; "12 ⚡/hr → 24 ⚡/hr" is a number the
    member can check against the rate the app already shows them, and it is
    computed from their OWN reach and badges rather than a headline figure that
    would be someone else's. A tier that would not actually pay them more is
    left out — an offer whose gain is zero is a nag.
    """
    from .models import TIER_FREE, TIER_PREMIUM, TIER_STATZ, energy_rate_per_hour, membership_for

    ladder = [TIER_FREE, TIER_PREMIUM, TIER_STATZ]
    mine = membership_for(user).tier
    if mine not in ladder:          # debug/owner — nothing above them to sell
        return {"tier": mine, "per_hour": rate, "options": []}

    options = []
    for tier in ladder[ladder.index(mine) + 1:]:
        would = energy_rate_per_hour(user, tier=tier)
        if would > rate:
            options.append({
                "tier": tier,
                "per_hour": would,
                "gain_per_hour": would - rate,
                "tab": "membershipz",
                "target": "",
            })
    return {"tier": mine, "per_hour": rate, "options": options}


class EarnView(APIView):
    """GET /api/economy/earn/ — every way this member can earn, right now."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        admob_on = bool(getattr(settings, "ADMOB_APP_ID", "")
                        and getattr(settings, "ADMOB_REWARDED_UNIT_ID", ""))
        offerz_on = bool(getattr(settings, "OFFERZ_CALLBACK_SECRET", "")
                         or getattr(settings, "AYET_API_KEY", ""))
        onboarded = profile_for(request.user).onboarded
        rate = energy_rate_per_hour(request.user)

        ways = [
            _way("rating", "Rate a member, face or post", RATING_REWARD_ENERGY, "energy",
                 tab="social", target="social-rate",
                 cap=f"{RATING_REWARD_DAILY_CAP} a day",
                 note="Your first rating of each thing pays. Changing your mind is free."),
            _way("referral", "Refer someone", REFERRAL_REWARD_REFERRER_SPINAZ, "spinaz",
                 tab="profilez", target="referral-code",
                 note=f"They start with {REFERRAL_REWARD_JOINEE_SPINAZ} too."),
            _way("share", "Share another member's post", SHARE_REWARD_ENERGY, "energy",
                 tab="social", target="social-feed",
                 note="Once per post, after you've actually watched it."),
            _way("link", "Someone clicks your link", LINK_CLICK_REWARD_ENERGY, "energy",
                 tab="profilez", target="profile-links"),
            _way("restricted", "Someone joins your restricted post",
                 RESTRICTED_JOIN_REWARD_SPINAZ, "spinaz",
                 tab="social", target="social-compose"),
            # Always available now: ENERGY_FLOOR_PER_HOUR means the rate is
            # never 0, so this stopped being a locked row a new member reads as
            # "not for you" and became a number that grows when they verify.
            _way("passive", "Passive Energy, hourly", rate, "energy",
                 tab="profilez", target="profile-reach",
                 note="Paid by the hour, tier-scaled. Verify a social account "
                      "and your median reach raises it above the floor."),
            _way("onboard", "Finish OnboardZ", ONBOARD_REWARD_SPINAZ, "spinaz",
                 tab="onboardz", target="",
                 available=not onboarded,
                 reason="Already claimed." if onboarded else "",
                 note=f"Plus {ONBOARD_REWARD_ENERGY} Energy, once."),
            _way("adz", "Watch a rewarded ad", 1, "spinaz",
                 tab="adz", target="", available=admob_on,
                 reason="" if admob_on else "Rewarded ads aren't switched on yet.",
                 note=f"Typical reward. Each ad pays 1+ SpinAZ. Up to {AD_REWARD_DAILY_CAP_PER_USER} rewarded ads per day."),
            _way("offerz", "Complete an offer", 0, "spinaz",
                 tab="offerz", target="", available=offerz_on,
                 reason="" if offerz_on else "The offerwall isn't switched on yet."),
        ]

        # What they've actually banked, so the list isn't purely aspirational.
        earned = {}
        for res in (Transaction.RES_SPINAZ, Transaction.RES_ENERGY):
            rows = Transaction.objects.filter(user=request.user, resource=res, amount__gt=0)
            earned[res] = sum(rows.values_list("amount", flat=True))

        # What the 🍥 in that list is FOR. A screen that shows somebody five
        # ways to earn a currency and no door out of it is a read-only surface
        # wearing an earn screen's clothes — and until PromptZ could be bought
        # with SpinaZ there genuinely wasn't one.
        from .catalog import SPINAZ_PER_PROMPTZ

        return Response({
            "ways": ways,
            "available": [w for w in ways if w["available"]],
            "earned_total": earned,
            "energy_per_hour": rate,
            "raise_rate": _raise_rate(request.user, rate),
            "spend": [{
                "key": "promptz",
                "label": "Turn SpinaZ into PromptZ",
                "cost": {"resource": "spinaz", "amount": SPINAZ_PER_PROMPTZ},
                "gain": {"resource": "promptz", "amount": 1},
                "tab": "walletz", "target": "promptz-convert",
                "note": "AI credits, earned rather than bought. No card needed.",
            }],
        })
