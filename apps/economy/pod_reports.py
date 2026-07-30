"""Seller reporting for print-on-demand: invoices, statements, and what's selling.

Three different questions, three shapes:

* **Invoice** — one order. What did this specific person buy, what did it cost to
  make, what did I earn. A record to keep or send.
* **Sales report** — what's selling. Ranked by listing, product, size and colour,
  because "which of my shirts moves, and in which size" is the question that
  changes what a creator makes next.
* **Statement** — one month. Gross, print costs withheld, platform tax, net paid.
  The thing you hand an accountant.

All three read the figures snapshotted on `PrintOrder` at sale time, never
recomputed from the current listing — a creator who repriced last week must not
see last month's earnings change.

⚠️ These are **sales records, not tax invoices.** No sales tax or VAT is
calculated, collected, or remitted anywhere in this system, and the documents
carry no tax registration number. A seller with a tax obligation has to handle it
themselves; see MERCH_POD.md.
"""
from collections import defaultdict
from datetime import date, datetime, time

from django.utils import timezone

from .models import PrintOrder

# Orders that never became a sale. Excluded from revenue, still listed, because a
# report that hides cancellations makes them impossible to notice.
VOID_STATUSES = {PrintOrder.STATUS_CANCELLED, PrintOrder.STATUS_FAILED}


def invoice_number(order):
    """Stable, human-quotable, and derivable from the id — no counter to keep."""
    return f"MCZ-POD-{order.id:06d}"


def statement_number(user, year, month):
    return f"MCZ-STMT-{user.id}-{year:04d}{month:02d}"


def _money(cents):
    return round((cents or 0) / 100, 2)


def parse_day(raw, end=False):
    """`YYYY-MM-DD` to an aware datetime, or None. `end` takes the whole day."""
    try:
        d = date.fromisoformat(str(raw).strip())
    except (TypeError, ValueError):
        return None
    moment = datetime.combine(d, time.max if end else time.min)
    return timezone.make_aware(moment) if timezone.is_naive(moment) else moment


def can_view(order, user):
    """Buyer, seller, and the platform owner. Nobody else — an invoice carries a
    shipping address."""
    from .views import is_owner

    return (order.seller_id == user.id or order.buyer_id == user.id
            or is_owner(user))


def invoice(order, viewer=None):
    """One order as an invoice document.

    `lines` is deliberately in document shape (description / quantity / unit /
    amount) so a client can render or print it without doing arithmetic — and so
    the arithmetic is done once, here, where it's tested.
    """
    listing, product = order.listing, order.listing.product
    unit = order.price_cents // max(1, order.quantity)
    variant = " / ".join(x for x in (order.size, order.color) if x)

    lines = [{
        "description": listing.title,
        "detail": f"{product.name}{f' · {variant}' if variant else ''}",
        "quantity": order.quantity,
        "unit_cents": unit,
        "amount_cents": order.price_cents,
    }]
    if order.upcharge_cents:
        # Broken out rather than folded in, because a buyer seeing "$30" on a
        # "$25" shirt deserves to see why.
        lines.append({
            "description": f"Size/colour upcharge ({variant})",
            "detail": "printer's cost for this variant",
            "quantity": order.quantity,
            "unit_cents": order.upcharge_cents,
            "amount_cents": order.upcharge_cents * order.quantity,
            "included_above": True,
        })

    doc = {
        "number": invoice_number(order),
        "order_id": order.id,
        "issued_at": order.created_at,
        "status": order.status,
        "made_to_order": True,
        "seller": order.seller.username,
        "buyer": order.buyer.username,
        "lines": lines,
        "totals": {
            "gross_cents": order.price_cents,
            "print_cost_cents": order.base_cost_cents,
            "platform_fee_cents": order.dev_tax_cents,
            "seller_net_cents": order.seller_cents,
            "gross": _money(order.price_cents),
            "print_cost": _money(order.base_cost_cents),
            "platform_fee": _money(order.dev_tax_cents),
            "seller_net": _money(order.seller_cents),
        },
        "fulfilment": {
            "provider": order.provider,
            "provider_order_id": order.provider_order_id,
            "tracking_url": order.tracking_url,
            "note": order.note,
        },
        # Stated on the document itself, not just in the docs, so nobody files it
        # as something it isn't.
        "tax_note": "Sales record only — no sales tax or VAT calculated or collected.",
    }
    # A shipping address only travels to the people entitled to it.
    if viewer is None or can_view(order, viewer):
        doc["ship_to"] = order.ship_to
    return doc


def _bucket_totals():
    return {"units": 0, "orders": 0, "gross_cents": 0, "print_cost_cents": 0,
            "fee_cents": 0, "net_cents": 0}


def _add(bucket, order):
    bucket["orders"] += 1
    bucket["units"] += order.quantity
    bucket["gross_cents"] += order.price_cents
    bucket["print_cost_cents"] += order.base_cost_cents
    bucket["fee_cents"] += order.dev_tax_cents
    bucket["net_cents"] += order.seller_cents


