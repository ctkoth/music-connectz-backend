"""Buy a membership with SpinAZ.

From the spec: "Users can buy memberships with spinaz $1=100 spinaz."

Why it matters for conversion more than it looks: a large share of a music
audience has no card on file — under-18s, people outside card-friendly
countries, people who just won't put a card into a new platform. SpinAZ is
earned by using the product, so this turns engagement directly into revenue-
equivalent upgrades without ever asking for payment details.

It is also the only upgrade path that works when Stripe is misconfigured.
"""
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import PREMIUM_PLANS, STATZ_PLANS
from .models import (TIER_PREMIUM, TIER_STATZ, Transaction, membership_for,
                     wallet_for)
from .upgrade import spinaz_price, tier_rank

TIER_PLANS = {TIER_PREMIUM: PREMIUM_PLANS, TIER_STATZ: STATZ_PLANS}

# How long a SpinAZ-bought membership lasts. There is no Stripe subscription
# behind it, so nothing renews it — the member buys another when it runs out.
PLAN_DAYS = {"month": 30, "year": 365}


class MembershipSpinazView(APIView):
    """GET the SpinAZ prices; POST {tier, plan} to buy with SpinAZ."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        w = wallet_for(request.user)
        options = []
        for tier, plans in TIER_PLANS.items():
            for plan, cfg in plans.items():
                cost = spinaz_price(cfg["cents"])
                options.append({
                    "tier": tier, "plan": plan, "spinaz": cost,
                    "cents_equivalent": cfg["cents"],
                    "days": PLAN_DAYS[plan],
                    "affordable": (w.spinaz or 0) >= cost,
                })
        options.sort(key=lambda o: o["spinaz"])
        return Response({"spinaz": w.spinaz or 0, "options": options,
                         "rate": "100 SpinAZ = $1"})

    @transaction.atomic
    def post(self, request):
        d = request.data or {}
        tier = str(d.get("tier", "")).lower()
        plan = str(d.get("plan", "month")).lower()

        plans = TIER_PLANS.get(tier)
        if not plans:
            return Response({"detail": f"tier must be one of {sorted(TIER_PLANS)}"},
                            status=status.HTTP_400_BAD_REQUEST)
        cfg = plans.get(plan)
        if not cfg:
            return Response({"detail": f"plan must be one of {sorted(plans)}"},
                            status=status.HTTP_400_BAD_REQUEST)

        m = membership_for(request.user)
        if m.lifetime:
            return Response({"detail": "You already have lifetime access.",
                             "tier": m.tier}, status=status.HTTP_409_CONFLICT)
        # Buying a tier you already outrank would silently take SpinAZ for
        # nothing. Downgrading is not a purchase.
        if tier_rank(m.tier) > tier_rank(tier):
            return Response({"detail": f"You're already on {m.tier} — that's above {tier}.",
                             "tier": m.tier}, status=status.HTTP_409_CONFLICT)

        cost = spinaz_price(cfg["cents"])
        w = wallet_for(request.user)
        if (w.spinaz or 0) < cost:
            return Response({"detail": f"That costs {cost:,} SpinAZ and you have "
                                       f"{w.spinaz or 0:,}.",
                             "need_spinaz": cost, "spinaz": w.spinaz or 0,
                             "short_spinaz": cost - (w.spinaz or 0)},
                            status=status.HTTP_402_PAYMENT_REQUIRED)

        w.spinaz -= cost
        w.save(update_fields=["spinaz", "updated_at"])
        Transaction.objects.create(
            user=request.user, kind=Transaction.KIND_SPEND, amount_cents=0,
            dev_tax_cents=0, note=f"{tier.title()} ({plan}) — {cost:,} SpinAZ")

        m.tier = tier
        m.last_paid_at = timezone.now()
        m.last_payment_kind = f"{tier}_{plan}_spinaz"
        m.last_payment_ref = ""
        m.save(update_fields=["tier", "last_paid_at", "last_payment_kind",
                              "last_payment_ref", "updated_at"])

        return Response({
            "tier": m.tier, "plan": plan, "spent_spinaz": cost,
            "spinaz": w.spinaz,
            "days": PLAN_DAYS[plan],
            # Said plainly: nothing renews this, and a member who thinks it does
            # would be surprised on day 31.
            "note": "Bought with SpinAZ — this doesn't auto-renew. Buy again "
                    "when it runs out, or set up a card to renew automatically.",
        }, status=status.HTTP_201_CREATED)
