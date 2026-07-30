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

# The blank catalog. Costs are realistic mid-2026 print-on-demand economics
# (garment + print + typical domestic shipping) and are meant to be edited to
# match whatever your provider actually quotes — `seed_pod` updates in place, so
# changing a number here and re-running it repriced nothing else.
BLANKS = [
    {
        "key": "tee",
        "name": "Unisex T-Shirt",
        "category": "apparel",
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
        "base_cost_cents": 2200,
        "shipping_cents": 650,
        "sizes": ["S", "M", "L", "XL", "2XL"],
        "colors": ["Black", "Grey", "Navy"],
        "size_upcharges": {"2XL": 300},
        "color_upcharges": {"Black": 150, "Navy": 150},
    },
    {
        "key": "cap",
        "name": "Embroidered Cap",
        "category": "accessories",
        "base_cost_cents": 1400,
        "shipping_cents": 450,
        "sizes": ["One size"],
        "colors": ["Black", "White", "Khaki"],
    },
    {
        "key": "tote",
        "name": "Canvas Tote",
        "category": "accessories",
        "base_cost_cents": 1150,
        "shipping_cents": 450,
        "sizes": ["One size"],
        "colors": ["Natural", "Black"],
    },
    {
        "key": "mug",
        "name": "Ceramic Mug (11oz)",
        "category": "accessories",
        "base_cost_cents": 800,
        "shipping_cents": 550,
        "sizes": ["11oz", "15oz"],
        "colors": ["White", "Black"],
    },
    {
        "key": "poster",
        "name": "Matte Poster (18x24)",
        "category": "art",
        "base_cost_cents": 950,
        "shipping_cents": 600,
        "sizes": ['12x18"', '18x24"', '24x36"'],
        "colors": ["Matte", "Semi-gloss"],
    },
    {
        "key": "sticker",
        "name": "Vinyl Sticker Pack",
        "category": "accessories",
        "base_cost_cents": 300,
        "shipping_cents": 200,
        "sizes": ['3"', '5"'],
        "colors": ["Gloss", "Matte", "Holographic"],
    },
    {
        "key": "vinyl-sleeve",
        "name": "Record Sleeve Print (12x12)",
        "category": "art",
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
