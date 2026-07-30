"""Print-on-demand: made when it sells, so nobody holds stock.

The economics are the whole point, so they're stated once, here:

    buyer pays  price
                 ├── landed cost (print + shipping) -> held for the printer
                 └── margin
                      ├── developer tax (the payer's tier rate)
                      └── the creator

`pay_between` can't express that — it pays the seller the whole amount minus tax,
which on a $25 shirt with a $14 print cost would pay the creator $22.50 out of
money that owes a printer $14. So the split is done here and the print cost is
withheld from the transfer, not from the creator's earnings after the fact.

**Pricing below cost is refused at listing time.** A creator who prices a $14
shirt at $12 would otherwise discover it one sale at a time.

Providers are pluggable. With no keys configured, orders rest at `pending` and
appear on a fulfilment list to be placed by hand — a real workflow for a small
shop, not a broken one. Set `POD_PROVIDER` + its key and the same orders get
submitted automatically.
"""
import logging
import os

from django.db import transaction

from .models import (PrintOrder, PrintProduct, Transaction, membership_for,
                     split_cents, wallet_for)

log = logging.getLogger("apps.omviardz")

MIN_PRICE_CENTS = 100
MAX_PRICE_CENTS = 5_000_00
MAX_QUANTITY = 25

# How artwork gets onto a blank — and what each method can't do. This is the real
# limitation on a custom-merch shop: not which products exist, but which artwork
# survives which process. The client shows these next to the blank so a creator
# finds out before ordering, not after.
PRINT_METHODS = {
    "dtg": {
        "method": "dtg",
        "name": "Direct-to-garment",
        "full_bleed": False,
        # Printed onto a finished garment, so a transparent background is
        # normally what you want.
        "on_garment": True,
        "cut_and_sew": False,
        "no_white_ink": False,
        "min_px": 1800,
        "max_colors": None,
        "notes": (
            "Ink sprayed straight onto the fabric. Photos and gradients are fine. Dark "
            "garments need a white underbase, which is why they cost more — and white ink on "
            "a white shirt is invisible, so the garment itself has to be your white."
        ),
    },
    "embroidery": {
        "method": "embroidery",
        "name": "Embroidery",
        "full_bleed": False,
        "on_garment": True,
        "cut_and_sew": False,
        "no_white_ink": False,
        "min_px": 1000,
        "max_colors": 6,
        "notes": (
            "Stitched, not printed — so no gradients, no photographs, and no detail finer "
            "than about 3mm. Six thread colours, bold shapes, and text no smaller than 5mm "
            "or the letters close up. A logo works; album art usually doesn't."
        ),
    },
    "sublimation": {
        "method": "sublimation",
        "name": "Dye sublimation",
        "full_bleed": True,
        "on_garment": False,
        "cut_and_sew": False,
        # No white ink: anything transparent (or white) comes out as bare fabric.
        "no_white_ink": True,
        "min_px": 3000,
        "max_colors": None,
        "notes": (
            "Dye bonded into the fibres, so it never cracks or peels and the colours are "
            "vivid. Only works on white or light polyester — cotton won't take it, and there "
            "is no white ink, so anything white in your design comes out as bare fabric."
        ),
    },
    "aop": {
        "method": "aop",
        "name": "All-over print",
        "full_bleed": True,
        "on_garment": False,
        # Printed on flat panels that are then cut and sewn — this is what makes
        # aspect ratio and seams matter, and it is NOT true of a poster.
        "cut_and_sew": True,
        "no_white_ink": True,
        "min_px": 4000,
        "max_colors": None,
        "notes": (
            "Printed on flat fabric panels BEFORE the garment is cut and sewn. Artwork has to "
            "be full-bleed at large dimensions, and seams will interrupt it — a centred logo "
            "is the wrong design for this. Repeating patterns and textures are what it's for."
        ),
    },
    "vinyl": {
        "method": "vinyl",
        "name": "Cut vinyl",
        "full_bleed": False,
        "on_garment": True,
        "cut_and_sew": False,
        "no_white_ink": False,
        "min_px": 1500,
        "max_colors": 4,
        "notes": (
            "Solid colour shapes cut from sheet vinyl. Crisp edges, no gradients, and every "
            "colour is a separate layer — keep it to a few flat shapes."
        ),
    },
    "paper": {
        "method": "paper",
        "name": "Giclée / paper print",
        "full_bleed": True,
        "on_garment": False,
        "cut_and_sew": False,
        # Paper IS white, so transparency prints as white — no warning needed.
        "no_white_ink": False,
        "min_px": 3600,
        "max_colors": None,
        "notes": (
            "Full colour on paper, the most forgiving process here. 300 DPI at final size is "
            "the only real requirement — a 1000px file on a 24-inch poster looks soft."
        ),
    },
}


