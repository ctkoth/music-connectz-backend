"""Print-on-demand MerchZ endpoints — design once, list anywhere, print on sale.

    GET         /api/economy/pod/blanks/            the product catalog + costs
    GET  POST   /api/economy/pod/designs/           your designs / upload one
    DELETE      /api/economy/pod/designs/<id>/
    GET  POST   /api/economy/pod/listings/          the shop / list a design on a blank
    DELETE      /api/economy/pod/listings/<id>/
    POST        /api/economy/pod/listings/<id>/buy/ buy it (made to order)
    GET         /api/economy/pod/orders/            your orders + your sales
    POST        /api/economy/pod/orders/<id>/status/ seller/owner moves it along
    GET         /api/economy/pod/orders/<id>/invoice/ one order, as a document
    GET         /api/economy/pod/sales/             what's selling (ranked)
    GET         /api/economy/pod/statement/         a month, for the accountant

The catalog endpoint is public so a shop can be browsed before signing up.
Everything else needs a login.
"""
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import pod, pod_reports
from .models import (MerchDesign, PrintListing, PrintOrder, PrintProduct,
                     wallet_for)
from .serializers import WalletSerializer
from .views import is_owner

MAX_DESIGNS = 100


def _image_url(image, request):
    try:
        return request.build_absolute_uri(image.url) if image else None
    except ValueError:
        return None


def _product_dict(p, price_cents=None):
    return {
        "key": p.key,
        "name": p.name,
        "category": p.category,
        "base_cost_cents": p.base_cost_cents,
        "shipping_cents": p.shipping_cents,
        "landed_cost_cents": p.landed_cost_cents,
        "suggested_price_cents": pod.suggested_price_cents(p),
        "sizes": p.sizes,
        "colors": p.colors,
        # What the artwork has to be to survive this blank's process.
        "print_method": p.print_method,
        "artwork": p.artwork,
        # Per-variant cost and stock, so the buyer picks their real size and
        # sees the upcharge next to it instead of at checkout.
        "variants": pod.variant_table(p, price_cents),
        "provider": p.provider,
    }


def _design_dict(d, request):
    return {
        "id": d.id,
        "title": d.title,
        "image_url": _image_url(d.image, request),
        "listings": d.listings.count(),
        "created_at": d.created_at,
    }


def _listing_dict(li, request):
    return {
        "id": li.id,
        "title": li.title,
        "description": li.description,
        "price_cents": li.price_cents,
        "margin_cents": li.margin_cents,
        "seller": li.seller.username,
        "mine": li.seller_id == getattr(request.user, "id", None),
        "design": {"id": li.design_id, "title": li.design.title,
                   "image_url": _image_url(li.design.image, request)},
        "product": _product_dict(li.product, li.price_cents),
        "sold": li.orders.exclude(status=PrintOrder.STATUS_CANCELLED).count(),
        "made_to_order": True,
        "created_at": li.created_at,
    }


def _order_dict(o):
    return {
        "id": o.id,
        "listing_id": o.listing_id,
        "title": o.listing.title,
        "product": o.listing.product.key,
        "size": o.size,
        "color": o.color,
        "quantity": o.quantity,
        "price_cents": o.price_cents,
        "upcharge_cents": o.upcharge_cents,
        "base_cost_cents": o.base_cost_cents,
        "seller_cents": o.seller_cents,
        "dev_tax_cents": o.dev_tax_cents,
        "status": o.status,
        "provider": o.provider,
        "provider_order_id": o.provider_order_id,
        "tracking_url": o.tracking_url,
        "note": o.note,
        "buyer": o.buyer.username,
        "seller": o.seller.username,
        "created_at": o.created_at,
    }


class BlanksView(APIView):
    """GET the blanks a design can go on, with what each costs to make."""

    permission_classes = [AllowAny]

    def get(self, _request):
        products = PrintProduct.objects.filter(active=True)
        return Response({
            "blanks": [_product_dict(p) for p in products],
            # Grouped so a picker can show "Apparel / Headwear / Home" tabs.
            "categories": sorted({p.category for p in products}),
            "print_methods": pod.PRINT_METHODS,
            "provider": pod.provider_name(),
            # Said out loud because it's the pitch: nothing is made until it sells.
            "made_to_order": True,
            "holds_inventory": False,
            "limits": {"min_price_cents": pod.MIN_PRICE_CENTS,
                       "max_price_cents": pod.MAX_PRICE_CENTS,
                       "max_quantity": pod.MAX_QUANTITY,
                       "max_designs": MAX_DESIGNS},
        })


