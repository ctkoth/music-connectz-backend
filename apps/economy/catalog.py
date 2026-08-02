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


# Founding StatZ offer: first 50 members get StatZ at 50% off — as a one-time
# lifetime seat, or grandfathered founding rates by year / month.
FOUNDING_TIER = TIER_STATZ
FOUNDING_LIMIT = 50
FOUNDING_DISCOUNT = 0.50              # first 50 pay half
LIFETIME_PRICE_CENTS = 30000          # $300 full lifetime StatZ
FOUNDING_PRICE_CENTS = int(LIFETIME_PRICE_CENTS * (1 - FOUNDING_DISCOUNT))  # $150 lifetime
FOUNDING_YEAR_CENTS = 6000            # $60/yr founding StatZ (50% off full $120/yr)
FOUNDING_MONTH_CENTS = 750            # $7.50/mo founding StatZ (50% off full $15/mo)
# Plan -> (Stripe mode, unit amount cents, recurring interval or None)
FOUNDING_PLANS = {
    "lifetime": {"mode": "payment", "cents": FOUNDING_PRICE_CENTS, "interval": None, "kind": "lifetime"},
    "year": {"mode": "subscription", "cents": FOUNDING_YEAR_CENTS, "interval": "year", "kind": "founding_sub"},
    "month": {"mode": "subscription", "cents": FOUNDING_MONTH_CENTS, "interval": "month", "kind": "founding_sub"},
}

# Premium tier — the mid subscription (lower fees, 2x energy, 5 daily prompts).
#
# $10/mo, not the $6 this used to say. The founding block above is the proof,
# not the spec: it computes its 50% discount from a "full $15/mo" and "full
# $120/yr" StatZ. StatZ costs $5/mo and $40/yr ON TOP of Premium, so those
# full prices are only reachable when Premium is $10/mo and $80/yr. At $6 the
# stack came to $11/mo, and the founding discount was quietly being taken off
# a price nothing else in the codebase charged.
#
# Raising this later is much harder than launching at it — every subscriber at
# the low price is either grandfathered or feels the rise as a betrayal. The
# discount for early members already exists as the founding offer, which is
# time-limited by design and doesn't anchor the list price.
PREMIUM_MONTH_CENTS = 1000            # $10/mo   -> $15/mo with StatZ
PREMIUM_YEAR_CENTS = 8000             # $80/yr   -> $120/yr with StatZ
PREMIUM_PLANS = {
    "year": {"mode": "subscription", "cents": PREMIUM_YEAR_CENTS, "interval": "year", "kind": "premium_sub"},
    "month": {"mode": "subscription", "cents": PREMIUM_MONTH_CENTS, "interval": "month", "kind": "premium_sub"},
}

# StatZ — the top tier — had NO purchase path at all until now. Everything gated
# to it (the AI coach without spending a prompt, other members' routines, CallZ,
# automations, SuggestionZ, gym locations) was unreachable by paying money.
# Priced per the spec: $5/mo or $40/yr on top of Premium.
STATZ_MONTH_CENTS = 500
STATZ_YEAR_CENTS = 4000
STATZ_PLANS = {
    "year": {"mode": "subscription", "cents": STATZ_YEAR_CENTS, "interval": "year", "kind": "statz_sub"},
    "month": {"mode": "subscription", "cents": STATZ_MONTH_CENTS, "interval": "month", "kind": "statz_sub"},
}


def ai_cost(model):
    return AI_MODEL_COSTS.get(model, AI_MODEL_COSTS["corey-gpt"])
