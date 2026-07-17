from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    DEV_TAX,
    TIER_CHOICES,
    Transaction,
    membership_for,
    split_cents,
    wallet_for,
)
from .serializers import TransactionSerializer, WalletSerializer

User = get_user_model()
VALID_TIERS = {t[0] for t in TIER_CHOICES}


class StatsView(APIView):
    """Powers the frontend CommunityBar + tier gating: /api/auth/stats/."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        w = wallet_for(request.user)
        m = membership_for(request.user)
        return Response(
            {
                "total_members": User.objects.count(),
                "online_now": 1,  # last-seen presence tracking is a later addition
                "online_members": [request.user.username],
                "my_tier": m.tier,
                "my_money": w.money,
                "my_energy": w.energy,
                "my_spinaz": w.spinaz,
                "dev_tax_rate": m.dev_tax_rate,
            }
        )


class WalletView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        w = wallet_for(request.user)
        recent = request.user.transactions.all()[:50]
        return Response({"wallet": WalletSerializer(w).data, "transactions": TransactionSerializer(recent, many=True).data})


class AddFundsView(APIView):
    """Add funds — developer tax enforced server-side; net credited to wallet."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            amount_cents = int(request.data.get("amount_cents"))
        except (TypeError, ValueError):
            return Response({"detail": "amount_cents (integer) required"}, status=status.HTTP_400_BAD_REQUEST)
        if amount_cents <= 0:
            return Response({"detail": "amount must be positive"}, status=status.HTTP_400_BAD_REQUEST)

        m = membership_for(request.user)
        w = wallet_for(request.user)
        dev, net = split_cents(amount_cents, m.dev_tax_rate)
        w.money_cents += net
        w.save(update_fields=["money_cents", "updated_at"])
        Transaction.objects.create(
            user=request.user, kind=Transaction.KIND_ADD, amount_cents=net,
            dev_tax_cents=dev, note=request.data.get("note", "Add funds")[:200],
        )
        return Response(
            {
                "wallet": WalletSerializer(w).data,
                "breakdown": {"gross_cents": amount_cents, "dev_tax_cents": dev, "net_cents": net, "rate": m.dev_tax_rate},
            }
        )


class MembershipView(APIView):
    """GET current tier; POST sets it (dev/testing — real upgrades go via billing)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        m = membership_for(request.user)
        return Response({"tier": m.tier, "dev_tax_rate": m.dev_tax_rate, "rates": DEV_TAX})

    def post(self, request):
        tier = str(request.data.get("tier", "")).lower()
        if tier not in VALID_TIERS:
            return Response({"detail": f"tier must be one of {sorted(VALID_TIERS)}"}, status=status.HTTP_400_BAD_REQUEST)
        m = membership_for(request.user)
        m.tier = tier
        m.save(update_fields=["tier", "updated_at"])
        return Response({"tier": m.tier, "dev_tax_rate": m.dev_tax_rate})
