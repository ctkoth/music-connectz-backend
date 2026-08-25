"""The price of an AI action, before the member commits to paying it.

`SingZCoachView.get` proved the shape: a GET on the same route that answers
what THIS member pays for THIS action right now — whether a free daily prompt
covers it, how many are left, what it falls back to, and whether a failed
attempt is billed. That was the only AI surface in the app with one. Every
other AI action — OCC chat, TranslateZ, the Gemini image and video endpoints —
charged server-side and reported `cost_cents` in the RESPONSE, which is a bill
rather than a price (see CLAUDE.md, the cost/gain paradigm).

This is that answer, in one place, so the four surfaces can't drift into four
different ideas of what a prompt costs. The coach keeps its own `get` because
it also serves the instrument's scoring profile and this member's upload cap;
what it shares with these is the money, and the keys below are named to match
it exactly so a client can read either one with the same code.
"""
import os

from .catalog import ai_cost
from .models import (
    PROMPT_ALLOWANCE,
    TIER_FREE,
    TIER_PREMIUM,
    TIER_STATZ,
    can_afford_ai,
    daily_prompt_state,
    membership_for,
    wallet_for,
)

# The same ladder the coach serves, built once. Order is the upgrade path, not
# dict order, so a client can render it straight down the screen.
ALLOWANCE_LADDER = [
    {"tier": t, "daily": PROMPT_ALLOWANCE[t]}
    for t in (TIER_FREE, TIER_PREMIUM, TIER_STATZ)
]


def ai_price(user, *, cost_cents=None, model=None, configured=True,
             daily_covers=True, charged_on_failure=False, **extra):
    """The pre-flight price block for one AI action.

    `cost_cents` wins when given (OCC prices per engine); otherwise the action
    is priced at the "standard" AI minimum, which is what TranslateZ and the
    Gemini surfaces charge.

    `configured` is the caller's own key check — an unconfigured backend can't
    run the action at any price, so it can't be "allowed" either.

    `daily_covers` must match the `count_daily` the caller passes when it
    bills. Image and video run models the free allowance isn't priced for and
    bill with `count_daily=False`, so quoting a free prompt there would be the
    same lie in the other direction: a price the member doesn't get.
    """
    cost = int(cost_cents if cost_cents is not None else ai_cost("standard"))
    allowance, _, daily_left = daily_prompt_state(user)
    free_today = bool(daily_covers) and cost > 0 and daily_left > 0
    w = wallet_for(user)
    return {
        # CAN YOU DO THIS RIGHT NOW — configured, and either a free prompt this
        # action can actually use or the balance to cover it. Not "are you the
        # right tier": nothing here is tier-locked, the tier only sets how many
        # prompts come free per day.
        "allowed": bool(configured) and (free_today or can_afford_ai(user, cost)),
        "configured": bool(configured),
        "cost_cents": cost,
        # A free daily prompt covers the whole run before any paid balance —
        # where it applies at all. `daily_covers` says whether it does here.
        "free_today": free_today,
        "daily_covers": bool(daily_covers),
        "daily_remaining": daily_left,
        "daily_allowance": allowance,
        "tier": membership_for(user).tier,
        # What more would buy: frequency, not access.
        "allowance_ladder": ALLOWANCE_LADDER,
        "open_in": "membershipz",
        "promptz": w.promptz or 0,
        "money_cents": w.money_cents or 0,
        # Whether a failed attempt is billed. Every caller here bills only
        # after a usable result comes back, so this is False — but it is said
        # rather than assumed, because "usually not" is not something a member
        # can act on.
        "charged_on_failure": bool(charged_on_failure),
        **({"model": model} if model else {}),
        **extra,
    }


def anthropic_configured():
    """Whether the Anthropic-backed surfaces (OCC chat, TranslateZ) can run.

    Both 503 on `ImportError` and would then fail inside the SDK with no key at
    all, so "configured" is both halves: the package installed AND a key in the
    environment. Only the pre-flight price asks this — the POST paths keep
    their own guards, because a key that disappears between the quote and the
    press must still 503 rather than charge.
    """
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
