"""One answer to "what does this AI action cost me, before I press it?"

`CLAUDE.md`'s first rule: a price discovered by paying it is not a price, it's
a bill. The Boss Take coach already answers it — `SingZCoachView.get` states the
cost, whether a free daily prompt covers it, and what it falls back to — but
every other AI surface charged server-side and told the member afterwards, in
`cost_cents` on the response. That is the bill.

This is the coach's answer, factored out, so the rest of the AI suite can give
the same one in the same words instead of three near-misses that drift.

The part worth being careful about is the free daily allowance. It does NOT
cover every AI action:

    charge_ai_usage(user, cost, count_daily=True)   # allowance applies
    charge_ai_usage(user, cost)                     # it does not

The coach passes `count_daily=True`, so "Free today" is true there. Image, video
and translate do not — image and video run models the allowance isn't priced
for, and translate bills per batch. Copying the coach's shape without that flag
would have every one of them announce a free run and then charge for it, which
is worse than saying nothing: the member checked.

So `uses_allowance` is required, not defaulted. `daily_remaining` is still
reported when it doesn't apply, because "you have 4 free prompts left, they
don't cover this one" is the answer to the question the member is actually
asking, and silence lets them assume the opposite.
"""
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


def ai_price(user, *, configured, uses_allowance, charged_on_failure,
             failure_note="", action="", model="standard", open_in="membershipz"):
    """What `user` pays for one run of this action, right now.

    `configured` — whether the backend can actually run it. An unconfigured
    action is not "free", it is unavailable, and the two must not read alike.
    `uses_allowance` — whether the charge passes `count_daily=True`. See above.
    `charged_on_failure` — whether a run that fails still costs. State it either
    way; `failure_note` says WHY, which is the half that lets a member trust it.
    """
    cost = ai_cost(model)
    allowance, _used, daily_left = daily_prompt_state(user)
    w = wallet_for(user)
    promptz = w.promptz or 0
    money_cents = w.money_cents or 0

    # A free daily prompt only covers this run if this run actually spends one.
    free_today = bool(uses_allowance and daily_left > 0 and cost)
    affordable = can_afford_ai(user, cost)

    if not cost:
        pays_from = "free"
    elif free_today:
        pays_from = "free_today"
    elif not affordable:
        pays_from = "short"
    elif promptz >= cost:
        pays_from = "promptz"
    elif promptz > 0:
        pays_from = "mixed"       # PromptZ first, then the rest from cash
    else:
        pays_from = "balance"

    out = {
        "action": action,
        # Can the member take this action right now — configured, and either a
        # free prompt or the balance to cover it. Not "is your tier allowed":
        # nothing here is tier-locked, and that was never the question.
        "allowed": bool(configured and (free_today or affordable)),
        "configured": configured,
        "cost_cents": cost,
        "free_today": free_today,
        # Reported even when the allowance doesn't apply, so the client can say
        # so plainly rather than leaving the member to guess it does.
        "uses_daily_allowance": bool(uses_allowance),
        "daily_remaining": daily_left,
        "daily_allowance": allowance,
        "tier": membership_for(user).tier,
        "promptz": promptz,
        "money_cents": money_cents,
        "pays_from": pays_from,
        "charged_on_failure": bool(charged_on_failure),
        "charged_on_failure_note": failure_note,
        "open_in": open_in,
    }
    # What a tier up buys HERE. Only when the allowance is what's being spent —
    # on an action it doesn't cover, the ladder buys nothing and printing it
    # would be an upsell for a benefit that doesn't apply.
    if uses_allowance:
        out["allowance_ladder"] = [
            {"tier": t, "daily": PROMPT_ALLOWANCE[t]}
            for t in (TIER_FREE, TIER_PREMIUM, TIER_STATZ)
        ]
    return out
