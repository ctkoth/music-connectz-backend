# MerchZ print-on-demand — made when it sells

One design, listed on as many blanks as you like, nothing produced until somebody
buys it. No stock, no upfront spend, no box of unsold shirts.

```
upload "Logo" once
   ├── Logo Tee       $25   ← three listings
   ├── Logo Hoodie    $45
   └── Logo Mug       $20
                            ← a fan buys a 3XL black tee
                              that one shirt gets printed
```

---

## Can you sell any size and colour?

Short answer: **the buyer's exact size gets printed, but the choices aren't
unlimited — they're whatever the printer stocks for that blank.**

### Sizes

Fixed per product, from the supplier's size run. A tee is S–3XL; a mug is 11oz or
15oz; a poster is one of three dimensions. There's no "any size" — a 5XL tee is
refused, with the real list returned so the UI can correct itself.

**Extended sizes cost more.** A 2XL blank costs the printer more than a medium, so
the tee carries `{"2XL": 200, "3XL": 400}` — extra cents per unit.

### Colours

Fixed per product too, and constrained by physics as well as stock:

- Only the garment colours the supplier actually stocks.
- **Dark garments cost more to print.** Direct-to-garment printing needs a white
  underbase on anything dark, which is an extra pass. Hence
  `{"Black": 100, "Navy": 100}` on the tee.
- **You can't print white on white.** A design made for a light shirt often looks
  wrong on black — that's a design decision the catalog can't make for you.

### Stock-outs

You hold no inventory, but the **printer does**, and blanks run out. `unavailable`
blocks a size (`"3XL"`), a colour (`"Sand"`), or one exact pair
(`"2XL|Navy"`) — suppliers run out at all three granularities. A blocked variant
is refused at checkout and marked unavailable in the variant table, so it can be
greyed out rather than sold and then apologised for.

### Who pays the upcharge

**The buyer.** The upcharge is added to what they pay *and* to what the printer
takes, so the creator's margin is byte-for-byte identical on every variant:

| Variant | Buyer pays | Printer gets | Creator earns |
|---|---|---|---|
| M / White | $25.00 | $15.50 | same |
| 3XL / Black | $30.00 | $20.50 | **same** |

Otherwise a shop selling mostly 3XL would quietly earn less per shirt than the
same shop selling mediums, for no reason the seller could see. A test asserts
`big.seller_cents == small.seller_cents`.

The product page gets a price range — "$25.00 – $30.00" — from
`variants.price_from_cents` / `price_to_cents`.

### Other real limits worth knowing

- **One print area per listing.** Front-only. Back and sleeve prints are separate
  costs at every provider and would need per-placement pricing.
- **Artwork quality is on you.** 300 DPI at print size or it looks soft. Nothing
  here validates resolution yet.
- **Shipping is one flat cost per blank**, folded into the landed cost.
  International shipping and multi-item basket consolidation aren't modelled — a
  two-item order pays two shipping costs.
- **No returns flow.** `cancelled` exists as a status; refunding the wallet is not
  wired to it.

---

## The money

The economics are the whole feature, so they're worth being explicit about:

```
buyer pays  price + variant upcharge
             ├── landed cost (print + shipping + upcharge) → withheld for the printer
             └── margin
                  ├── developer tax (the buyer's tier rate)
                  └── the creator
```

`pay_between` **cannot** express this — it pays the seller the whole amount minus
tax. On a $25 shirt with a $15.50 print cost that would hand the creator $22.50
out of money that owes a printer $15.50. So `pod.place_order` does the split
itself and withholds the print cost from the transfer, rather than paying it out
and hoping.

Two guards on top:

- **Listing below cost is refused**, with the break-even and a suggested price. A
  creator pricing a $15.50 shirt at $12 would otherwise find out one sale at a
  time.
- **A sale is refused if costs have risen past the price** since the listing was
  made. Better to refuse than to pay a creator out of the printer's money.

Orders snapshot every figure, so repricing a listing later can't rewrite what a
past sale paid.

---

## API

```
GET         /api/economy/pod/blanks/              catalog + costs + variants  (public)
GET  POST   /api/economy/pod/designs/             your artwork / upload
DELETE      /api/economy/pod/designs/<id>/
GET  POST   /api/economy/pod/listings/            the shop (?mine=1) / list a design
DELETE      /api/economy/pod/listings/<id>/
POST        /api/economy/pod/listings/<id>/buy/   buy it — made after
GET         /api/economY/pod/orders/              your purchases + your sales queue
POST        /api/economy/pod/orders/<id>/status/  seller moves it along
```

### Listing a design

```http
POST /api/economy/pod/listings/
{"design_id": 3, "product": "tee", "price_cents": 2500}
```

Returns the listing plus a `quote` breaking the price into cost, margin and
margin percentage.

### Buying

```http
POST /api/economy/pod/listings/12/buy/
{"size": "3XL", "color": "Black", "quantity": 1,
 "ship_to": {"name": "…", "line1": "…", "city": "…", "country": "US", "postcode": "…"}}
```

Only `name`, `line1`, `city`, `country` are required. The address is trimmed to
the fields a printer needs — an order record isn't a place to accumulate personal
data.

### Fulfilment

Orders walk `pending → submitted → in_production → shipped → delivered`, with
`cancelled` / `failed` as terminal states. Terminal is final, so a replayed
provider webhook can't reopen a delivered order.

Only the **seller** (or the platform owner, for support) can move an order —
marking your own purchase delivered isn't a thing.

With no provider configured, orders rest at `pending` on the seller's `to_fulfil`
queue, to be placed by hand. That's a real workflow for a small shop, not a
broken state. To automate:

```
POD_PROVIDER=printful          # or printify
PRINTFUL_API_KEY=…             # or PRINTIFY_API_KEY
```

`pod.submit_order` is the one function to fill in — the money path above never
needs touching again. Submission is best-effort by design: the buyer has already
paid and the order is already recorded, so a provider outage must not fail the
purchase.

---

## Setup

```bash
python manage.py seed_pod        # create/update the blank catalog (idempotent)
```

Costs in `apps/economy/pod.py` are realistic placeholders. Replace them with what
your provider actually quotes and re-run — `seed_pod` updates in place, so a
reprice changes only what moved and leaves every listing intact.
