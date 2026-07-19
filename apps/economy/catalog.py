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

# Per-tier limits. Storage in MB (Free 400MB / Premium 5GB / StatZ 100GB),
# uploads in MB (Free 40MB / Premium 400MB / StatZ 4GB), char limits for
# messages/posts/comments/AI prompts.
TIER_LIMITS = {
    TIER_FREE: {"char_limit": 400, "upload_mb": 40, "storage_mb": 400},
    TIER_PREMIUM: {"char_limit": 4000, "upload_mb": 400, "storage_mb": 5120},
    TIER_STATZ: {"char_limit": 40000, "upload_mb": 4096, "storage_mb": 102400},
    # Owner god-mode: effectively unlimited.
    TIER_DEBUG: {"char_limit": 1000000, "upload_mb": 1048576, "storage_mb": 10485760},
}


def limits_for(tier):
    return TIER_LIMITS.get(tier, TIER_LIMITS[TIER_FREE])


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
AI_MODEL_COSTS = {
    "corey-gpt": 2,
    "standard": 3,
    "technical": 3,
}


def ai_cost(model):
    return AI_MODEL_COSTS.get(model, AI_MODEL_COSTS["corey-gpt"])
