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
from .models import membership_for, profile_for


def model_row(key, allowed, current):
    spec = AI_MODELS[key]
    return {
        "key": key,
        "name": spec["name"],
        "emoji": spec["emoji"],
        "blurb": spec["blurb"],
        # The price, on the row, before anybody picks it.
        "cost_cents": spec["cost_cents"],
        "cost_note": f"−{spec['cost_cents']} 🏷️ a message",
        "tier": spec["tier"],
        "allowed": key in allowed,
        "current": key == current,
        # The model ID is deliberately not published. It is an implementation
        # detail that changes when a better model ships, and a client that
        # rendered it would go stale the day it did.
    }


def model_state(user):
    tier = membership_for(user).tier
    p = profile_for(user)
    allowed = ai_models_for(tier)
    current, spec = ai_model_for(p.ai_model, tier)
    return {
        "tier": tier,
        "model": current,
        "cost_cents": spec["cost_cents"],
        # True while the member has never chosen — the client can say "picked
        # for you" rather than implying they set it.
        "chosen": bool(p.ai_model) and p.ai_model in allowed,
        "default": default_ai_model(tier),
        "models": [model_row(k, allowed, current) for k in AI_MODEL_ORDER],
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
