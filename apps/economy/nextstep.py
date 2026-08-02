"""Every refusal carries what to do next.

A member who hits a wall has exactly one question: *what now?* Answering it
with a price, an amount and a route converts. Answering it with
`{"detail": "insufficient balance"}` makes them close the app — and that was
the single biggest conversion hole in this codebase: seventeen paywalls with
no price, no tier and nowhere to go.

The rule is narrow, and it matters:

    Attach the next step to the REFUSAL. Never to the browse.

A link offered to somebody who is blocked is help. The same link offered to
somebody who is just looking is an upsell, and you only get to do that twice
before people stop reading anything the app says — including the times it
mattered.

`upgrade.payload` already builds the rich version for tier and balance walls.
This module is for the refusals that aren't about money: verification that
failed, a wallet on hold, an allowance that ran out. Same shape either way, so
a client renders one thing.
"""
from .upgrade import payload as upgrade_payload


def refusal(detail, *, action=None, label=None, why=None, **extra):
    """A refusal body with a way forward.

    `action` is the route that fixes it, `label` is the button, `why` is the
    plain reason. Anything else the caller knows goes in `extra` — an amount
    short, an allowance, a reset time.
    """
    body = {"detail": detail}
    if why:
        body["why"] = why
    if action:
        body["next"] = {"action": action, "label": label or "Fix this"}
    body.update(extra)
    return body


def not_enough(user, *, need_cents=0, need_spinaz=0, feature="",
               required_tier=None, detail=""):
    """A money wall. Price, shortfall, and every route out of it.

    Wraps `upgrade.payload`, which already knows about plans, trials, SpinAZ
    pricing and whether the member's SpinAZ would cover the gap. One builder,
    so a paywall in MerchZ says the same thing a paywall in VenueZ does.
    """
    body = upgrade_payload(user, feature, required_tier, need_cents, need_spinaz)
    if detail:
        body["detail"] = detail
    body.setdefault("detail", "Not enough balance for that.")
    body.setdefault("next", {"action": "/api/economy/checkout/stripe/",
                             "label": "Add funds"})
    return body


def wallet_on_hold(wallet):
    """A frozen wallet. Says why, says it isn't permanent, says who to ask.

    Reached when a card payment that funded the wallet was charged back. The
    member may have had nothing to do with it — a stolen card funds somebody
    else's account — so the tone is a hold, not an accusation.
    """
    return refusal(
        wallet.frozen_reason or "This wallet is on hold.",
        why="A card payment that funded this wallet was disputed.",
        action="/api/economy/support/", label="Sort this out",
        on_hold=True, since=wallet.frozen_at,
        can_still=["posting", "collabs", "messaging", "getting paid"],
    )


def out_of_prompts(user):
    """The AI allowance ran out. Says how many, when it resets, what more costs.

    "You're out of prompts" with no number and no reset time is a dead end
    dressed as an explanation.
    """
    from .models import daily_prompt_state

    allowance, used, remaining = daily_prompt_state(user)
    return refusal(
        f"You've used today's {allowance} free AI prompts.",
        why="The free allowance resets at midnight UTC.",
        action="/api/economy/checkout/stripe/", label="Buy PromptZ",
        allowance=allowance, used=used, remaining=remaining,
        upgrade="/api/economy/premium/checkout/",
        note=("Premium gets 10 a day, StatZ 20 — or buy PromptZ and they don't "
              "expire."),
    )


def verification_needed(profile, detail=""):
    """Identity verification failed, stalled, or was never started.

    The old behaviour was silence: a member whose document was rejected saw a
    screen identical to never having started, and had no way to try again.
    """
    # "unstarted" is the model's default — not "" and not "none". Reading it
    # wrong is how a member who never began gets told their document failed.
    status_ = getattr(profile, "verification_status", "") or "unstarted"
    never_started = "You haven't verified yet."
    reasons = {
        "failed": "The document didn't pass. You can try again with a clearer photo.",
        "requires_input": "Verification was started but never finished.",
        "processing": "Still checking — this usually takes a minute.",
        "unstarted": never_started,
        "none": never_started,
    }
    return refusal(
        detail or "This needs a verified 18+ account.",
        why=reasons.get(status_, reasons["none"]),
        action="/api/economy/identity/start/", label="Verify now",
        verification_status=status_,
        reason=getattr(profile, "verification_reason", "") or None,
        attempts=getattr(profile, "verification_attempts", 0),
        # Telling somebody to retry mid-check makes them do it twice.
        retryable=status_ != "processing",
    )
