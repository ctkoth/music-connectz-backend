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

## What you can put a design on

**20 blanks.** `GET /api/economy/pod/blanks/` is the live list — this table is a
snapshot.

### Apparel
| Blank | Process | Sizes | Cost to make |
|---|---|---|---|
| Unisex T-Shirt | DTG | S–3XL | $15.50 |
| Premium Heavyweight Tee | DTG | S–2XL | $20.00 |
| **Unisex Tank Top** | DTG | S–2XL | $16.50 |
| Long Sleeve Tee | DTG | S–3XL | $22.00 |
| Crewneck Sweatshirt | DTG | S–2XL | $28.50 |
| Pullover Hoodie | DTG | S–3XL | $32.50 |
| **All-Over-Print Kimono Robe** | AOP | S/M, L/XL, 2XL/3XL | $49.50 |
| **All-Over-Print Bomber Jacket** | AOP | S–2XL | $54.50 |
| **All-Over-Print Windbreaker** | AOP | S–2XL | $47.00 |
| **Embroidered Denim Jacket** | Embroidery | S–2XL | $63.00 |

### Headwear
| Blank | Process | Cost to make |
|---|---|---|
| **Embroidered Baseball Cap** | Embroidery | $18.50 |
| **Snapback Cap** | Embroidery | $20.50 |
| **Trucker Cap (mesh back)** | Embroidery | $19.50 |
| **Cuffed Beanie** | Embroidery | $17.50 |

### Home & accessories
| Blank | Process | Cost to make |
|---|---|---|
| **Beach Towel (30x60 / 20x40)** | Sublimation | $32.50 |
| Canvas Tote | DTG | $16.00 |
| Ceramic Mug (11oz / 15oz) | Sublimation | $13.50 |
| Matte Poster (12x18 → 24x36) | Paper | $15.50 |
| Record Sleeve Print (12x12) | Paper | $18.50 |
| Vinyl Sticker Pack (3" / 5") | Cut vinyl | $5.00 |

Costs are landed (blank + print + domestic shipping) for the base variant, before
size/colour upcharges. They're realistic placeholders — replace them in
`apps/economy/pod.py` with what your provider actually quotes and re-run
`seed_pod`.

## The process decides what your artwork can be

This is the limit that catches people out — not which products exist, but which
artwork survives which process. Every blank declares its `print_method`, and the
API returns the rules with it.

| Process | Full bleed | Min resolution | Colours | The catch |
|---|---|---|---|---|
| **DTG** | no | 1800px | any | Photos and gradients fine. Dark garments need a white underbase (costs more), and **white ink on a white shirt is invisible** — the garment is your white. |
| **Embroidery** | no | 1000px | **6 max** | Stitched, not printed. **No gradients, no photographs**, nothing finer than ~3mm, no text under 5mm. A logo works; album art doesn't. |
| **Sublimation** | yes | 3000px | any | Vivid and permanent, but white/light **polyester only** — cotton won't take it, and there's no white ink, so white in your design is bare fabric. |
| **All-over print** | **yes** | 4000px | any | Printed on flat panels **before the garment is cut and sewn**. Needs full-bleed art at large dimensions and **seams interrupt it** — a centred logo is the wrong design. Patterns and textures are what it's for. |
| **Cut vinyl** | no | 1500px | 4 max | Solid shapes cut from sheet. Crisp edges, no gradients, each colour a layer. |
| **Paper** | yes | 3600px | any | The forgiving one. 300 DPI at final size or a 24-inch poster looks soft. |

So: your one design **won't** work everywhere. A photographic cover will print
beautifully on a tee, poster and mug, and come back from embroidery as an
unrecognisable blob. The kimono and jackets want a repeating pattern, not a logo.

### Artwork is measured on upload and checked per blank

Every design's pixel size and transparency are recorded at upload (once — with
object storage, re-reading the file per product page is a network round trip
each). `POST /pod/designs/` then returns a `suitability` block:

```json
{"measured": true, "width": 4500, "height": 4500, "shortest_side": 4500,
 "good_for": ["poster", "tee", "hoodie", "kimono", "…"],
 "warnings_for": [{"product": "cap", "print_method": "embroidery",
                   "warnings": ["Embroidered Baseball Cap is embroidery — 6 colours maximum,
                                 no gradients or photographs…"]}]}
```

Listing returns `artwork_ok` and `artwork_warnings` for that specific blank. The
checks are **advisory and the listing is created either way** — image analysis
can't tell a deliberately lo-fi design from a mistake, and a flat two-colour logo
genuinely is fine at a size that would ruin a photograph. A warning you can
override beats a refusal that's wrong.

