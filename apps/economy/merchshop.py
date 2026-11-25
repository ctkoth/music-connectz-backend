"""Shops of members' own designs, printed on demand, and how a sale splits.

A design shop listing is a PrintDesign: the member's mockup from the MercheZ designer, which product it goes
on, and their MARKUP. The price a buyer pays is the printer's cost plus that markup, and the split is:

    printer's cost -> the printer (it makes and ships the item)
    dev tax        -> the platform, taken from the MARKUP only, at the BUYER's tier rate (as every MercheZ sale)
    the rest       -> the designer

The dev tax is on the markup, never on the printer's cost: taxing money that goes straight to the printer would
charge the designer for a cost they do not keep. CHECKOUT IS NOT OPEN: no printer account is connected, so
`checkout_open` is False and a buy answers 503 before anything moves. The printer's costs below are ESTIMATES
(said so on every response) until the printer's own price list is read live.
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

# Estimated printer cost per item, before shipping, in cents. Replace with the printer's live list once connected.
BASE_CENTS = {"shirt": 1300, "hoodie": 2700, "towel": 2000, "bandana": 1200, "wavecap": 1200, "durag": 1200, "baseballcap": 1800, "mug": 900, "phonecase": 1300, "sticker": 300, "poster": 1200, "buckethat": 1800, "beanie": 1400, "tote": 1400}
LABELS = {"shirt": "T-shirt", "hoodie": "Hoodie", "towel": "Towel", "bandana": "Bandana", "wavecap": "Wave cap", "durag": "Durag", "baseballcap": "Baseball cap", "mug": "Mug", "phonecase": "Phone case", "sticker": "Sticker", "poster": "Poster", "buckethat": "Bucket hat", "beanie": "Beanie", "tote": "Tote bag"}
MAX_MARKUP = 10000        # $100 over cost
MAX_IMAGE_BYTES = 8 * 1024 * 1024
PER_DESIGNER = 200
CHECKOUT_OPEN = False
ESTIMATE_NOTE = "The printer's cost is an estimate before shipping until a printer is connected; checkout opens then."
CLOSED_NOTE = "Checkout isn't open yet — no printer is connected, so nothing can be bought and nothing was charged."
OWN_ART_RULE = "Only your own art: no team or brand logos, characters or other people's work."


def split(product, markup_cents, rate):
    base = BASE_CENTS[product]
    dev, designer = split_cents(markup_cents, rate)
    return {"price": base + markup_cents, "printer": base, "dev_tax": dev, "designer": designer}


def designer_range(product, markup_cents):
    """What the designer keeps, lowest to highest: the tax depends on who buys."""
    rates = [DEV_TAX[t] for t in (TIER_FREE, TIER_PREMIUM, TIER_STATZ)]
    keeps = [split(product, markup_cents, r)["designer"] for r in rates]
    return {"min": min(keeps), "max": max(keeps)}


def _dict(d, request):
    rate = rate_for(request.user)
    out = {"id": d.id, "designer": d.designer.username, "product": d.product, "product_label": LABELS.get(d.product, d.product),
           "color": d.color, "title": d.title, "image": request.build_absolute_uri(d.image.url) if d.image else "",
           "markup_cents": d.markup_cents, "mine": d.designer_id == request.user.id,
           "split": split(d.product, d.markup_cents, rate)}
    if out["mine"]:
        out["designer_keeps"] = designer_range(d.product, d.markup_cents)
    return out


def _meta():
    return {"base_cents": BASE_CENTS, "labels": LABELS, "max_markup_cents": MAX_MARKUP, "checkout_open": CHECKOUT_OPEN,
            "estimate_note": ESTIMATE_NOTE, "closed_note": CLOSED_NOTE, "own_art_rule": OWN_ART_RULE,
            "dev_tax": {"free": DEV_TAX[TIER_FREE], "premium": DEV_TAX[TIER_PREMIUM], "statz": DEV_TAX[TIER_STATZ]},
            "split_rule": "Buyer pays the printer's cost plus your markup. The printer gets its cost; the dev tax comes out of "
                          "your markup at the buyer's plan rate; you keep the rest."}


class ShopView(APIView):
    """GET shops (?designer=<username>, ?mine=1); POST lists a design (multipart: image, product, color, title,
    markup_cents, own_art)."""

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
        if str(d.get("own_art", "")).lower() not in ("1", "true", "yes"):
            return Response({"detail": OWN_ART_RULE + " Tick that the design is yours to list it."}, status=status.HTTP_400_BAD_REQUEST)
        title = str(d.get("title", "")).strip()[:120]
        if not title:
            return Response({"detail": "Give the design a name."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            markup = int(d.get("markup_cents"))
        except (TypeError, ValueError):
            return Response({"detail": "Set your markup in cents."}, status=status.HTTP_400_BAD_REQUEST)
        if not 0 <= markup <= MAX_MARKUP:
            return Response({"detail": f"Your markup can be $0 to ${MAX_MARKUP // 100}."}, status=status.HTTP_400_BAD_REQUEST)
        img = request.FILES.get("image")
        if not img or not str(getattr(img, "content_type", "")).startswith("image/") or img.size > MAX_IMAGE_BYTES:
            return Response({"detail": "Add the design's picture (an image under 8 MB)."}, status=status.HTTP_400_BAD_REQUEST)
        if PrintDesign.objects.filter(designer=request.user, active=True).count() >= PER_DESIGNER:
            return Response({"detail": f"A shop holds {PER_DESIGNER} designs. Remove one to add another."}, status=status.HTTP_400_BAD_REQUEST)
        color = str(d.get("color", "#111111"))
        if not (len(color) == 7 and color.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in color[1:])):
            color = "#111111"
        pd = PrintDesign.objects.create(designer=request.user, product=product, color=color, title=title,
                                        image=img, markup_cents=markup, own_art=True)
        return Response({"design": _dict(pd, request), **_meta()}, status=status.HTTP_201_CREATED)


class ShopDesignView(APIView):
    """PATCH your own design's markup/title; DELETE takes it out of your shop."""

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser]

    def _mine(self, request, pk):
        return PrintDesign.objects.filter(pk=pk, designer=request.user, active=True).first()

    def patch(self, request, pk):
        pd = self._mine(request, pk)
        if not pd:
            return Response({"detail": "Not one of your designs."}, status=status.HTTP_404_NOT_FOUND)
        if "markup_cents" in request.data:
            try:
                m = int(request.data["markup_cents"])
            except (TypeError, ValueError):
                return Response({"detail": "Set your markup in cents."}, status=status.HTTP_400_BAD_REQUEST)
            if not 0 <= m <= MAX_MARKUP:
                return Response({"detail": f"Your markup can be $0 to ${MAX_MARKUP // 100}."}, status=status.HTTP_400_BAD_REQUEST)
            pd.markup_cents = m
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
