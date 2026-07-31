"""Suggestion mode — one definition, used everywhere.

The rule you set: a suggestion says **What / Why / How**. All three, every time.

This lives in its own module because it had already drifted. OCC chat asked for
all three; OmviardZ asked for "what to do and why" and silently dropped the How;
and the OCC *agent* — the place suggestions matter most, since it's the one
actually changing your code — had no suggestion mode at all. Three copies, two
of them wrong. Now there is one copy.

Tier gate: SuggestionZ is StatZ, per the spec (`+SuggestionZ💭 … {requires statz
membership!}`). `may_suggest` is the single place that's decided.
"""
from .models import TIER_DEBUG, TIER_STATZ, membership_for

# The three parts, named so a caller can render its own UI copy from the same
# source rather than re-typing the rule.
PARTS = [
    {"key": "what", "label": "What", "blurb": "The one concrete next move."},
    {"key": "why", "label": "Why", "blurb": "What it gets you, or what it costs to skip."},
    {"key": "how", "label": "How", "blurb": "The step or two that does it."},
]

SUGGEST_STYLE = (
    "SUGGESTION MODE IS ON: always end your reply with a short '💡 Suggestion' — one "
    "concrete next move phrased as What / Why / How. WHAT to do, WHY it matters (what "
    "it gets them, or what it costs to skip), and HOW to do it in a step or two. "
    "All three, every time — a suggestion missing the How is a thought, not a "
    "suggestion. Keep it tight and actionable, never generic."
)

# Same rule, shortened for a phone bottom sheet. Still all three.
SUGGEST_STYLE_SHORT = (
    "End with one short '💡 Suggestion' — the single next move as What / Why / How: "
    "what to do, why it matters, and the one step that does it. All three, in two "
    "lines or less."
)

SUGGEST_TIERS = (TIER_STATZ, TIER_DEBUG)


def may_suggest(user):
    """Whether this member gets Suggestion mode. StatZ (and debug) only."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return membership_for(user).tier in SUGGEST_TIERS


def gate(user, wanted):
    """Resolve a requested suggestion flag against the member's tier.

    Returns (enabled, notice). A member below StatZ who asks for suggestions
    gets the reply without them plus a line saying why — rather than a hard
    error that loses the answer they actually asked for, or silence that looks
    like the toggle is broken.
    """
    if not wanted:
        return False, None
    if may_suggest(user):
        return True, None
    return False, ("Suggestions 💭 are a StatZ feature — this reply is without "
                   "them. Upgrade to have Corey close every answer with a "
                   "What / Why / How next step.")


def payload():
    """What the settings screen needs to describe the toggle honestly."""
    return {
        "key": "suggestions",
        "name": "SuggestionZ 💭",
        "blurb": "Corey ends every reply with one concrete next move.",
        "parts": PARTS,
        "requires_tier": TIER_STATZ,
    }