class DesignsView(APIView):
    """Your artwork. One design, then list it on as many blanks as you like."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        return Response({"designs": [_design_dict(d, request)
                                     for d in request.user.merch_designs.all()[:MAX_DESIGNS]]})

    def post(self, request):
        title = str(request.data.get("title", "")).strip()
        image = request.FILES.get("image")
        if not title:
            return Response({"detail": "title required"}, status=status.HTTP_400_BAD_REQUEST)
        if not image:
            return Response({"detail": "image file required"}, status=status.HTTP_400_BAD_REQUEST)
        if request.user.merch_designs.count() >= MAX_DESIGNS:
            return Response({"detail": f"you already have {MAX_DESIGNS} designs"},
                            status=status.HTTP_400_BAD_REQUEST)
        d = MerchDesign.objects.create(owner=request.user, title=title[:120], image=image)
        return Response({"design": _design_dict(d, request)}, status=status.HTTP_201_CREATED)


class DesignDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        d = request.user.merch_designs.filter(pk=pk).first()
        if not d:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        # Orders reference the listing, which references the design, so refuse
        # rather than cascade a sale record into nothing.
        if PrintOrder.objects.filter(listing__design=d).exists():
            return Response(
                {"detail": "this design has sold — deactivate its listings instead of deleting it"},
                status=status.HTTP_409_CONFLICT,
            )
        if d.image:
            d.image.delete(save=False)
        d.delete()
        return Response({"deleted": pk})


class ListingsView(APIView):
    """GET the shop (or `?mine=1` for yours); POST puts a design on a blank."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = PrintListing.objects.filter(active=True).select_related(
            "design", "product", "seller")
        if request.query_params.get("mine") in ("1", "true"):
            qs = qs.filter(seller=request.user)
        if request.query_params.get("seller"):
            qs = qs.filter(seller__username=request.query_params["seller"])
        return Response({"listings": [_listing_dict(li, request) for li in qs[:200]]})

    def post(self, request):
        d = request.data or {}
        design = request.user.merch_designs.filter(pk=d.get("design_id")).first()
        if not design:
            return Response({"detail": "design_id must be one of your designs"},
                            status=status.HTTP_400_BAD_REQUEST)
        product = PrintProduct.objects.filter(key=str(d.get("product", "")).strip(),
                                              active=True).first()
        if not product:
            return Response({"detail": "unknown product — see /api/economy/pod/blanks/"},
                            status=status.HTTP_400_BAD_REQUEST)
        ok, detail = pod.validate_price(product, d.get("price_cents"))
        if not ok:
            return Response({"detail": detail,
                             "break_even_cents": product.landed_cost_cents,
                             "suggested_price_cents": pod.suggested_price_cents(product)},
                            status=status.HTTP_400_BAD_REQUEST)
        if PrintListing.objects.filter(design=design, product=product).exists():
            return Response({"detail": f"{design.title} is already listed on {product.name}"},
                            status=status.HTTP_409_CONFLICT)
        li = PrintListing.objects.create(
            design=design, product=product, seller=request.user,
            title=str(d.get("title") or f"{design.title} — {product.name}")[:120],
            description=str(d.get("description", ""))[:500],
            price_cents=int(d["price_cents"]),
        )
        return Response({"listing": _listing_dict(li, request),
                         "quote": pod.quote(product, li.price_cents)},
                        status=status.HTTP_201_CREATED)


class ListingDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        li = request.user.print_listings.filter(pk=pk).first()
        if not li:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        # Sold listings are deactivated, never deleted — an order has to keep
        # pointing at what was bought.
        if li.orders.exists():
            li.active = False
            li.save(update_fields=["active"])
            return Response({"deactivated": pk, "reason": "it has orders"})
        li.delete()
        return Response({"deleted": pk})