What it catches: resolution below the method's minimum (measured on the **short**
side, because a 6000×400 banner is not a 6000px design), artwork too oblong for a
cut-and-sew garment, transparency going to a no-white-ink process, a solid
rectangle heading for a garment, and embroidery's colour ceiling.

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
- **Artwork is checked, not enforced.** Uploads are measured and warned about per
  print method (see below) — but a warning you can override, not a refusal.
- **Shipping is one flat cost per blank**, folded into the landed cost.
  International shipping and multi-item basket consolidation aren't modelled — a
  two-item order pays two shipping costs.
- **Refunds exist; returns don't.** `POST /pod/orders/<id>/refund/` reverses the
  money while an order is still `pending` or `submitted`. Once it's in production
  or shipped it's refused — there's a real garment in a real van by then, and
  that's a return to settle with the buyer, not a button.

---

## Seller paperwork: invoices, what's selling, and a monthly statement

Three different questions, three endpoints:

```
GET /api/economy/pod/orders/<id>/invoice/   one order, as a document
GET /api/economy/pod/sales/                 what's selling (ranked by revenue)
GET /api/economy/pod/statement/?month=YYYY-MM   a month, for the accountant
```

### What's selling

```
7 orders · 7 units · gross $220.49  (print $139.00 · fee $8.15 · YOU $73.34)
awaiting fulfilment: 7  ·  cancelled: 1

Best sellers:
  Logo Tee        5 units  gross $134.00  net $42.75
  Logo Hoodie     1 units  gross $ 56.50  net $20.25
  Logo Cap        1 units  gross $ 29.99  net $10.34

By size:   L=3  3XL=1  One size=1  2XL=1  M=1
By colour: Black=4  White=2  Navy=1
```

Ranked by **revenue, not units** — ten stickers and one hoodie are not the same
result, and revenue is the number to decide from. Also broken down by product, by
size, by colour, and by month (chronological, so it reads as a trend line).

Size and colour are the actionable ones: if 3XL is a third of your tee sales,
that's what to feature and what to keep an eye on for stock-outs.

`?from=YYYY-MM-DD&to=YYYY-MM-DD` bounds it. A seller only ever sees their own
sales.

### An invoice

```
MCZ-POD-000004  status=pending  seller=k-oth buyer=fan
  Logo Tee                            Unisex T-Shirt · 3XL / Black    x1  $30.00
  Size/colour upcharge (3XL / Black)  printer's cost for this variant  x1  $5.00  (incl.)
  gross $30.00 = print $20.50 + fee $0.95 + you $8.55
```

Invoice numbers are derived from the order id (`MCZ-POD-000004`) — stable,
quotable, and with no counter to keep in sync. `lines` comes in document shape
(description / quantity / unit / amount) so a client renders it without doing
arithmetic, and the variant upcharge is its own line: a buyer seeing $30 on a $25
shirt deserves to see why.

Visible to the **buyer, the seller, and the platform owner** only — the document
carries a shipping address. Anyone else gets a 404, not a 403, because whether an
order exists isn't their business either.

### Refunds

```
POST /api/economy/pod/orders/<id>/refund/   {"reason": "wrong size"}
```

Reverses all three legs: the buyer gets the full price back, the seller's credit
is clawed back, and the withheld print cost is released. Either side can do it —
the buyer included, because nothing has been made yet and making them ask the
seller for something the system can do instantly is pure friction.

**Refused once the order is `in_production` or `shipped`.** There's a real garment
in a real van by then; silently refunding it would have the platform eat the print
cost with nothing recording that it happened.

If the seller has already spent their credit, the buyer is still made whole.
Wallets are non-negative platform-wide, so the clawback takes what's there and the
remainder is recorded on the order as `clawback_shortfall_cents` — the platform
absorbs it, visibly. A recorded shortfall is something support can chase; a
refused refund is an angry customer and a chargeback.

### A monthly statement

Every sale in the month with its invoice number, plus gross, print costs withheld,
platform fee, and net payout. It carries a `balanced` flag that is only true when
every line and the totals actually add up — if the arithmetic ever disagreed with
itself, the statement says so rather than printing a confident wrong number.

### ⚠️ These are sales records, not tax invoices

**No sales tax or VAT is calculated, collected, or remitted anywhere in this
system**, and the documents carry no tax registration number. Every document says
so on its face. A seller with a sales-tax, VAT or GST obligation has to handle it
themselves — and if you start selling physical goods across borders at volume, get
advice before you get a letter.

Cancelled and failed orders are excluded from revenue but still listed and
counted. A report that buries cancellations makes them impossible to notice.

Every figure comes from what was snapshotted on the order at sale time, never
recomputed from the current listing — repricing today must not change what last
month earned.

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