def _finish(bucket, **extra):
    out = {**extra, **bucket}
    out["gross"] = _money(bucket["gross_cents"])
    out["net"] = _money(bucket["net_cents"])
    return out


def sales_report(user, start=None, end=None):
    """What's selling, for one seller.

    Ranked by revenue rather than units on purpose: ten stickers and one hoodie
    are not the same result, and a creator deciding what to make next should be
    looking at money.
    """
    qs = PrintOrder.objects.filter(seller=user).select_related(
        "listing", "listing__product", "buyer")
    if start:
        qs = qs.filter(created_at__gte=start)
    if end:
        qs = qs.filter(created_at__lte=end)
    orders = list(qs)

    live = [o for o in orders if o.status not in VOID_STATUSES]
    totals = _bucket_totals()
    by_listing, by_product, by_size, by_color, by_month, by_status = (
        defaultdict(_bucket_totals), defaultdict(_bucket_totals),
        defaultdict(_bucket_totals), defaultdict(_bucket_totals),
        defaultdict(_bucket_totals), defaultdict(int),
    )
    titles, product_names = {}, {}

    for o in orders:
        by_status[o.status] += 1
    for o in live:
        _add(totals, o)
        _add(by_listing[o.listing_id], o)
        _add(by_product[o.listing.product.key], o)
        _add(by_size[o.size or "—"], o)
        _add(by_color[o.color or "—"], o)
        _add(by_month[o.created_at.strftime("%Y-%m")], o)
        titles[o.listing_id] = o.listing.title
        product_names[o.listing.product.key] = o.listing.product.name

    def ranked(buckets, key_name, labels=None):
        rows = [_finish(b, **{key_name: k},
                        **({"name": labels[k]} if labels else {}))
                for k, b in buckets.items()]
        return sorted(rows, key=lambda r: -r["gross_cents"])

    voided = [o for o in orders if o.status in VOID_STATUSES]
    return {
        "seller": user.username,
        "from": start,
        "to": end,
        "totals": _finish(totals),
        "best_sellers": ranked(by_listing, "listing_id", titles),
        "by_product": ranked(by_product, "product", product_names),
        "by_size": ranked(by_size, "size"),
        "by_color": ranked(by_color, "color"),
        # Chronological, not ranked — this one is a trend line.
        "by_month": sorted(
            (_finish(b, month=m) for m, b in by_month.items()),
            key=lambda r: r["month"],
        ),
        "by_status": dict(by_status),
        "cancelled": {
            "orders": len(voided),
            "gross_cents": sum(o.price_cents for o in voided),
        },
        "awaiting_fulfilment": sum(
            1 for o in orders if o.status == PrintOrder.STATUS_PENDING),
        "tax_note": "Sales record only — no sales tax or VAT calculated or collected.",
    }


def statement(user, year, month):
    """One month, as the document you'd hand an accountant.

    Reconciliation is asserted rather than assumed: gross must equal print cost +
    platform fee + net for every line, and the totals must equal the sum of the
    lines. If that ever fails, the statement says so instead of quietly printing
    a number that doesn't add up.
    """
    start = parse_day(f"{year:04d}-{month:02d}-01")
    end_month, end_year = (month + 1, year) if month < 12 else (1, year + 1)
    end = parse_day(f"{end_year:04d}-{end_month:02d}-01")

    qs = PrintOrder.objects.filter(
        seller=user, created_at__gte=start, created_at__lt=end
    ).select_related("listing", "listing__product").order_by("created_at")
    orders = [o for o in qs if o.status not in VOID_STATUSES]

    totals = _bucket_totals()
    lines = []
    for o in orders:
        _add(totals, o)
        variant = " / ".join(x for x in (o.size, o.color) if x)
        lines.append({
            "date": o.created_at,
            "invoice": invoice_number(o),
            "item": o.listing.title,
            "variant": variant,
            "quantity": o.quantity,
            "gross_cents": o.price_cents,
            "print_cost_cents": o.base_cost_cents,
            "platform_fee_cents": o.dev_tax_cents,
            "net_cents": o.seller_cents,
            "status": o.status,
        })

    balanced = all(
        l["gross_cents"] == l["print_cost_cents"] + l["platform_fee_cents"] + l["net_cents"]
        for l in lines
    ) and totals["gross_cents"] == (
        totals["print_cost_cents"] + totals["fee_cents"] + totals["net_cents"]
    )

    return {
        "number": statement_number(user, year, month),
        "seller": user.username,
        "period": f"{year:04d}-{month:02d}",
        "from": start,
        "to": end,
        "lines": lines,
        "totals": _finish(totals),
        "payout_cents": totals["net_cents"],
        "payout": _money(totals["net_cents"]),
        # True unless the arithmetic disagrees with itself.
        "balanced": balanced,
        "tax_note": "Sales record only — no sales tax or VAT calculated or collected.",
    }
