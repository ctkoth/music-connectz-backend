# Stripe audit

Audited against the code in `apps/economy/` — `payments.py`, `identity.py`,
`autotopup.py`, `models.py`. I can't see your Stripe dashboard, so **§1 is the
part you have to check yourself**; everything else is verified in the code.

488 tests pass.

---

## 1. Your webhook: the events you must be subscribed to

One endpoint handles everything: `POST /api/economy/stripe/webhook/`.

Go to **Stripe → Developers → Webhooks → your endpoint → Events**. These nine
must be listed. Anything the code handles but you aren't subscribed to is
silently dead — it looks fine in the code and never fires in production.

| Event | What breaks if it's missing |
|---|---|
| `checkout.session.completed` | **Everything.** No wallet funding, no Premium, no lifetime, no auto-top-up setup. Money taken, nothing granted. |
| `invoice.payment_succeeded` | Auto-top-up renewals never credit. |
| `invoice.paid` | Same. Stripe fires **both** for one invoice — see §2. |
| `invoice.payment_failed` | A dead subscription keeps its tier forever. |
| `customer.subscription.deleted` | Cancelled subs keep their tier forever. |
| `identity.verification_session.verified` | **Nobody ever gets verified 18+.** |
| `identity.verification_session.requires_input` | Failed ID checks never report a reason. |
| `identity.verification_session.processing` | "Checking…" never appears. |
| `identity.verification_session.canceled` | An abandoned check stays "Checking…" forever. |

**If you only ever added `checkout.session.completed`, that alone explains why
your verification went nowhere** — the Identity events were never delivered.

Two more to check while you're there:

- **The endpoint URL** must be the deployed backend, not the frontend. With the
  backend at `admin.musicconnectz.net`, that's
  `https://admin.musicconnectz.net/api/economy/stripe/webhook/`.
- **The signing secret** shown on that page must equal `STRIPE_WEBHOOK_SECRET`
  on Render. A wrong secret makes every event fail signature verification and
  return 400 — Stripe shows them all as failed deliveries, and nothing is
  processed. Test-mode and live-mode secrets are different.

**How to know for sure:** the endpoint page lists recent deliveries with
response codes. All 200 means it's working. All 400 means the signing secret is
wrong. No deliveries at all means the events aren't subscribed, or the URL is
wrong.

---

## 2. What's correct

Verified by reading the code, not assumed.

**Signature verification** — `construct_event` against the raw `request.body`,
rejecting with 400. The view is `AllowAny` with `authentication_classes = []`,
which is right for a server-to-server callback, and the signature is what
authenticates it.

**Replay safety.** Stripe retries, and `invoice.paid` and
`invoice.payment_succeeded` **both fire for the same invoice** — so this path
runs twice every renewal by design. It's safe: crediting goes through
`PaymentIntent.provider_ref`, which is `unique=True` at the database level, and
the credit is guarded by `select_for_update()` plus a status check. The second
run is a no-op. This is the single most important thing in the payment code and
it's right.

**Amounts are server-side.** `_amount_or_error` validates before the session is
created; the client never states its own price. Developer tax is applied inside
`credit_funds`, not passed in.

**Lifetime members are protected.** `_downgrade_by_customer` filters
`lifetime=False`, so a failed unrelated subscription can't strip a lifetime
grant.

**Dead subscriptions downgrade promptly.** `invoice.payment_failed` checks
`next_payment_attempt is None` — when Stripe has given up retrying, the tier
drops immediately rather than waiting for the eventual `deleted` event.

---

## 3. Bugs found and fixed in this pass

**`identity.verification_session.created` read as a failure.** `requires_input`
means two different things: a session that *failed and needs another attempt*,
and a *brand-new* session waiting on the member. Stripe fires `created` with
`requires_input` before they've done anything. The code I wrote earlier today
would have flashed **"Didn't pass ❌" the instant they pressed start** — worse
than the silence it replaced. Now a `requires_input` with no `last_error` is
treated as in-progress.

