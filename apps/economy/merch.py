"""MerchZ — a legal-goods marketplace. Creators list apparel, art, beats,
sample packs, etc.; buyers pay from their wallet with the developer tax
enforced server-side (via pay_between). Substances/paraphernalia are not a
category — this is legal goods only.
"""
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import MerchItem, MerchPurchase, pay_between, refund_cents, wallet_for
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


def _purchase_dict(p):
    return {
        "id": p.id,
        "item_id": p.item_id,
        "item_title": p.item.title,
        "buyer": p.buyer.username,
        "price_cents": p.price_cents,
        "dev_tax_cents": p.dev_tax_cents,
        "net_received_cents": p.price_cents - p.dev_tax_cents,
        "refunded": p.refunded,
        "refunded_at": p.refunded_at,
        "refund_reason": p.refund_reason,
        "created_at": p.created_at,
    }


class MerchSalesView(APIView):
    """GET your own sales — the half of MerchZ that had no screen at all.
    A seller could see what they'd LISTED but never what anyone had actually
    BOUGHT from them, which is also the only place a refund can start from."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = (MerchPurchase.objects.filter(item__seller=request.user)
                .select_related("item", "buyer").order_by("-created_at")[:200])
        return Response({"sales": [_purchase_dict(p) for p in rows]})


class MerchRefundView(APIView):
    """GET: what refunding this sale costs you, before you press anything —
    the cost/gain rule applied to the most expensive thing a seller can do
    here. POST: do it.

    Corey's call: the SELLER eats the developer tax. A refund gives the
    buyer back the full `price_cents`, and the seller's wallet is debited
    that same full amount — not just the net they were paid — so the tax
    the platform took on the original sale is never handed back to anyone.
    `refund_cents` is its own atomic primitive for exactly that reason: it
    is not `pay_between` run backwards, because `pay_between` would split
    the tax AGAIN on the way back.
    """

    permission_classes = [IsAuthenticated]

    def _mine(self, request, pk):
        p = (MerchPurchase.objects.filter(pk=pk).select_related("item", "buyer").first())
        if not p:
            return None
        if p.item.seller_id != request.user.id and not (request.user.is_staff or request.user.is_superuser):
            return None
        return p

    def get(self, request, pk):
        p = self._mine(request, pk)
        if not p:
            return Response({"detail": "Not yours, or not here."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_purchase_dict(p))

    def post(self, request, pk):
        p = self._mine(request, pk)
        if not p:
            return Response({"detail": "Not yours, or not here."}, status=status.HTTP_404_NOT_FOUND)
        if p.refunded:
            return Response({"detail": "Already refunded."}, status=status.HTTP_400_BAD_REQUEST)
        reason = str(request.data.get("reason", "") or "")[:200]
        with transaction.atomic():
            new_balance = refund_cents(p.item.seller, p.buyer, p.price_cents,
                                       note=f"MerchZ refund: {p.item.title}")
            if new_balance is None:
                return Response(
                    {"detail": f"You received {p.price_cents - p.dev_tax_cents}¢ net from this sale, but "
                               f"refunding it costs the full {p.price_cents}¢ — the platform's fee isn't "
                               f"given back on a refund. Your balance doesn't cover that right now."},
                    status=status.HTTP_402_PAYMENT_REQUIRED,
                )
            p.refunded = True
            p.refunded_at = timezone.now()
            p.refund_reason = reason
            p.save(update_fields=["refunded", "refunded_at", "refund_reason"])
        return Response({
            "purchase": _purchase_dict(p),
            "wallet": WalletSerializer(wallet_for(request.user)).data,
        })


class MerchBuyView(APIView):
    """Buy an item: pay the seller from your wallet, developer tax enforced."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        it = MerchItem.objects.select_related("seller").filter(pk=pk, active=True).first()
        if not it:
            return Response({"detail": "item not found"}, status=status.HTTP_404_NOT_FOUND)
        if it.seller_id == request.user.id:
            return Response({"detail": "you can't buy your own item"}, status=status.HTTP_400_BAD_REQUEST)
        # The real guard is inside `pay_between` now (a conditional atomic
        # update), so two concurrent buys of the same balance can't both
        # pass. This stays as the fast, friendly rejection for the common
        # case — not having the money — before anything is created.
        w = wallet_for(request.user)
        if w.money_cents < it.price_cents:
            return Response({"detail": "insufficient balance"}, status=status.HTTP_402_PAYMENT_REQUIRED)
        with transaction.atomic():
            moved = pay_between(request.user, it.seller, it.price_cents, note=f"MerchZ: {it.title}")
            if moved is None:
                return Response({"detail": "insufficient balance"}, status=status.HTTP_402_PAYMENT_REQUIRED)
            dev, _net = moved
            MerchPurchase.objects.create(buyer=request.user, item=it, price_cents=it.price_cents, dev_tax_cents=dev)
        return Response({"wallet": WalletSerializer(wallet_for(request.user)).data, "item_id": it.id, "dev_tax_cents": dev})
