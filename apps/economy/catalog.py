"""Static economy config: SpecZ marketplace, per-tier limits, royalty cashout."""
from .models import TIER_FREE, TIER_PREMIUM, TIER_STATZ

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
    TIER_PREMIUM: {"char_limit": 1500, "upload_mb": 400, "storage_mb": 5120},
    TIER_STATZ: {"char_limit": 5000, "upload_mb": 4096, "storage_mb": 102400},
}


def limits_for(tier):
    return TIER_LIMITS.get(tier, TIER_LIMITS[TIER_FREE])


# Royalty cashout tax by plan. Weekly uses the account's developer-tax rate
# (Free 5% / Premium 3% / StatZ 2%); the others are flat.
CASHOUT_INSTANT = 0.15
CASHOUT_MONTHLY = 0.01
CASHOUT_QUARTERLY = 0.0


def cashout_rate(plan, dev_tax_rate):
    if plan == "instant":
        return CASHOUT_INSTANT
    if plan == "weekly":
        return dev_tax_rate
    if plan == "monthly":
        return CASHOUT_MONTHLY
    if plan == "quarterly":
        return CASHOUT_QUARTERLY
    return None
