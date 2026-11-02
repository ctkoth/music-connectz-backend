"""SocialZ: the accounts a member has connected, and what their followers pay.

`social_verify.py` has proven a linked account is the member's and read its real
follower count since it shipped, and `reach_median` has fed passive Energy for as
long as that has — but the only screen that ever drove it was in `src/mcz2/`,
which is not mounted. So the whole income path (verify → reach → ⚡ an hour) had
a backend and no way in. This is the read half that a screen needs; verifying
itself is still `POST /api/economy/social/verify/`.

**Everything on the screen is served, nothing retyped.** The divisors and floors
are the ones `energy_rate_per_hour` reads (`ENERGY_REACH_DIVISOR`,
`ENERGY_FLOOR_PER_HOUR`), the per-tier rates are that function called once per
tier against the member's OWN reach, and the sentences are built from those
constants. A client that worked "reach ÷ 10" out itself would be the second
place the rule lives, and the first to disagree after a change.

**What a connected sign-in does NOT do is said out loud.** An OAuth connection
(Google, Spotify, SoundCloud…) proves it is you when you sign in. It does not read
a follower count — only the verification below does, and only a VERIFIED account
counts toward reach. Saying otherwise would sell reach for a button that adds none.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    ENERGY_FLOOR_PER_HOUR, ENERGY_REACH_DIVISOR, TIER_FREE, TIER_PREMIUM, TIER_STATZ,
    SocialReview, energy_rate_per_hour, membership_for, profile_for, reach_median,
    social_sources,
)

TIER_LABELS = {TIER_FREE: "Free", TIER_PREMIUM: "Premium", TIER_STATZ: "StatZ"}


def _status(source, link, review):
    """verified | pending | rejected | unverified — one word per account.

    `pending` and `rejected` come from the review row, not from the link alone:
    a link flagged for a person to look at is waiting, and one the owner declined
    has to say so, or a member re-submits it forever wondering why it never counts.
    """
    if source["verified"]:
        return "verified"
    if link and link.get("review") == "pending":
        return "pending"
    if review is not None and review.status == SocialReview.STATUS_REJECTED:
        return "rejected"
    return "unverified"


def _rule_text(tier):
    divisor = ENERGY_REACH_DIVISOR.get(tier, ENERGY_REACH_DIVISOR[TIER_FREE])
    floor = ENERGY_FLOOR_PER_HOUR.get(tier, ENERGY_FLOOR_PER_HOUR[TIER_FREE])
    per = "your reach" if divisor == 1 else f"your reach ÷ {divisor}"
    return (f"On your tier you regenerate {per} ⚡ an hour, never fewer than {floor}. "
            "Reach is the median follower count across your VERIFIED accounts — "
            "Music ConnectZ followers included. A median, not a total, so one huge "
            "account can't carry it and a stranger's can't be borrowed.")


def payload(user):
    tier = membership_for(user).tier
    p = profile_for(user)
    sources = social_sources(user)
    # social_sources() is the Music ConnectZ row followed by one row per DICT
    # link of the profile, in order — pairing them here keeps the follower and
    # verified numbers its own and only adds what a screen needs to act on.
    dict_links = [l for l in (p.links or []) if isinstance(l, dict)]
    reviews = {}
    for r in SocialReview.objects.filter(user=user).order_by("created_at"):
        reviews[(r.url or "").strip().rstrip("/").lower()] = r

    rows = [{
        "kind": "mcz", "label": "Music ConnectZ", "url": "", "followers": sources[0]["followers"],
        "status": "verified", "counts": True,
        "note": "Your followers here always count — it is our own number.",
    }]
    for src, link in zip(sources[1:], dict_links):
        review = reviews.get((link.get("url") or "").strip().rstrip("/").lower())
        status = _status(src, link, review)
        rows.append({
            "kind": "link",
            "label": src["label"], "url": link.get("url", ""),
            "followers": src["followers"],
            "status": status, "counts": status == "verified",
            # The code is the member's own, shown back so they can paste it into
            # the bio they are verifying; a verified link no longer needs it.
            "code": None if status == "verified" else (link.get("code") or None),
            "verified_at": link.get("verified_at"),
            "verified_by": link.get("verified_by"),
            "note": (review.note if review is not None and status == "rejected" else "")
                    or (review.ai_reason if review is not None and status == "pending" else ""),
        })

    return {
        "tier": tier,
        "reach": reach_median(user),
        "energy_per_hour": energy_rate_per_hour(user),
        "floor": ENERGY_FLOOR_PER_HOUR.get(tier, ENERGY_FLOOR_PER_HOUR[TIER_FREE]),
        "divisor": ENERGY_REACH_DIVISOR.get(tier, ENERGY_REACH_DIVISOR[TIER_FREE]),
        "rule": _rule_text(tier),
        # What the same reach pays on each tier, from the function that pays it.
        "ladder": [{
            "tier": t, "label": TIER_LABELS[t],
            "divisor": ENERGY_REACH_DIVISOR[t], "floor": ENERGY_FLOOR_PER_HOUR[t],
            "per_hour": energy_rate_per_hour(user, tier=t),
            "yours": t == tier,
        } for t in (TIER_FREE, TIER_PREMIUM, TIER_STATZ)],
        "sources": rows,
        "counted": sum(1 for r in rows if r["counts"]),
        "oauth_note": ("Connecting a sign-in proves it's you when you log in. It doesn't read a "
                       "follower count — an account only counts toward reach once it is "
                       "verified below."),
        "cost": "Checking an account costs you nothing, and a check that fails charges nothing.",
        "how": [
            "Quick match: no code. We read the public page and see whether it's you. "
            "If we can't tell, a person looks at it — it doesn't count until it clears.",
            "Code in bio: we give you a short code, you paste it in that profile's bio, "
            "and it settles in a minute.",
        ],
    }


class SocialZView(APIView):
    """GET /api/economy/socialz/ — the screen's one read."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(payload(request.user))