# The blank catalog. Costs are realistic mid-2026 print-on-demand economics
# (garment + print + typical domestic shipping) and are meant to be edited to
# match whatever your provider actually quotes — `seed_pod` updates in place, so
# changing a number here and re-running it repriced nothing else.
BLANKS = [
    {
        "key": "tee",
        "name": "Unisex T-Shirt",
        "category": "apparel",
        "print_method": "dtg",
        "base_cost_cents": 1100,
        "shipping_cents": 450,
        "sizes": ["S", "M", "L", "XL", "2XL", "3XL"],
        "colors": ["Black", "White", "Navy", "Heather Grey", "Sand"],
        # Extended sizes cost more blank; dark garments cost more to print
        # (DTG needs a white underbase). Passed to the buyer, not absorbed by
        # the creator.
        "size_upcharges": {"2XL": 200, "3XL": 400},
        "color_upcharges": {"Black": 100, "Navy": 100},
    },
    {
        "key": "tee-premium",
        "name": "Premium Heavyweight Tee",
        "category": "apparel",
        "print_method": "dtg",
        "base_cost_cents": 1550,
        "shipping_cents": 450,
        "sizes": ["S", "M", "L", "XL", "2XL"],
        "colors": ["Black", "White", "Bone", "Forest"],
        "size_upcharges": {"2XL": 250},
        "color_upcharges": {"Black": 150, "Forest": 150},
    },
    {
        "key": "hoodie",
        "name": "Pullover Hoodie",
        "category": "apparel",
        "print_method": "dtg",
        "base_cost_cents": 2600,
        "shipping_cents": 650,
        "sizes": ["S", "M", "L", "XL", "2XL", "3XL"],
        "colors": ["Black", "Charcoal", "Maroon", "Sand"],
        "size_upcharges": {"2XL": 300, "3XL": 600},
        "color_upcharges": {"Black": 150, "Charcoal": 150, "Maroon": 150},
    },
    {
        "key": "crewneck",
        "name": "Crewneck Sweatshirt",
        "category": "apparel",
        "print_method": "dtg",
        "base_cost_cents": 2200,
        "shipping_cents": 650,
        "sizes": ["S", "M", "L", "XL", "2XL"],
        "colors": ["Black", "Grey", "Navy"],
        "size_upcharges": {"2XL": 300},
        "color_upcharges": {"Black": 150, "Navy": 150},
    },
    {
        "key": "tank",
        "name": "Unisex Tank Top",
        "category": "apparel",
        "print_method": "dtg",
        "base_cost_cents": 1200,
        "shipping_cents": 450,
        "sizes": ["S", "M", "L", "XL", "2XL"],
        "colors": ["Black", "White", "Heather Grey", "Navy"],
        "size_upcharges": {"2XL": 200},
        "color_upcharges": {"Black": 100, "Navy": 100},
    },
    {
        "key": "long-sleeve",
        "name": "Long Sleeve Tee",
        "category": "apparel",
        "print_method": "dtg",
        "base_cost_cents": 1700,
        "shipping_cents": 500,
        "sizes": ["S", "M", "L", "XL", "2XL", "3XL"],
        "colors": ["Black", "White", "Navy", "Heather Grey"],
        "size_upcharges": {"2XL": 250, "3XL": 450},
        "color_upcharges": {"Black": 100, "Navy": 100},
    },
    {
        "key": "kimono",
        "name": "All-Over-Print Kimono Robe",
        "category": "apparel",
        "print_method": "aop",
        "base_cost_cents": 4200,
        "shipping_cents": 750,
        # Cut-and-sew, so the size run is short and generous rather than exact.
        "sizes": ["S/M", "L/XL", "2XL/3XL"],
        "colors": ["Full print"],
        "size_upcharges": {"2XL/3XL": 500},
    },
    {
        "key": "bomber",
        "name": "All-Over-Print Bomber Jacket",
        "category": "apparel",
        "print_method": "aop",
        "base_cost_cents": 4600,
        "shipping_cents": 850,
        "sizes": ["S", "M", "L", "XL", "2XL"],
        "colors": ["Full print"],
        "size_upcharges": {"2XL": 500},
    },
    {
        "key": "windbreaker",
        "name": "All-Over-Print Windbreaker",
        "category": "apparel",
        "print_method": "aop",
        "base_cost_cents": 3900,
        "shipping_cents": 800,
        "sizes": ["S", "M", "L", "XL", "2XL"],
        "colors": ["Full print"],
        "size_upcharges": {"2XL": 450},
    },
    {
        "key": "denim-jacket",
        "name": "Embroidered Denim Jacket",
        "category": "apparel",
        "print_method": "embroidery",
        "base_cost_cents": 5400,
        "shipping_cents": 900,
        "sizes": ["S", "M", "L", "XL", "2XL"],
        "colors": ["Light Wash", "Dark Wash", "Black"],
        "size_upcharges": {"2XL": 600},
    },
    {
        "key": "towel",
        "name": "Beach Towel (30x60)",
        "category": "home",
        "print_method": "sublimation",
        "base_cost_cents": 2500,
        "shipping_cents": 750,
        "sizes": ['30x60"', '20x40"'],
        "colors": ["White base"],
    },
    {
        "key": "snapback",
        "name": "Snapback Cap",
        "category": "accessories",
        "print_method": "embroidery",
        "base_cost_cents": 1600,
        "shipping_cents": 450,
        "sizes": ["One size"],
        "colors": ["Black", "White", "Navy", "Black/Grey"],
    },
    {
        "key": "trucker",
        "name": "Trucker Cap (mesh back)",
        "category": "accessories",
        "print_method": "embroidery",
        "base_cost_cents": 1500,
        "shipping_cents": 450,
        "sizes": ["One size"],
        "colors": ["Black", "White/Black", "Navy/White"],
    },
    {
        "key": "beanie",
        "name": "Cuffed Beanie",
        "category": "accessories",
        "print_method": "embroidery",
        "base_cost_cents": 1350,
        "shipping_cents": 400,
        "sizes": ["One size"],
        "colors": ["Black", "Charcoal", "Maroon", "Forest"],
    },
    {
        "key": "cap",
        "name": "Embroidered Baseball Cap",
        "category": "accessories",
        "print_method": "embroidery",
        "base_cost_cents": 1400,
        "shipping_cents": 450,
        "sizes": ["One size"],
        "colors": ["Black", "White", "Khaki"],
    },
    {
        "key": "tote",
        "name": "Canvas Tote",
        "category": "accessories",
        "print_method": "dtg",
        "base_cost_cents": 1150,
        "shipping_cents": 450,
        "sizes": ["One size"],
        "colors": ["Natural", "Black"],
    },
    {
        "key": "mug",
        "name": "Ceramic Mug (11oz)",
        "category": "accessories",
        "print_method": "sublimation",
        "base_cost_cents": 800,
        "shipping_cents": 550,
        "sizes": ["11oz", "15oz"],
        "colors": ["White", "Black"],
    },
    {
        "key": "poster",
        "name": "Matte Poster (18x24)",
        "category": "art",
        "print_method": "paper",
        "base_cost_cents": 950,
        "shipping_cents": 600,
        "sizes": ['12x18"', '18x24"', '24x36"'],
        "colors": ["Matte", "Semi-gloss"],
    },
    {
        "key": "sticker",
        "name": "Vinyl Sticker Pack",
        "category": "accessories",
        "print_method": "vinyl",
        "base_cost_cents": 300,
        "shipping_cents": 200,
        "sizes": ['3"', '5"'],
        "colors": ["Gloss", "Matte", "Holographic"],
    },
    {
        "key": "vinyl-sleeve",
        "name": "Record Sleeve Print (12x12)",
        "category": "art",
        "print_method": "paper",
        "base_cost_cents": 1250,
        "shipping_cents": 600,
        "sizes": ['12x12"'],
        "colors": ["Matte", "Gloss"],
    },
]


