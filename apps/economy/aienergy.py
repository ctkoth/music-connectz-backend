"""GET /api/economy/ai/energy/?engine= — the ⚡ a run costs this member, and their XP
bonus, so every AI button can state both before it is pressed."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AI_ENERGY_BASE, ai_energy_cost, membership_for, wallet_for


class AiEnergyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.skillz.models import XP_TIER_MULTIPLIER
        tier = membership_for(request.user).tier
        engine = request.query_params.get("engine") or None
        return Response({
            "engine": engine, "energy_cost": ai_energy_cost(request.user, engine, tier),
            "energy": wallet_for(request.user).energy or 0,
            "by_engine": {k: ai_energy_cost(request.user, k, tier) for k in AI_ENERGY_BASE},
            "xp_multiplier": XP_TIER_MULTIPLIER.get(tier, 1.0),
            "note": "Taken when the run succeeds, up to what you hold. A failed run costs nothing.",
        })
