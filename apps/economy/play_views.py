"""Google Play Billing endpoints.

    GET  /api/economy/play/products/   what the client may offer
    POST /api/economy/play/verify/     verify a purchase token and grant it

Verification is the only way a Play purchase turns into anything on this
platform. There is deliberately no "trust the client" path: the Digital Goods API
hands the app a purchase token, the app hands it here, and this asks Google.
"""
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import play_billing
from .models import PlayPurchase, wallet_for
from .serializers import WalletSerializer


class PlayProductsView(APIView):
    """GET the product catalog. Public so the store screen renders pre-login."""

    permission_classes = [AllowAny]

    def get(self, _request):
        return Response(play_billing.catalog_payload())


class PlayVerifyView(APIView):
    """POST {product_id, purchase_token} -> verified with Google, then granted.

    503 when the server has no service account (the client should fall back to
    web checkout), 400 when Google says the purchase isn't good, 200 with
    `duplicate: true` when the same token is sent twice — which happens routinely,
    because a client that doesn't get our response will retry.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        d = request.data or {}
        if not play_billing.configured():
            return Response(
                {"detail": "Play Billing is not configured on the server.",
                 "configured": False},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        result, err = play_billing.redeem(
            request.user, d.get("product_id"), d.get("purchase_token"))
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "purchase": result,
            "wallet": WalletSerializer(wallet_for(request.user)).data,
        })


class PlayPurchasesView(APIView):
    """GET this member's verified Play purchases — their receipts, and the record
    support needs when somebody says a purchase didn't land."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = PlayPurchase.objects.filter(user=request.user)[:100]
        return Response({"purchases": [
            {"product_id": p.product_id, "kind": p.kind, "value_cents": p.value_cents,
             "order_id": p.order_id, "subscription": p.subscription,
             "granted": p.granted, "acknowledged": p.acknowledged,
             "detail": p.detail, "created_at": p.created_at}
            for p in rows
        ]})