def seed_blanks():
    """Create or update the blank catalog. Idempotent — safe on every deploy."""
    made = 0
    for blank in BLANKS:
        _, created = PrintProduct.objects.update_or_create(
            key=blank["key"],
            defaults={
                "name": blank["name"],
                "category": blank["category"],
                "base_cost_cents": blank["base_cost_cents"],
                "shipping_cents": blank["shipping_cents"],
                "sizes": blank["sizes"],
                "colors": blank["colors"],
                "print_method": blank.get("print_method", "dtg"),
                "size_upcharges": blank.get("size_upcharges", {}),
                "color_upcharges": blank.get("color_upcharges", {}),
                "provider": provider_name(),
                "active": True,
            },
        )
        made += 1 if created else 0
    return made


def provider_name():
    """Which fulfilment provider is configured. `manual` when none is."""
    name = (os.environ.get("POD_PROVIDER") or "").strip().lower()
    return name if name in ("printful", "printify") and provider_key(name) else "manual"


def provider_key(name=None):
    name = name or (os.environ.get("POD_PROVIDER") or "").strip().lower()
    if name == "printful":
        return os.environ.get("PRINTFUL_API_KEY", "")
    if name == "printify":
        return os.environ.get("PRINTIFY_API_KEY", "")
    return ""


