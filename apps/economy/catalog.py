"""Static economy config: SpecZ marketplace, per-tier limits, royalty cashout."""
from .models import TIER_FREE, TIER_PREMIUM, TIER_STATZ, TIER_DEBUG

# SpecZ marketplace — StatZ-only purchasable metadata/UGC. Prices in cents.
SPECZ_CATALOG = {
    "demographics": {"name": "Audience Demographics", "price_cents": 999},
    "engagement": {"name": "Engagement Heatmap", "price_cents": 799},
    "genre-intel": {"name": "Genre Intelligence", "price_cents": 699},
    "collab-score": {"name": "Collab Compatibility", "price_cents": 499},
    "ugc-covers": {"name": "UGC: Cover Art Pack", "price_cents": 1299},
    "trending": {"name": "Trending Metadata Report", "price_cents": 899},
}

# A cap high enough that no human writes past it, while staying a plain int —
# so every `len(x) > cap` and `x[:cap]` in the codebase keeps working, and it
# still serializes to JSON. Clients should render `char_limit_unlimited` rather
# than printing this number.
UNLIMITED_CHARS = 10 ** 9

# Per-tier limits. Storage in MB (Free 400MB / Premium 5GB / StatZ 100GB),
# uploads in MB (Free 40MB / Premium 400MB / StatZ 4GB), char limits for
# messages/posts/comments/AI prompts.
TIER_LIMITS = {
    TIER_FREE: {"char_limit": 400, "upload_mb": 40, "storage_mb": 400},
    TIER_PREMIUM: {"char_limit": 1500, "upload_mb": 400, "storage_mb": 5120},
    # StatZ writes without a character cap — the client already advertised this
    # ("StatZ char limit: Unlimited") while the server was still cutting at
    # 5000, so a StatZ member was told one thing and refused another.
    TIER_STATZ: {"char_limit": UNLIMITED_CHARS, "upload_mb": 4096, "storage_mb": 102400},
    # Owner god-mode: effectively unlimited.
    TIER_DEBUG: {"char_limit": UNLIMITED_CHARS, "upload_mb": 1048576, "storage_mb": 10485760},
}


def limits_for(tier):
    return TIER_LIMITS.get(tier, TIER_LIMITS[TIER_FREE])


def chars_unlimited(tier):
    """True when this tier writes without a character cap."""
    return limits_for(tier)["char_limit"] >= UNLIMITED_CHARS


def over_char_limit(text, tier):
    """The cap `text` broke for this tier, or None if it fits.

    Every member-authored text field should run through this rather than
    hardcoding a number — a literal cap silently cuts a Premium member's 1,500
    characters and refuses a StatZ member the unlimited writing they paid for.
    """
    cap = limits_for(tier)["char_limit"]
    return None if len(text or "") <= cap else cap


# How long after posting a message/comment/post/rating you can still edit it, by
# tier: Free 4 min, Premium 40 min, StatZ 4 hours. (Owner/debug: no limit.)
EDIT_WINDOW_SECONDS = {
    TIER_FREE: 4 * 60,
    TIER_PREMIUM: 40 * 60,
    TIER_STATZ: 4 * 3600,
    TIER_DEBUG: 10 ** 9,
}


def edit_window_for(tier):
    return EDIT_WINDOW_SECONDS.get(tier, EDIT_WINDOW_SECONDS[TIER_FREE])


# Royalty cashout tax by plan. Weekly is its own per-tier schedule
# (Free 10% / Premium 5% / StatZ 3%) — matches the StatZ developer-tax rate.
# The others are flat.
CASHOUT_INSTANT = 0.15
CASHOUT_MONTHLY = 0.01
CASHOUT_QUARTERLY = 0.0
CASHOUT_WEEKLY = {TIER_FREE: 0.10, TIER_PREMIUM: 0.05, TIER_STATZ: 0.03, TIER_DEBUG: 0.0}


def cashout_rate(plan, tier):
    if plan == "instant":
        return CASHOUT_INSTANT
    if plan == "weekly":
        return CASHOUT_WEEKLY.get(tier, CASHOUT_WEEKLY[TIER_FREE])
    if plan == "monthly":
        return CASHOUT_MONTHLY
    if plan == "quarterly":
        return CASHOUT_QUARTERLY
    return None


