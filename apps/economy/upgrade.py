"""One upgrade payload, used by every paywall.

A 402 is the highest-intent moment in the whole product: the member is trying to
do the thing, right now, and has been told no. Before this, sixteen of the
seventeen paywalls answered `{"detail": "insufficient balance"}` — no price, no
tier, no button. A wall instead of a door, at the exact moment somebody had
already decided they wanted it.

`payload()` answers four things every time: what you hit, what unlocks it, what
that costs, and whether SpinAZ can cover it instead of a card. The copy lives
here rather than in each caller, so seventeen paywalls can't word the offer
seventeen ways.
"""
from .catalog import (PREMIUM_MONTH_CENTS, PREMIUM_YEAR_CENTS, STATZ_MONTH_CENTS,
                      STATZ_YEAR_CENTS)
from .models import (TIER_DEBUG, TIER_FREE, TIER_PREMIUM, TIER_STATZ,
                     membership_for, wallet_for)

# $1 = 100 SpinAZ, and $1 = 100 cents, so one SpinAZ is one cent. Kept as a
# named constant anyway — if the rate ever moves, it moves in one place.
SPINAZ_PER_CENT = 1

TIER_ORDER = [TIER_FREE, TIER_PREMIUM, TIER_STATZ, TIER_DEBUG]

TIER_LABELS = {
    TIER_FREE: "Free 🤗",
    TIER_PREMIUM: "Premium 🥇",
    TIER_STATZ: "StatZ 📈",
    TIER_DEBUG: "Debug 🛠️",
}

PLAN_CENTS = {
    TIER_PREMIUM: {"month": PREMIUM_MONTH_CENTS, "year": PREMIUM_YEAR_CENTS},
    TIER_STATZ: {"month": STATZ_MONTH_CENTS, "year": STATZ_YEAR_CENTS},
}


def tier_rank(tier):
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return 0


def spinaz_price(cents):
    return int(cents) * SPINAZ_PER_CENT


def plans_for(tier):
    """The ways to buy a tier, cheapest-per-month first is NOT the order —
    monthly first, because that's the lower-commitment yes."""
    prices = PLAN_CENTS.get(tier)
    if not prices:
        return []
    out = []
    for plan in ("month", "year"):
        cents = prices[plan]
        row = {
            "plan": plan,
            "cents": cents,
            "price": f"${cents / 100:.2f}",
            "spinaz": spinaz_price(cents),
        }
        if plan == "year":
            monthly = prices["month"] * 12
            if monthly > cents:
                saved = monthly - cents
                row["saves_cents"] = saved
                row["saves"] = f"${saved / 100:.2f} a year"
        out.append(row)
    return out


def payload(user, feature="", required_tier=None, need_cents=0, need_spinaz=0):
    """Everything a paywall screen needs to be a door instead of a wall.

    `required_tier` for a tier gate; `need_cents` / `need_spinaz` for a balance
    shortfall. Both may apply — a StatZ feature you also can't afford.
    """
    m = membership_for(user)
    w = wallet_for(user)
    current = m.tier

    out = {
        "feature": feature or None,
        "current_tier": current,
        "current_tier_label": TIER_LABELS.get(current, current),
        "balance_cents": w.money_cents or 0,
        "spinaz": w.spinaz or 0,
    }

    if need_cents:
        short = max(0, int(need_cents) - (w.money_cents or 0))
        out["need_cents"] = int(need_cents)
        out["short_cents"] = short
        # SpinAZ is the path for somebody with no card on file, which on a music
        # platform is a large share of the audience. Saying so at the moment
        # they're blocked is worth more than a Settings page they never open.
        out["spinaz_would_cover"] = (w.spinaz or 0) >= spinaz_price(short or need_cents)

    if need_spinaz:
        out["need_spinaz"] = int(need_spinaz)
        out["short_spinaz"] = max(0, int(need_spinaz) - (w.spinaz or 0))

    if required_tier and tier_rank(current) < tier_rank(required_tier):
        out["required_tier"] = required_tier
        out["required_tier_label"] = TIER_LABELS.get(required_tier, required_tier)
        out["plans"] = plans_for(required_tier)
        out["checkout"] = f"/api/economy/{required_tier}/checkout/"
        out["spinaz_checkout"] = "/api/economy/membership/spinaz/"
        out["headline"] = f"{feature or 'That'} needs {TIER_LABELS.get(required_tier, required_tier)}"
        cheapest = min((p["cents"] for p in out["plans"]), default=0)
        if cheapest:
            out["detail"] = (f"From ${cheapest / 100:.2f} — or "
                             f"{spinaz_price(cheapest):,} SpinAZ if you'd rather not "
                             f"use a card.")
    elif need_cents or need_spinaz:
        out["headline"] = "Not enough balance for that"
        out["detail"] = "Add funds, or spend SpinAZ instead."
        out["checkout"] = "/api/economy/checkout/stripe/"

    return out


def response(user, feature="", required_tier=None, need_cents=0, need_spinaz=0,
             detail=""):
    """The body for a 402. `detail` overrides the generated line when a caller
    has something more specific to say."""
    body = payload(user, feature, required_tier, need_cents, need_spinaz)
    if detail:
        body["detail"] = detail
    else:
        body["detail"] = body.get("detail") or "That needs an upgrade."
    return body
