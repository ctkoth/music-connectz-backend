"""Shops of members' own designs, printed on demand, and how a sale splits.

A design shop listing is a PrintDesign: the member's mockup from the MercheZ designer and which product it goes
on. Each product carries its own MARKUP, set from the printer's cost (see MARKUP_BY_PRODUCT). The price a buyer pays is
the printer's cost plus that markup, and the split is:

    printer's cost -> the printer (it makes and ships the item)
    dev tax        -> the platform, taken from the MARKUP only, at the BUYER's tier rate (as every MercheZ sale)
    the rest       -> the designer

The dev tax is on the markup, never on the printer's cost: taxing money that goes straight to the printer would
charge the designer for a cost they do not keep. CHECKOUT IS NOT OPEN: no printer account is connected, so
`checkout_open` is False and a buy answers 503 before anything moves. The printer's costs below are Printify's catalog
prices, read by test product for one size and colour of each, not a live price list.
"""
from django.db import transaction
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DEV_TAX, TIER_FREE, TIER_PREMIUM, TIER_STATZ, PrintDesign, membership_for, split_cents


def rate_for(user):
    """The app-wide dev tax at the BUYER's plan, as every MercheZ sale."""
    return membership_for(user).dev_tax_rate

# Printer cost per item, before shipping, in cents: read from Printify's catalog by a test product for one size and
# colour of each, on 27 Nov 2026. The bandana is a 25-inch poly scarf, and the wave cap is a surf cap: both are stand-ins,
# because Printify's catalog has no matching product for either. Durag has none, so it is hidden from new listings; its
# old headband cost stays only so that any older listing still reads.
BASE_CENTS = {"shirt": 968, "hoodie": 2499, "towel": 2370, "bandana": 1453, "wavecap": 2127, "durag": 1582,
              "baseballcap": 1538, "mug": 644, "phonecase": 1311, "sticker": 142, "poster": 1186, "buckethat": 2105,
              "beanie": 1526, "tote": 1874}
LABELS = {"shirt": "T-shirt", "hoodie": "Hoodie", "towel": "Towel", "bandana": "Bandana", "wavecap": "Wave cap", "durag": "Durag", "baseballcap": "Baseball cap", "mug": "Mug", "phonecase": "Phone case", "sticker": "Sticker", "poster": "Poster", "buckethat": "Bucket hat", "beanie": "Beanie", "tote": "Tote bag"}
# The markup each product carries over its printer cost, set by that cost: under $2 gets $3, $2 to under $9 gets $5,
# and $9 or more gets $10. The plans differ in the dev tax taken from it (models.DEV_TAX, at the BUYER's plan), not in
# the markup. A design listed before this change still holds the markup it was listed with in the database; every read
# and every sale uses the product's markup from here.
MARKUP_BY_PRODUCT = {"shirt": 1000, "hoodie": 1000, "towel": 1000, "bandana": 1000, "wavecap": 1000, "durag": 1000,
                     "baseballcap": 1000, "mug": 500, "phonecase": 1000, "sticker": 300, "poster": 1000,
                     "buckethat": 1000, "beanie": 1000, "tote": 1000}
# Products the designer does not offer yet: no new listing can be made in them, though older listings still read.
HIDDEN_PRODUCTS = {"durag"}
MARKUP_NOTE = "Each product carries its own set markup, so leave the markup out when you list a design."
MAX_IMAGE_BYTES = 8 * 1024 * 1024
PER_DESIGNER = 200
CHECKOUT_OPEN = False
COST_NOTE = ("Printer costs are Printify's, read on 27 Nov 2026 for one size and colour of each product. Shipping is extra "
             "and quoted for each buyer's address at checkout.")
CLOSED_NOTE = "Checkout isn't open yet — no printer is connected, so nothing can be bought and nothing was charged."
OWN_ART_RULE = "Only your own art: no team or brand logos, characters or other people's work."


def markup_for(product):
    """The markup a design of this product carries, whatever the member's plan."""
    return MARKUP_BY_PRODUCT[product]


def split(product, markup_cents, rate):
    base = BASE_CENTS[product]
    dev, designer = split_cents(markup_cents, rate)
    return {"price": base + markup_cents, "printer": base, "dev_tax": dev, "designer": designer}


def designer_range(product, markup_cents):
    """What the designer keeps, lowest to highest: the tax depends on who buys."""
    rates = [DEV_TAX[t] for t in (TIER_FREE, TIER_PREMIUM, TIER_STATZ)]
    keeps = [split(product, markup_cents, r)["designer"] for r in rates]
    return {"min": min(keeps), "max": max(keeps)}


def _standard(raw, product):
    """True when a client sent no markup, or the markup this product carries. Anything else is refused, so no client
    can list a design at a markup the rest of the shop does not carry for that product."""
    if raw in (None, ""):
        return True
    try:
        return int(raw) == markup_for(product)
    except (TypeError, ValueError):
        return False