# AI model per-message cost in cents — the *minimum* to cover the model run
# (pass-through, no markup). Corey GPT is priced a touch under the cheapest other
# voice so it's always the value option; it's tuned on member input + the built-in
# curricula so it costs the least to serve.
# Per-message minimum to cover the model (pass-through, no markup). Corey GPT is
# deliberately the cheapest voice.
AI_MODEL_COSTS = {
    "corey-gpt": 1,
    "standard": 3,
    "technical": 3,
}


# ---- Subscription pricing.
#
# Two rules hold the ladder together, and both are load-bearing:
#
#   1. Annual is four months free (33% off) at EVERY tier. One discount to
#      explain, and the bigger commitment never gets the smaller reward.
#   2. StatZ is 2.5x Premium. The gap has to be wide enough that Premium is a
#      real choice — if StatZ costs a couple of dollars more and buys unlimited
#      characters, the whole AI layer, CallZ and SpecZ, nobody sane picks the
#      middle tier and it stops earning its place on the page.
#
# Everything below is derived, not typed twice, so the two rules can't drift.

# Premium — the mid subscription (lower fees, 2x energy, 5 daily prompts).
PREMIUM_MONTH_CENTS = 600                            # $6/mo
PREMIUM_YEAR_CENTS = PREMIUM_MONTH_CENTS * 8         # $48/yr — four months free
PREMIUM_PLANS = {
    "year": {"mode": "subscription", "cents": PREMIUM_YEAR_CENTS, "interval": "year", "kind": "premium_sub"},
    "month": {"mode": "subscription", "cents": PREMIUM_MONTH_CENTS, "interval": "month", "kind": "premium_sub"},
}

# StatZ — the top subscription (no character limit, the AI layer, CallZ, SpecZ).
STATZ_MONTH_CENTS = 1500                             # $15/mo
STATZ_YEAR_CENTS = STATZ_MONTH_CENTS * 8             # $120/yr — four months free
LIFETIME_PRICE_CENTS = 30000                         # $300 one-time, StatZ forever
STATZ_PLANS = {
    "lifetime": {"mode": "payment", "cents": LIFETIME_PRICE_CENTS, "interval": None, "kind": "lifetime"},
    "year": {"mode": "subscription", "cents": STATZ_YEAR_CENTS, "interval": "year", "kind": "statz_sub"},
    "month": {"mode": "subscription", "cents": STATZ_MONTH_CENTS, "interval": "month", "kind": "statz_sub"},
}

# Founding StatZ offer: the first 50 members get StatZ at 50% off — as a
# one-time lifetime seat, or grandfathered founding rates by year / month.
# Derived from the StatZ prices above so the discount is always genuinely half.
FOUNDING_TIER = TIER_STATZ
FOUNDING_LIMIT = 50
FOUNDING_DISCOUNT = 0.50              # first 50 pay half
_half = lambda cents: int(cents * (1 - FOUNDING_DISCOUNT))
FOUNDING_PRICE_CENTS = _half(LIFETIME_PRICE_CENTS)   # $150 lifetime
FOUNDING_YEAR_CENTS = _half(STATZ_YEAR_CENTS)        # $60/yr
FOUNDING_MONTH_CENTS = _half(STATZ_MONTH_CENTS)      # $7.50/mo
# Plan -> (Stripe mode, unit amount cents, recurring interval or None)
FOUNDING_PLANS = {
    "lifetime": {"mode": "payment", "cents": FOUNDING_PRICE_CENTS, "interval": None, "kind": "lifetime"},
    "year": {"mode": "subscription", "cents": FOUNDING_YEAR_CENTS, "interval": "year", "kind": "founding_sub"},
    "month": {"mode": "subscription", "cents": FOUNDING_MONTH_CENTS, "interval": "month", "kind": "founding_sub"},
}

# The founding discount must never price the top tier below the middle one.
# At Premium $10/mo this assertion fails: founding StatZ is $7.50, so the first
# 50 members would pay less for more. It is here so that can't ship unnoticed.
assert FOUNDING_MONTH_CENTS > PREMIUM_MONTH_CENTS, (
    f"Founding StatZ (${FOUNDING_MONTH_CENTS / 100:.2f}/mo) must cost more than "
    f"Premium (${PREMIUM_MONTH_CENTS / 100:.2f}/mo) — the ladder is inverted.")


def ai_cost(model):
    return AI_MODEL_COSTS.get(model, AI_MODEL_COSTS["corey-gpt"])
