"""ModelZ — pick the engine your AI runs on, and see what it costs first.

Every model run in this app bills ONE Anthropic account: the platform's. A
member spending PromptZ or cash on an AI action is reimbursing that account.
That is the whole reason this screen exists — a member choosing a better engine
is choosing a bigger bill, and the cost/gain rule says they get told before they
choose, not after the charge lands.

So every row carries its price on its face:

    ⚡ Haiku    −2 🏷️ a message
    📖 Fable   −15 🏷️ a message

Two things are deliberately separate here, because tangling them is what went
wrong before:

* **Voice** is tone — Corey, standard, technical. Those are system prompts and
  they are free. A Free member gets the founder's voice like anyone else.
* **Model** is the engine. It has a real per-token price, so it is what costs
  and what the tier gates.

While they were one setting, Corey GPT — advertised as the *cheapest* voice at
1¢ — ran on Fable 5, the most expensive model there is. The app lost money
fastest on the option it told people was the value pick.

Locked rows are shown, not hidden. A Free member should be able to see that
Fable exists and what it would take to reach it; a locked row nobody can see is
not an upsell, it's a secret.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import (
    AI_MODELS,
    AI_MODEL_ORDER,
    ai_model_for,
    ai_models_for,
    default_ai_model,
    occ_limits,
)
from .models import (
    DAILY_PROMPT_MAX_CENTS,
    can_afford_ai,
    daily_prompt_covers,
    daily_prompt_state,
    membership_for,
    profile_for,
    wallet_for,
)
from .occ import CHAT_BUDGET_SECONDS
from .resources import PROMPTZ


def model_row(key, allowed, current, *, daily_left=None, user=None):
    spec = AI_MODELS[key]
    row = {
        "key": key,
        "name": spec["name"],
        "emoji": spec["emoji"],
        "blurb": spec["blurb"],
        # The price, on the row, before anybody picks it.
        "cost_cents": spec["cost_cents"],
        "cost_note": f"−{spec['cost_cents']} {PROMPTZ} a message",
        "tier": spec["tier"],
        # Same value, named for what a locked row needs to say: "needs premium".
        "required_tier": spec["tier"],
        "allowed": key in allowed,
        "current": key == current,
        # The model ID is deliberately not published. It is an implementation
        # detail that changes when a better model ships, and a client that
        # rendered it would go stale the day it did.
    }
    if daily_left is not None:
        # Whether a message on THIS engine would be covered by one of today's
        # free prompts — computed by the same two tests the chat endpoint
        # applies (`daily_prompt_covers` and prompts remaining), so the Send
        # button can say "Free today" before it is pressed and be right.
        row["free_today"] = bool(daily_prompt_covers(spec["cost_cents"]) and daily_left > 0)
    if user is not None:
        # Whether the wallet could pay for one message without a free prompt.
        row["affordable"] = can_afford_ai(user, spec["cost_cents"])
    return row


def model_state(user):
    tier = membership_for(user).tier
    p = profile_for(user)
    allowed = ai_models_for(tier)
    current, spec = ai_model_for(p.ai_model, tier)
    allowance, _, daily_left = daily_prompt_state(user)
    w = wallet_for(user)
    return {
        "tier": tier,
        "model": current,
        "cost_cents": spec["cost_cents"],
        # True while the member has never chosen — the client can say "picked
        # for you" rather than implying they set it.
        "chosen": bool(p.ai_model) and p.ai_model in allowed,
        "default": default_ai_model(tier),
        "models": [model_row(k, allowed, current, daily_left=daily_left, user=user)
                   for k in AI_MODEL_ORDER],
        # The free daily prompts and the wallet, so a message's price can be
        # stated BEFORE it is sent: "Free today — uses 1 of your N free prompts"
        # or "−5 🏷️". The answer used to arrive only in the reply, which is
        # the bill rather than the price.
        "daily_prompts": allowance,
        "daily_prompts_left": daily_left,
        "daily_prompt_max_cents": DAILY_PROMPT_MAX_CENTS,
        "promptz": w.promptz or 0,
        "money_cents": w.money_cents or 0,
        # How long a reply may take before the server gives up (and charges
        # nothing). The screen's own timeout is built from this, not guessed.
        "chat_budget_seconds": CHAT_BUDGET_SECONDS,
        # How big one message may be. Published here because it is the other
        # half of the prices above — a per-message price only means anything
        # alongside the size it was worked out for.
        "limits": occ_limits(),
        # Where a locked row leads. Nothing is a dead end.
        "open_in": "membershipz",
    }


class AiModelView(APIView):
    """GET /api/economy/ai/models/ — the ladder, what you're on, what it costs.

    PATCH { model: "opus" } — choose one. Choosing above your tier is refused
    with the tier that would reach it, rather than silently downgraded: a
    refusal you can read is better than a setting that didn't take.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(model_state(request.user))

    def patch(self, request):
        key = str((request.data or {}).get("model", "")).strip().lower()[:16]
        if key not in AI_MODELS:
            return Response(
                {"detail": "No such model.", "models": list(AI_MODEL_ORDER)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        tier = membership_for(request.user).tier
        if key not in ai_models_for(tier):
            spec = AI_MODELS[key]
            return Response(
                {"detail": f"{spec['emoji']} {spec['name']} needs {spec['tier']} — "
                           f"you're on {tier}.",
                 "required_tier": spec["tier"],
                 "cost_cents": spec["cost_cents"],
                 "open_in": "membershipz"},
                status=status.HTTP_403_FORBIDDEN,
            )
        p = profile_for(request.user)
        p.ai_model = key
        p.save(update_fields=["ai_model", "updated_at"])
        return Response(model_state(request.user))
