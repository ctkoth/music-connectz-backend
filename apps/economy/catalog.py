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


# ---- Which engine runs the AI, who may pick it, and what it costs.
#
# The bill for every model run in this app lands on ONE Anthropic account — the
# platform's. A member spending their PromptZ is reimbursing that account, so a
# per-message price below the real cost is the platform paying people to use it.
#
# Two things were tangled together before this and are now separate:
#
#   * VOICE is tone. Corey / standard / technical are system prompts. Tone is
#     free — a Free member gets the founder's voice, same as anyone.
#   * MODEL is the engine. It has a real per-token price, so it is what gets
#     charged for and what tier gates.
#
# Keeping them tangled is how Corey GPT — the cheapest voice at 1c — ended up
# running on Fable 5, the most expensive model in the catalogue. The app was
# losing money fastest on the option it advertised as the value pick.
#
# `cost_cents` is the per-message minimum for a TYPICAL OCC turn: about 10,000
# input tokens (voice prompt + courses + eight turns of history) and about 800
# output. Published per-million rates, rounded up, because history grows:
#
#     Haiku 4.5   $1/$5    ->  1.0c + 0.4c  =  1.4c  ->  2c
#     Sonnet 5    $3/$15   ->  3.0c + 1.2c  =  4.2c  ->  5c
#     Opus 5      $5/$25   ->  5.0c + 2.0c  =  7.0c  ->  8c
#     Fable 5     $10/$50  -> 10.0c + 4.0c  = 14.0c  -> 15c
#
# These are minimums to cover a run, not a margin. If the model prices move,
# this table moves — it is the only place they are written down.
AI_MODELS = {
    "haiku": {
        "id": "claude-haiku-4-5", "name": "Haiku", "emoji": "⚡",
        "tier": TIER_FREE, "cost_cents": 2,
        "blurb": "Fast and cheap. Plenty for chat, translation and quick answers.",
    },
    "sonnet": {
        "id": "claude-sonnet-5", "name": "Sonnet", "emoji": "🎼",
        "tier": TIER_PREMIUM, "cost_cents": 5,
        "blurb": "The balanced one. Near-flagship work at a fraction of the price.",
    },
    "opus": {
        "id": "claude-opus-5", "name": "Opus", "emoji": "🎹",
        "tier": TIER_PREMIUM, "cost_cents": 8,
        "blurb": "Flagship. Long-horizon work, code, and anything that has to be right.",
    },
    "fable": {
        "id": "claude-fable-5", "name": "Fable", "emoji": "📖",
        "tier": TIER_STATZ, "cost_cents": 15,
        "blurb": "The most capable model there is. The hardest problems, at the highest price.",
    },
}

# Cheapest first — the order the picker renders, and the order a fallback walks.
AI_MODEL_ORDER = ("haiku", "sonnet", "opus", "fable")

# Which tiers can reach which rung. A tier gets its own rung and every rung
# below it, so upgrading only ever adds.
_TIER_RANK = {TIER_FREE: 0, TIER_PREMIUM: 1, TIER_STATZ: 2, TIER_DEBUG: 3}


def ai_models_for(tier):
    """The model keys this tier may pick, cheapest first."""
    rank = _TIER_RANK.get(tier, 0)
    return [k for k in AI_MODEL_ORDER
            if _TIER_RANK.get(AI_MODELS[k]["tier"], 0) <= rank]


def default_ai_model(tier):
    """What a member gets before they choose: the best rung their tier owns.

    The top rung rather than the bottom because the tier was paid for. A StatZ
    member who never opens the picker should not be quietly served Haiku.
    """
    allowed = ai_models_for(tier)
    return allowed[-1] if allowed else "haiku"


def ai_model_for(key, tier):
    """Resolve a member's stored choice against what their tier can reach.

    Returns (key, spec). A choice above the member's tier falls back rather than
    refusing — a lapsed StatZ member's saved 'fable' becomes their best current
    rung instead of an error on a screen they didn't come to fix.
    """
    allowed = ai_models_for(tier)
    if key not in allowed:
        key = default_ai_model(tier)
    return key, AI_MODELS[key]


def ai_model_cost(key, tier):
    """What one message on this member's model costs them, in cents."""
    return ai_model_for(key, tier)[1]["cost_cents"]
