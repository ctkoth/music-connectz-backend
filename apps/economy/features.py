"""Which tier opens which feature, in one table.

Gates were being written inline — vocalcoach.py hardcodes its own StatZ check —
so every new gated feature meant another hand-rolled 403 with its own wording,
and the client had no way to know what it could offer without guessing.

The client reads this from /api/economy/features/ and renders locks from it, so
a gate and the UI that advertises it can never disagree.
"""
from .models import TIER_DEBUG, TIER_FREE, TIER_PREMIUM, TIER_STATZ

# Highest last — membership is a ladder, and "at least" needs an order.
TIER_ORDER = [TIER_FREE, TIER_PREMIUM, TIER_STATZ, TIER_DEBUG]

FEATURES = {
    # The four that thread through every app, MCZ and OCC alike.
    "logz": {
        "tier": TIER_PREMIUM, "label": "LogZ", "emoji": "🪵",
        "blurb": "What Music ConnectZ did — every move, by day, week, month or a range you pick.",
    },
    "tellz": {
        "tier": TIER_PREMIUM, "label": "TellZ", "emoji": "🗣️",
        "blurb": "What you input — every prompt and post you made, across any app or all of them.",
    },
    "suggestionz": {
        "tier": TIER_PREMIUM, "label": "SuggestionZ", "emoji": "💭",
        "blurb": "Proposes tasks and explains what, why and how — you decide whether it runs.",
    },
    "automationz": {
        "tier": TIER_STATZ, "label": "AutomationZ", "emoji": "🤖",
        "blurb": "Performs tasks without asking first and tells you in LogZ afterwards.",
    },
    # OCC.
    "gitz": {
        "tier": TIER_STATZ, "label": "GitZ", "emoji": "🐙",
        "blurb": "Git integration, synchronous with TaskZ — a commit is a task with a diff.",
    },
    "occ_cpp": {
        "tier": TIER_STATZ, "label": "C++ / Unreal", "emoji": "🎮",
        "blurb": "Build games in any language including C++. Unreal is StatZ-only.",
    },
    "occ_games": {
        "tier": TIER_PREMIUM, "label": "Game builds", "emoji": "🕹️",
        "blurb": "Build games in any language except C++.",
    },
    "pick_unlimited": {
        "tier": TIER_PREMIUM, "label": "PickConnectZ pins", "emoji": "📌",
        "blurb": "Pin as many features to the footer as you like. Free picks 2; AI fills the rest.",
    },
}


def rank(tier):
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return 0


def required_tier(key):
    return (FEATURES.get(key) or {}).get("tier", TIER_FREE)


def can_use(tier, key):
    """True when `tier` opens `key`. Unknown features are open — a typo in a
    key should not silently lock a member out of something they paid for."""
    if key not in FEATURES:
        return True
    return rank(tier) >= rank(required_tier(key))


def gate_detail(key):
    """The 403 body. One wording for every gate, naming the tier and the app,
    so a member is never told 'upgrade' without being told to what or why."""
    f = FEATURES.get(key) or {}
    tier = f.get("tier", TIER_FREE)
    label = f.get("label", key)
    return {
        "detail": f"{label} is a {tier.title()} feature. Upgrade in MembershipZ to use it.",
        "feature": key,
        "required_tier": tier,
        "blurb": f.get("blurb", ""),
    }


def feature_map(tier):
    """Everything, with whether THIS member has it — the client renders locks
    from this rather than keeping its own copy of the tier rules."""
    return [
        {"key": k, "label": v["label"], "emoji": v["emoji"], "blurb": v["blurb"],
         "required_tier": v["tier"], "unlocked": can_use(tier, k)}
        for k, v in FEATURES.items()
    ]