class ListingBuyView(APIView):
    """POST {size, color, quantity, ship_to} — buy it; it gets made after."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        li = PrintListing.objects.select_related("product", "seller", "design").filter(
            pk=pk, active=True).first()
        if not li:
            return Response({"detail": "listing not found"}, status=status.HTTP_404_NOT_FOUND)
        if li.seller_id == request.user.id:
            return Response({"detail": "you can't buy your own listing"},
                            status=status.HTTP_400_BAD_REQUEST)
        d = request.data or {}
        ok, detail = pod.validate_address(d.get("ship_to"))
        if not ok:
            return Response({"detail": detail, "required": list(pod.REQUIRED_ADDRESS)},
                            status=status.HTTP_400_BAD_REQUEST)

        size = str(d.get("size", "")).strip()
        if li.product.sizes and size not in li.product.sizes:
            return Response({"detail": f"size must be one of {li.product.sizes}",
                             "variants": pod.variant_table(li.product, li.price_cents)},
                            status=status.HTTP_400_BAD_REQUEST)
        color = str(d.get("color", "")).strip()
        if li.product.colors and color and color not in li.product.colors:
            return Response({"detail": f"color must be one of {li.product.colors}",
                             "variants": pod.variant_table(li.product, li.price_cents)},
                            status=status.HTTP_400_BAD_REQUEST)

        order, err = pod.place_order(request.user, li, size=size, color=color,
                                     quantity=d.get("quantity", 1), ship_to=d["ship_to"])
        if err:
            code = (status.HTTP_402_PAYMENT_REQUIRED if err == "insufficient balance"
                    else status.HTTP_400_BAD_REQUEST)
            return Response({"detail": err}, status=code)
        return Response({"order": _order_dict(order),
                         "wallet": WalletSerializer(wallet_for(request.user)).data},
                        status=status.HTTP_201_CREATED)


class OrdersView(APIView):
    """GET your purchases and, separately, the ones you have to get made."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        base = PrintOrder.objects.select_related("listing", "listing__product", "buyer", "seller")
        mine = base.filter(buyer=request.user)[:100]
        sales = base.filter(seller=request.user)[:100]
        return Response({
            "orders": [_order_dict(o) for o in mine],
            "sales": [_order_dict(o) for o in sales],
            # The queue a seller actually works from when there's no provider.
            "to_fulfil": [_order_dict(o) for o in sales if o.status == PrintOrder.STATUS_PENDING],
            "provider": pod.provider_name(),
        })


class OrderStatusView(APIView):
    """POST {status, tracking_url?, provider_order_id?, note?} — move an order on.

    The seller drives it (that's who is getting it printed), and the platform
    owner can too, for support. A buyer cannot: marking your own order delivered
    is not a thing.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        o = PrintOrder.objects.select_related("listing", "listing__product").filter(pk=pk).first()
        if not o:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        if o.seller_id != request.user.id and not is_owner(request.user):
            return Response({"detail": "only the seller can update this order"},
                            status=status.HTTP_403_FORBIDDEN)
        d = request.data or {}
        ok, detail = pod.advance(
            o, str(d.get("status", "")).strip(),
            provider_order_id=d.get("provider_order_id", ""),
            tracking_url=d.get("tracking_url", ""),
            note=d.get("note", ""),
        )
        if not ok:
            return Response({"detail": detail, "statuses": PrintOrder.STATUSES},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response({"order": _order_dict(o)})


class SalesReportView(APIView):
    """GET what's selling. `?from=YYYY-MM-DD&to=YYYY-MM-DD` to bound it.

    Ranked by revenue, not units — ten stickers and one hoodie are not the same
    result, and this is the number a creator should decide from.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        start = pod_reports.parse_day(request.query_params.get("from"))
        end = pod_reports.parse_day(request.query_params.get("to"), end=True)
        if request.query_params.get("from") and not start:
            return Response({"detail": "from must be YYYY-MM-DD"},
                            status=status.HTTP_400_BAD_REQUEST)
        if request.query_params.get("to") and not end:
            return Response({"detail": "to must be YYYY-MM-DD"},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(pod_reports.sales_report(request.user, start=start, end=end))


class OrderInvoiceView(APIView):
    """GET one order's invoice. Buyer, seller, or the platform owner only —
    the document carries a shipping address."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        o = PrintOrder.objects.select_related(
            "listing", "listing__product", "buyer", "seller").filter(pk=pk).first()
        # 404 rather than 403 for someone else's invoice: whether an order exists
        # isn't their business either.
        if not o or not pod_reports.can_view(o, request.user):
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"invoice": pod_reports.invoice(o, viewer=request.user)})


class StatementView(APIView):
    """GET a month's statement. `?month=YYYY-MM`, defaults to this month."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        raw = str(request.query_params.get("month", "")).strip()
        if raw:
            try:
                year, month = (int(x) for x in raw.split("-", 1))
                if not 1 <= month <= 12:
                    raise ValueError
            except (TypeError, ValueError):
                return Response({"detail": "month must be YYYY-MM"},
                                status=status.HTTP_400_BAD_REQUEST)
        else:
            now = timezone.now()
            year, month = now.year, now.month
        return Response({"statement": pod_reports.statement(request.user, year, month)})
