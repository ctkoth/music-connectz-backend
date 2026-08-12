"""GET /api/economy/occ/agent/ — the price, before it is spent.
POST — run the agent.

The GET is not decoration. An agent run is 20-80 model calls and the member
cannot possibly guess what that costs, so the ceiling, the engine and what the
run is allowed to touch all reach the button BEFORE it is pressed. Same shape as
`occ_run.py`, for the same reason.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import (
    AI_MODELS,
    OCC_MAX_PROMPT_CHARS,
    ai_model_for,
    ai_run_budget,
    occ_file_limits,
)
from .models import (
    OccFile,
    can_afford_ai,
    membership_for,
    occ_settings_for,
    profile_for,
    wallet_for,
)
from .occ_agent import MAX_TURNS, run_agent
from .occ_tools import TOOLS


def agent_status(user, project="main"):
    """Everything the Run button needs to state its own price and its reach."""
    tier = membership_for(user).tier
    model_key, spec = ai_model_for(profile_for(user).ai_model, tier)
    budget = ai_run_budget(tier)
    settings_row = occ_settings_for(user)
    # Writes need AutomationZ today. Phase 3 adds the SuggestionZ path, where a
    # proposed change waits for an explicit approval instead of being refused.
    writes_allowed = bool(settings_row.automation)
    return {
        "engine": model_key,
        "engine_name": spec["name"],
        "engine_emoji": spec["emoji"],
        "tier": tier,
        # The price, up front, as a ceiling rather than a guess.
        "max_cents": budget["max_cents"],
        "promptz": wallet_for(user).promptz,
        "affordable": can_afford_ai(user, budget["max_cents"]),
        "max_turns": MAX_TURNS,
        "writes_allowed": writes_allowed,
        "write_note": (
            "AutomationZ is on, so OCC changes files without asking. Every change "
            "is a TaskZ row you can undo."
            if writes_allowed else
            "OCC will read your project and say what it would change, but won't "
            "change anything. Turn on AutomationZ to let it write."),
        "tools": [{"name": t["name"], "changes_files": t["name"] in ("write", "edit")}
                  for t in TOOLS],
        "project": project,
        "files": OccFile.objects.filter(user=user, project=project).count(),
        "limits": occ_file_limits(tier),
        "prompt_chars": OCC_MAX_PROMPT_CHARS,
        "engines": [{"key": k, "name": v["name"], "emoji": v["emoji"]}
                    for k, v in AI_MODELS.items()],
        # Stated rather than discovered, same as the sandbox: a run that never
        # reached the model isn't charged.
        "billing_note": (
            f"You're charged for the tokens the run actually uses, up to "
            f"{budget['max_cents']} 🏷️. It stops at that ceiling rather than "
            "going past it, and a run that never reaches the model costs nothing."),
    }


class OccAgentView(APIView):
    """GET the price and the reach; POST runs the agent."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        project = str(request.query_params.get("project") or "main")
        return Response(agent_status(request.user, project))

    def post(self, request):
        data = request.data or {}
        prompt = str(data.get("prompt", "")).strip()
        if not prompt:
            return Response({"detail": "Tell OCC what to do."},
                            status=status.HTTP_400_BAD_REQUEST)
        if len(prompt) > OCC_MAX_PROMPT_CHARS:
            return Response(
                {"detail": f"That's {len(prompt):,} characters — keep the "
                           f"instruction under {OCC_MAX_PROMPT_CHARS:,}. The "
                           "project's files are read by OCC, not pasted in.",
                 "limits": occ_file_limits(membership_for(request.user).tier)},
                status=status.HTTP_400_BAD_REQUEST)

        st = agent_status(request.user, str(data.get("project") or "main"))
        if not st["affordable"]:
            # Checked before the model runs, so we never do the work and then
            # fail to bill for it.
            return Response(
                {"detail": f"An agent run can cost up to {st['max_cents']} 🏷️ and "
                           f"you have {st['promptz']}. Top up, or a tier up "
                           "carries a bigger allowance.",
                 "open_in": "modelz", **st},
                status=status.HTTP_402_PAYMENT_REQUIRED)

        out = run_agent(
            request.user, prompt,
            project=st["project"],
            model_key=data.get("engine"),
            writes_allowed=st["writes_allowed"],
        )
        if out.get("stopped") == "unavailable":
            return Response({**out, **st},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({**out, "write_note": st["write_note"]},
                        status=status.HTTP_201_CREATED)
