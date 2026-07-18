"""MerchZ — a legal-goods marketplace. Creators list apparel, art, beats,
sample packs, etc.; buyers pay from their wallet with the developer tax
enforced server-side (via pay_between). Substances/paraphernalia are not a
category — this is legal goods only.
"""
from django.db import transaction
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import MerchItem, MerchPurchase, pay_between, wallet_for
from .serializers import WalletSerializer

MIN_PRICE = 100        # $1
MAX_PRICE = 5_000_00   # $5,000


def _item_dict(it, request):
    return {
        "id": it.id,
        "title": it.title,
        "description": it.description,
        "category": it.category,
        "price_cents": it.price_cents,
        "seller": it.seller.username,
        "mine": it.seller_id == request.user.id,
        "image_url": request.build_absolute_uri(it.image.url) if it.image else None,
        "sold": it.purchases.count(),
        "bought": it.purchases.filter(buyer=request.user).exists(),
        "created_at": it.created_at,
    }


class MerchView(APIView):
    """GET the marketplace + your listings; POST creates a listing."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        items = MerchItem.objects.filter(active=True).select_related("seller")[:200]
        return Response({"items": [_item_dict(i, request) for i in items]})

    def post(self, request):
        d = request.data
        title = str(d.get("title", "")).strip()
        if not title:
            return Response({"detail": "title required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            price = int(d.get("price_cents"))
        except (TypeError, ValueError):
            return Response({"detail": "price_cents (integer) required"}, status=status.HTTP_400_BAD_REQUEST)
        if not (MIN_PRICE <= price <= MAX_PRICE):
            return Response({"detail": f"price must be {MIN_PRICE}-{MAX_PRICE} cents"}, status=status.HTTP_400_BAD_REQUEST)
        category = d.get("category") if d.get("category") in MerchItem.CATEGORIES else "apparel"
        it = MerchItem.objects.create(
            seller=request.user, title=title[:120],
            description=str(d.get("description", ""))[:500],
            category=category, price_cents=price,
            image=request.FILES.get("image"),
        )
        return Response({"item": _item_dict(it, request)}, status=status.HTTP_201_CREATED)


class MerchDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        it = request.user.merch_items.filter(pk=pk).first()
        if not it:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        if it.image:
            it.image.delete(save=False)
        it.delete()
        return Response({"deleted": pk})


class MerchBuyView(APIView):
    """Buy an item: pay the seller from your wallet, developer tax enforced."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        it = MerchItem.objects.select_related("seller").filter(pk=pk, active=True).first()
        if not it:
            return Response({"detail": "item not found"}, status=status.HTTP_404_NOT_FOUND)
        if it.seller_id == request.user.id:
            return Response({"detail": "you can't buy your own item"}, status=status.HTTP_400_BAD_REQUEST)
        w = wallet_for(request.user)
        if w.money_cents < it.price_cents:
            return Response({"detail": "insufficient balance"}, status=status.HTTP_402_PAYMENT_REQUIRED)
        with transaction.atomic():
            dev, _net = pay_between(request.user, it.seller, it.price_cents, note=f"MerchZ: {it.title}")
            MerchPurchase.objects.create(buyer=request.user, item=it, price_cents=it.price_cents, dev_tax_cents=dev)
        return Response({"wallet": WalletSerializer(wallet_for(request.user)).data, "item_id": it.id, "dev_tax_cents": dev})