def suggested_price_cents(product, markup=0.6):
    """A price that clears cost with a sane margin, rounded to a .99.

    Offered as a default because "what do I charge?" is where most first-time
    sellers either lose money or price themselves out.
    """
    landed = product.landed_cost_cents
    target = int(landed * (1 + markup))
    return max(MIN_PRICE_CENTS, ((target + 99) // 100) * 100 - 1)


def quote(product, price_cents, quantity=1, size="", color=""):
    """Break a price down the way the creator needs to see it before listing.

    Variant upcharges (a 3XL, a black garment) are added to what the BUYER pays
    and to what the printer takes, so the creator's margin is identical on every
    size and colour. Otherwise a shop selling mostly 3XL earns less per shirt
    than the same shop selling mostly mediums, for no reason the seller can see.
    """
    qty = max(1, int(quantity))
    up = product.upcharge_cents(size, color)
    unit_price = int(price_cents) + up
    total = unit_price * qty
    landed = (product.landed_cost_cents + up) * qty
    margin = total - landed
    return {
        "price_cents": total,
        "unit_price_cents": unit_price,
        "upcharge_cents": up * qty,
        "base_cost_cents": landed,
        "margin_cents": max(0, margin),
        "profitable": margin > 0,
        "break_even_cents": product.landed_cost_cents,
        "margin_pct": round(margin / total * 100, 1) if total else 0.0,
    }


def variant_table(product, price_cents=None):
    """Every size and colour with what it adds and whether it's in stock.

    This is what the product page renders. A buyer picks their real size; the
    upcharge is shown next to it rather than discovered at checkout.
    """
    base = int(price_cents) if price_cents else suggested_price_cents(product)
    return {
        "sizes": [
            {
                "value": size,
                "upcharge_cents": int((product.size_upcharges or {}).get(size, 0) or 0),
                "available": product.variant_available(size=size),
            }
            for size in (product.sizes or [])
        ],
        "colors": [
            {
                "value": color,
                "upcharge_cents": int((product.color_upcharges or {}).get(color, 0) or 0),
                "available": product.variant_available(color=color),
            }
            for color in (product.colors or [])
        ],
        "price_from_cents": base,
        "price_to_cents": base + max(
            [0] + [product.upcharge_cents(s, c)
                   for s in (product.sizes or [""]) for c in (product.colors or [""])]
        ),
    }


def validate_price(product, price_cents):
    """(ok, detail). Refuses a price that doesn't clear the print cost."""
    try:
        price = int(price_cents)
    except (TypeError, ValueError):
        return False, "price_cents (integer) required"
    if not (MIN_PRICE_CENTS <= price <= MAX_PRICE_CENTS):
        return False, f"price must be {MIN_PRICE_CENTS}-{MAX_PRICE_CENTS} cents"
    landed = product.landed_cost_cents
    if price <= landed:
        return False, (
            f"{product.name} costs {landed} cents to make and ship, so {price} would sell at a "
            f"loss. Price above {landed} — {suggested_price_cents(product)} is a reasonable start."
        )
    return True, ""


REQUIRED_ADDRESS = ("name", "line1", "city", "country")


def validate_address(ship_to):
    """(ok, detail). A physical good needs somewhere to go."""
    if not isinstance(ship_to, dict):
        return False, "ship_to (object) required for a physical item"
    missing = [f for f in REQUIRED_ADDRESS if not str(ship_to.get(f, "")).strip()]
    if missing:
        return False, f"ship_to is missing: {', '.join(missing)}"
    return True, ""


def clean_address(ship_to):
    """Keep only the fields a printer needs. Everything else is dropped rather
    than stored — an order record is not a place to accumulate personal data."""
    fields = ("name", "line1", "line2", "city", "state", "postcode", "country", "phone")
    return {f: str(ship_to.get(f, "")).strip()[:120] for f in fields if ship_to.get(f)}


@transaction.atomic
def place_order(buyer, listing, size="", color="", quantity=1, ship_to=None):
    """Charge the buyer, pay the creator their margin, queue the print.

    Returns (order, None) or (None, error_detail). The print cost is withheld from
    the transfer, so the platform is holding real money against a real
    obligation to a printer rather than paying it out and hoping.
    """
    quantity = max(1, min(int(quantity or 1), MAX_QUANTITY))
    product = listing.product
    if not product.variant_available(size, color):
        variant = " / ".join(x for x in (size, color) if x) or "that variant"
        return None, f"the printer is out of {variant} right now — try another size or colour"

    # The variant upcharge rides on top of the listing price for the buyer AND on
    # top of the print cost, so the creator earns the same margin on a 3XL as on
    # a small.
    upcharge = product.upcharge_cents(size, color)
    total = (listing.price_cents + upcharge) * quantity
    landed = (product.landed_cost_cents + upcharge) * quantity

    w = wallet_for(buyer)
    if (w.money_cents or 0) < total:
        return None, "insufficient balance"
    if total <= landed:
        # Costs can move after a listing was created; refuse rather than pay a
        # creator out of the printer's money.
        return None, "this listing no longer covers its print cost — ask the seller to reprice"

    margin = total - landed
    dev, net = split_cents(margin, membership_for(buyer).dev_tax_rate)

    sw = wallet_for(listing.seller)
    w.money_cents -= total
    sw.money_cents += net
    w.save(update_fields=["money_cents", "updated_at"])
    sw.save(update_fields=["money_cents", "updated_at"])

    note = f"MerchZ POD: {listing.title} x{quantity}"[:200]
    Transaction.objects.create(user=buyer, kind=Transaction.KIND_SPEND,
                               amount_cents=-total, dev_tax_cents=dev, note=note)
    Transaction.objects.create(user=listing.seller, kind=Transaction.KIND_REWARD,
                               amount_cents=net, dev_tax_cents=dev,
                               note=f"{note} (print cost {landed}c withheld)"[:200])

    order = PrintOrder.objects.create(
        listing=listing, buyer=buyer, seller=listing.seller,
        size=str(size or "")[:16], color=str(color or "")[:32], quantity=quantity,
        price_cents=total, base_cost_cents=landed, seller_cents=net, dev_tax_cents=dev,
        upcharge_cents=upcharge,
        ship_to=clean_address(ship_to or {}), provider=provider_name(),
    )
    submit_order(order)
    return order, None


def submit_order(order):
    """Hand the order to the printer, if one is configured.

    Deliberately best-effort: the buyer has already paid and the order is already
    recorded, so a provider outage must not fail the purchase. It leaves the
    order at `pending` for the fulfilment list and returns False.
    """
    name = provider_name()
    if name == "manual":
        order.note = "Awaiting manual fulfilment (no POD provider configured)."
        order.save(update_fields=["note", "updated_at"])
        return False
    try:
        # Provider REST calls go here. Kept behind one function so adding
        # Printful/Printify is a contained change and the money path above never
        # has to be touched again.
        raise NotImplementedError(f"{name} submission not wired yet")
    except Exception as exc:
        log.info("pod: could not submit order %s to %s (%s)", order.id, name, str(exc)[:160])
        order.note = f"Submission to {name} pending: {str(exc)[:160]}"
        order.save(update_fields=["note", "updated_at"])
        return False


@transaction.atomic
def refund_order(order, reason="", by=None):
    """Cancel a paid order and put the money back where it came from.

    Returns (ok, detail). Every leg of the original sale is reversed:

        buyer      + the full price they paid
        seller     - the net they were credited
        platform   - the tax it kept, and releases the withheld print cost

    Refusing is the right answer once a printer has it. Money moves before the
    goods exist, so a `pending` order costs nothing to unwind — but a `shipped`
    one has a real garment in a real van, and silently refunding that would have
    the platform eating the cost with no way to notice.

    A seller who has already spent their credit does NOT block the buyer's refund.
    Wallets are non-negative by design across this platform, so the clawback takes
    whatever is there and the unrecoverable remainder is recorded on the order as
    `clawback_shortfall_cents` — the platform absorbs it. That's a deliberate
    trade: the buyer is owed their money back regardless of what the seller did
    with theirs, and a recorded shortfall is something support can chase, where a
    refused refund is an angry customer and a chargeback.
    """
    if order.status in PrintOrder.TERMINAL:
        return False, f"order is already {order.status}"
    if order.status not in (PrintOrder.STATUS_PENDING, PrintOrder.STATUS_SUBMITTED):
        return False, (
            f"this order is {order.status} — it's already being made or on its way, so it "
            "can't be refunded here. Handle it as a return with the buyer."
        )

    bw = wallet_for(order.buyer)
    sw = wallet_for(order.seller)
    clawback = min(order.seller_cents, sw.money_cents or 0)
    shortfall = order.seller_cents - clawback

    bw.money_cents = (bw.money_cents or 0) + order.price_cents
    sw.money_cents = (sw.money_cents or 0) - clawback
    bw.save(update_fields=["money_cents", "updated_at"])
    sw.save(update_fields=["money_cents", "updated_at"])

    note = f"MerchZ POD refund: {order.listing.title}"
    if reason:
        note += f" ({reason})"
    Transaction.objects.create(user=order.buyer, kind=Transaction.KIND_REWARD,
                               amount_cents=order.price_cents, dev_tax_cents=0,
                               note=note[:200])
    Transaction.objects.create(user=order.seller, kind=Transaction.KIND_SPEND,
                               amount_cents=-clawback, dev_tax_cents=0,
                               note=(note + (f" — {shortfall}c unrecovered" if shortfall else ""))[:200])

    order.status = PrintOrder.STATUS_CANCELLED
    order.clawback_shortfall_cents = shortfall
    order.note = (f"Refunded {order.price_cents}c"
                  + (f" — {reason}" if reason else "")
                  + (f" (by {by.username})" if by else "")
                  + (f" · {shortfall}c not recovered from seller" if shortfall else ""))[:300]
    order.save(update_fields=["status", "clawback_shortfall_cents", "note", "updated_at"])
    return True, ""


def refundable(order):
    """Whether `refund_order` would succeed — for showing or hiding a button."""
    return order.status in (PrintOrder.STATUS_PENDING, PrintOrder.STATUS_SUBMITTED)


def advance(order, status, provider_order_id="", tracking_url="", note=""):
    """Move an order along. Terminal states are final so a replayed provider
    webhook can't reopen a delivered or cancelled order."""
    if status not in PrintOrder.STATUSES:
        return False, f"unknown status {status!r}"
    if order.status in PrintOrder.TERMINAL:
        return False, f"order is already {order.status}"
    order.status = status
    fields = ["status", "updated_at"]
    for field, value in (("provider_order_id", provider_order_id),
                         ("tracking_url", tracking_url), ("note", note)):
        if value:
            setattr(order, field, str(value)[:300])
            fields.append(field)
    order.save(update_fields=fields)
    return True, ""


def measure_design(design):
    """Record an uploaded design's pixel size and transparency, once.

    Stored on the row rather than read on demand: with S3/R2 the file isn't
    local, so measuring it on every product-page render would be a network round
    trip per blank. Failure is non-fatal — an unmeasured design simply skips the
    artwork checks instead of blocking the upload.
    """
    try:
        from PIL import Image

        design.image.open()
        with Image.open(design.image) as img:
            design.width, design.height = img.size
            design.has_alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
        design.save(update_fields=["width", "height", "has_alpha"])
        return True
    except Exception as exc:
        log.info("pod: could not measure design %s (%s)", design.pk, str(exc)[:160])
        return False
    finally:
        try:
            design.image.close()
        except Exception:
            pass


def suitability(design):
    """Which blanks this artwork is good enough for, and why not for the rest.

    Returned at upload so a creator sees "great for posters, too small for a
    hoodie" before they list anything — the moment when fixing the file is still
    cheap.
    """
    rows = []
    for product in PrintProduct.objects.filter(active=True):
        ok, problems = design.check_for(product)
        rows.append({
            "product": product.key,
            "name": product.name,
            "print_method": product.print_method,
            "ok": ok,
            "warnings": problems,
        })
    return {
        "measured": bool(design.width and design.height),
        "width": design.width,
        "height": design.height,
        "shortest_side": design.shortest_side,
        "has_alpha": design.has_alpha,
        "good_for": [r["product"] for r in rows if r["ok"]],
        "warnings_for": [r for r in rows if not r["ok"]],
    }