def _dict(d, request):
    rate = rate_for(request.user)
    m = markup_for(d.product)
    out = {"id": d.id, "designer": d.designer.username, "product": d.product, "product_label": LABELS.get(d.product, d.product),
           "color": d.color, "title": d.title, "image": request.build_absolute_uri(d.image.url) if d.image else "",
           "markup_cents": m, "mine": d.designer_id == request.user.id,
           "split": split(d.product, m, rate)}
    if out["mine"]:
        out["designer_keeps"] = designer_range(d.product, m)
    return out


def _meta():
    return {"base_cents": BASE_CENTS, "labels": LABELS, "markup_by_product": MARKUP_BY_PRODUCT, "checkout_open": CHECKOUT_OPEN,
            "estimate_note": COST_NOTE, "closed_note": CLOSED_NOTE, "own_art_rule": OWN_ART_RULE,
            "dev_tax": {"free": DEV_TAX[TIER_FREE], "premium": DEV_TAX[TIER_PREMIUM], "statz": DEV_TAX[TIER_STATZ]},
            "split_rule": "Buyer pays the printer's cost plus the markup set for that product. The printer gets its cost; the "
                          "dev tax comes out of the markup at the buyer's plan rate; you keep the rest."}


class ShopView(APIView):
    """GET shops (?designer=<username>, ?mine=1); POST lists a design (multipart: image, product, color, title,
    own_art; markup_cents is optional and, if sent, must be the product's markup)."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        q = PrintDesign.objects.filter(active=True).select_related("designer")
        if request.query_params.get("mine"):
            q = q.filter(designer=request.user)
        elif request.query_params.get("designer"):
            q = q.filter(designer__username=request.query_params["designer"])
        return Response({"designs": [_dict(d, request) for d in q[:200]], **_meta()})

    def post(self, request):
        d = request.data
        product = str(d.get("product", ""))
        if product not in BASE_CENTS:
            return Response({"detail": "Pick one of the products in the designer."}, status=status.HTTP_400_BAD_REQUEST)
        if product in HIDDEN_PRODUCTS:
            return Response({"detail": f"{LABELS.get(product, product)} isn't on sale yet. Pick another product."}, status=status.HTTP_400_BAD_REQUEST)
        if str(d.get("own_art", "")).lower() not in ("1", "true", "yes"):
            return Response({"detail": OWN_ART_RULE + " Tick that the design is yours to list it."}, status=status.HTTP_400_BAD_REQUEST)
        title = str(d.get("title", "")).strip()[:120]
        if not title:
            return Response({"detail": "Give the design a name."}, status=status.HTTP_400_BAD_REQUEST)
        if not _standard(d.get("markup_cents"), product):
            return Response({"detail": MARKUP_NOTE}, status=status.HTTP_400_BAD_REQUEST)
        img = request.FILES.get("image")
        if not img or not str(getattr(img, "content_type", "")).startswith("image/") or img.size > MAX_IMAGE_BYTES:
            return Response({"detail": "Add the design's picture (an image under 8 MB)."}, status=status.HTTP_400_BAD_REQUEST)
        if PrintDesign.objects.filter(designer=request.user, active=True).count() >= PER_DESIGNER:
            return Response({"detail": f"A shop holds {PER_DESIGNER} designs. Remove one to add another."}, status=status.HTTP_400_BAD_REQUEST)
        color = str(d.get("color", "#111111"))
        if not (len(color) == 7 and color.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in color[1:])):
            color = "#111111"
        pd = PrintDesign.objects.create(designer=request.user, product=product, color=color, title=title,
                                        image=img, markup_cents=markup_for(product), own_art=True)
        return Response({"design": _dict(pd, request), **_meta()}, status=status.HTTP_201_CREATED)


class ShopDesignView(APIView):
    """PATCH your own design's title (its markup is set by its product); DELETE takes it out of your shop."""

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser]

    def _mine(self, request, pk):
        return PrintDesign.objects.filter(pk=pk, designer=request.user, active=True).first()

    def patch(self, request, pk):
        pd = self._mine(request, pk)
        if not pd:
            return Response({"detail": "Not one of your designs."}, status=status.HTTP_404_NOT_FOUND)
        if "markup_cents" in request.data:
            if not _standard(request.data["markup_cents"], pd.product):
                return Response({"detail": MARKUP_NOTE}, status=status.HTTP_400_BAD_REQUEST)
            pd.markup_cents = markup_for(pd.product)
        if str(request.data.get("title", "")).strip():
            pd.title = str(request.data["title"]).strip()[:120]
        pd.save()
        return Response({"design": _dict(pd, request)})

    def delete(self, request, pk):
        pd = self._mine(request, pk)
        if not pd:
            return Response({"detail": "Not one of your designs."}, status=status.HTTP_404_NOT_FOUND)
        pd.active = False
        pd.save(update_fields=["active"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ShopBuyView(APIView):
    """Closed until a printer is connected. Says so before anything moves."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        pd = PrintDesign.objects.filter(pk=pk, active=True).first()
        if not pd:
            return Response({"detail": "That design isn't in a shop."}, status=status.HTTP_404_NOT_FOUND)
        if not CHECKOUT_OPEN:
            return Response({"detail": CLOSED_NOTE, "checkout_open": False}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        with transaction.atomic():   # pragma: no cover — wired when the printer is
            raise NotImplementedError