**Out-of-order events could un-verify someone.** Stripe doesn't guarantee
ordering. A late `created` or `processing` for an old session would drop a
verified member back to "Checking…". A pass is now terminal for the age gate —
a date of birth doesn't change.

**A future SDK upgrade would turn rejected forgeries into 500s.**
`requirements.txt` pins `stripe>=8.0` with no upper bound, and the handler
caught `stripe.error.SignatureVerificationError`. `stripe.error` is a legacy
alias. If a release drops it, evaluating that path *inside the except clause*
raises AttributeError while handling a bad signature — a clean 400 becomes a
500, and Stripe retries what should have been rejected outright. Now resolved
defensively against both locations.

---

## 4. Gaps — your call, not fixed

### 🔴 Chargebacks and refunds don't claw anything back

Neither `charge.dispute.created` nor `charge.refunded` is handled. Today:
somebody funds a $200 wallet, spends it, then disputes the charge. Stripe pulls
the $200 back from you **plus a ~$15 dispute fee**. Their wallet balance,
tier and anything they bought are untouched.

This is the largest financial hole in the payment code and it's not theoretical
— it's the standard fraud pattern against any platform that converts a card
charge into in-app credit. It gets worse the moment BattleZ cash pools are live,
because credit becomes withdrawable.

Handling it means deciding what happens when the balance is already spent — the
same clamp-and-record problem the POD seller refund had, where the wallet can't
go negative. Worth doing before real money, and it needs your call on policy
(freeze the account? negative ledger? absorb it?).

### 🟡 Delayed payment methods would credit before settling

`checkout.session.async_payment_succeeded` and `async_payment_failed` aren't
handled. **This is harmless while you're card-only** — but if you ever enable
ACH, iDEAL, Bacs or SEPA, `checkout.session.completed` fires *before the money
settles*, and the wallet would be credited on a payment that can still fail
days later. Add these before enabling any non-card method.

### 🟡 No event-id ledger

There's no table of seen `event.id`s. In practice every money path is already
idempotent via `PaymentIntent`, so this is defence-in-depth rather than a live
bug. The one visible effect: a replayed `checkout.session.completed` for a
subscription re-stamps `last_paid_at`, which shifts the 10-day refund window
slightly. Low priority.

### 🟢 `customer.subscription.updated` isn't handled

Plan changes and `cancel_at_period_end` aren't reflected until the subscription
actually ends. Given `deleted` and `payment_failed` are both handled, nothing
breaks — a member who cancels keeps what they paid for until the period ends,
which is correct. Only worth adding if you introduce plan upgrades mid-cycle.

---

## 5. Environment variables

| Variable | Used for | Missing means |
|---|---|---|
| `STRIPE_SECRET_KEY` | Creating checkout + Identity sessions | Every payment and verification endpoint returns 503 |
| `STRIPE_WEBHOOK_SECRET` | Verifying webhook signatures | Webhook returns 503 — **nothing is ever granted** |
| `STRIPE_PUBLISHABLE_KEY` | Frontend | Checkout can't be opened client-side |
| `FRONTEND_URL` | `success_url` / `cancel_url` / Identity `return_url` | Members get bounced to the wrong place after paying |

Both Stripe keys must be from the **same mode**. A live secret key with a
test-mode webhook secret fails every signature, and the symptom looks exactly
like a code bug.

---

## 6. Recommended order

1. **Check the nine events in §1.** Most likely explanation for your
   verification going nowhere, and it's a two-minute fix in the dashboard.
2. **Deploy this branch** and hit `POST /api/economy/identity/` with
   `{"action": "refresh"}` — it pulls status straight from Stripe, so it works
   even if the webhook was never wired up.
3. **Decide the chargeback policy**, then implement `charge.dispute.created`.
   Before BattleZ cash, not after.
4. Pin `stripe<16` in `requirements.txt` if you'd rather not rely on the
   defensive lookup.
