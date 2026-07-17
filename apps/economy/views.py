from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import SPECZ_CATALOG, cashout_rate, limits_for
from .models import (
    DEV_TAX,
    TIER_CHOICES,
    TIER_STATZ,
    RoyaltyEntry,
    SpecZPurchase,
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


class LimitsView(APIView):
    """Per-tier caps for the client to enforce (char/upload/storage)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        m = membership_for(request.user)
        lim = dict(limits_for(m.tier))
        lim["tier"] = m.tier
        lim["dev_tax_rate"] = m.dev_tax_rate
        lim["storage_used_mb"] = 0  # real usage tracking arrives with the upload pipeline
        return Response(lim)


class SpecZView(APIView):
    """GET the SpecZ catalog with owned flags; POST buys an item (StatZ only)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        owned = set(request.user.specz_purchases.values_list("item_id", flat=True))
        items = [
            {"id": iid, "name": d["name"], "price_cents": d["price_cents"], "owned": iid in owned}
            for iid, d in SPECZ_CATALOG.items()
        ]
        return Response({"items": items})

    def post(self, request):
        m = membership_for(request.user)
        if m.tier != TIER_STATZ:
            return Response({"detail": "SpecZ is a StatZ-only marketplace"}, status=status.HTTP_403_FORBIDDEN)
        item_id = str(request.data.get("item_id", ""))
        item = SPECZ_CATALOG.get(item_id)
        if not item:
            return Response({"detail": "unknown item"}, status=status.HTTP_400_BAD_REQUEST)
        if request.user.specz_purchases.filter(item_id=item_id).exists():
            return Response({"detail": "already owned"}, status=status.HTTP_409_CONFLICT)
        w = wallet_for(request.user)
        price = item["price_cents"]
        if w.money_cents < price:
            return Response({"detail": "insufficient balance"}, status=status.HTTP_402_PAYMENT_REQUIRED)
        dev, _ = split_cents(price, m.dev_tax_rate)  # developer tax recorded on the sale
        w.money_cents -= price
        w.save(update_fields=["money_cents", "updated_at"])
        SpecZPurchase.objects.create(user=request.user, item_id=item_id, price_cents=price, dev_tax_cents=dev)
        Transaction.objects.create(
            user=request.user, kind=Transaction.KIND_PURCHASE, amount_cents=-price,
            dev_tax_cents=dev, note=f"SpecZ: {item['name']}",
        )
        return Response({"wallet": WalletSerializer(w).data, "item_id": item_id, "dev_tax_cents": dev})


class RoyaltiesView(APIView):
    """GET royalty balance + ledger."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        w = wallet_for(request.user)
        entries = [
            {"kind": e.kind, "amount_cents": e.amount_cents, "tax_cents": e.tax_cents, "source": e.source, "created_at": e.created_at}
            for e in request.user.royalty_entries.all()[:50]
        ]
        return Response({"royalties_cents": w.royalties_cents, "royalties": w.royalties, "entries": entries})


class RoyaltyAccrueView(APIView):
    """Accrue royalties to a user (called when their media earns; open for testing)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            amount_cents = int(request.data.get("amount_cents"))
        except (TypeError, ValueError):
            return Response({"detail": "amount_cents (integer) required"}, status=status.HTTP_400_BAD_REQUEST)
        if amount_cents <= 0:
            return Response({"detail": "amount must be positive"}, status=status.HTTP_400_BAD_REQUEST)
        w = wallet_for(request.user)
        w.royalties_cents += amount_cents
        w.save(update_fields=["royalties_cents", "updated_at"])
        RoyaltyEntry.objects.create(
            user=request.user, kind=RoyaltyEntry.KIND_ACCRUAL, amount_cents=amount_cents,
            source=str(request.data.get("source", ""))[:200],
        )
        return Response({"royalties_cents": w.royalties_cents, "royalties": w.royalties})


class RoyaltyCashoutView(APIView):
    """Cash out royalties into the wallet, applying the plan's tax.

    Plans: instant (15%), weekly (dev-tax rate), monthly (1%), quarterly (0%).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        plan = str(request.data.get("plan", "")).lower()
        m = membership_for(request.user)
        rate = cashout_rate(plan, m.dev_tax_rate)
        if rate is None:
            return Response({"detail": "plan must be instant|weekly|monthly|quarterly"}, status=status.HTTP_400_BAD_REQUEST)
        w = wallet_for(request.user)
        gross = w.royalties_cents
        if gross <= 0:
            return Response({"detail": "no royalties to cash out"}, status=status.HTTP_400_BAD_REQUEST)
        tax = round(gross * rate)
        net = gross - tax
        w.royalties_cents = 0
        w.money_cents += net
        w.save(update_fields=["royalties_cents", "money_cents", "updated_at"])
        RoyaltyEntry.objects.create(user=request.user, kind=RoyaltyEntry.KIND_CASHOUT, amount_cents=-gross, tax_cents=tax, source=f"{plan} cashout")
        Transaction.objects.create(user=request.user, kind=Transaction.KIND_ROYALTY, amount_cents=net, dev_tax_cents=tax, note=f"Royalty cashout ({plan})")
        return Response({"wallet": WalletSerializer(w).data, "breakdown": {"gross_cents": gross, "tax_cents": tax, "net_cents": net, "rate": rate, "plan": plan}})
