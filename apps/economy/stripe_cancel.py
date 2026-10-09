"""Stop the billing before the account that owns it is gone.

Deleting an account used to be `user.delete()` and nothing else. The Stripe
subscription lived on at Stripe: the ids that could have found it
(`Membership.stripe_customer_id`, `AutoTopUp.stripe_subscription_id`) sit on rows
that cascade away with the member, so once the account was deleted there was
nothing left on our side that knew the subscription existed. Premium kept
billing a card whose owner could no longer sign in to cancel it, and an auto
top-up kept charging and crediting a wallet that was gone.

So the order is the whole design:

    cancel at Stripe  ->  then delete

- **Before**, because afterwards the only thing that can find the subscription
  is a human with the Stripe dashboard and a guess.
- **A failed cancel refuses the delete.** The two ways to be wrong are not
  equal. Delete anyway and the member keeps being charged by an account that no
  longer exists, with no screen to stop it. Refuse and the member sees a
  sentence and tries again in a few minutes. The same trade `delete_duplicate`
  makes for money: a refusal is a retry, a destroyed thing is not.
- **A cancel that succeeds and then a delete that fails** leaves the account
  alive with its billing stopped, and Stripe's own `customer.subscription.deleted`
  webhook downgrades them to Free. The wrong half to be left holding is
  "still paying", never "no longer paying", and this order cannot produce it.

What it cancels is FOUND, not just read off the membership row, because the
membership row cannot be trusted to remember. **Every Checkout here creates a
brand-new Stripe customer** (none passes `customer=`) and the webhook then
OVERWRITES `Membership.stripe_customer_id` / `last_payment_ref` with the newest.
So a member who bought Premium and later StatZ has two live subscriptions on two
customers and one row naming one of them — and the first review of this module
cancelled the StatZ one, deleted the account, and left Premium billing. Three
sources are read, because any one alone has that hole:

- `StripeSubscription`, the append-only ledger the webhook writes once per
  subscription and never overwrites (`remember`) — the one that sees Premium
  AFTER StatZ replaced it on the membership row;
- the membership and auto-top-up rows, which cover everything that predates the
  ledger and anything the ledger write missed;
- **every live subscription on every customer either of those names**, because
  a row keeps one subscription id and a customer can hold more.

Subscriptions bought before the ledger existed and since overwritten are
invisible to all three. `manage.py backfill_stripe_subscriptions` recovers them
from Stripe's own Checkout Sessions, which carry the member's id.

`AutoTopUp.active` is NOT trusted. `AutoTopUpCancelView` flips it to False even
when its Stripe call failed ("already gone / network — flip local state
regardless"), so an inactive row can still be billing. Every id is checked at
Stripe instead, and one that is already cancelled is skipped rather than
cancelled twice — otherwise a stale id would answer an error forever and the
member could never delete their account.

A payment that lands AFTER the account is gone is the other half. A Checkout
stays payable for hours, and its `checkout.session.completed` then names a user
that no longer exists, so the webhook had nothing to attach it to and answered
200. `cancel_orphan` is what the webhook calls instead: the subscription is
cancelled the moment it is seen.

It cancels IMMEDIATELY and refunds nothing: the rest of a paid period is not
returned (the 10-day refund window is `MembershipRefundView`, a separate door the
member opens on purpose before this one). The delete screen and the web page say
so before the button.

It does NOT delete the Stripe customer, so the saved card stays on Stripe's side
under their own retention. That is a different promise and a different call.

**It fails closed on its own misconfiguration.** Rows that name Stripe ids with
no `STRIPE_SECRET_KEY` are proof billing may exist and that nobody can reach it,
so that refuses; an account with no Stripe ids on any row has nothing to cancel
and a dev box with no key can delete it. And `resource_missing` means "gone" only
when the key could see the object's mode: Stripe uses the same code for a
live-mode id asked of a test-mode key, and reading that as success would turn a
wrong key into a platform where every delete goes through and nothing is
cancelled. It is logged either way.

The whole pass runs on one `Deadline` and one client with its own timeout, for
the reason `deadline.py` exists: the member is sitting on a delete button, and a
pass that can legally take a minute and a half is the 853-second spinner again.
A per-call timeout is not a per-call bound — `requests` applies it to each socket
operation, and the SDK retries once after a pause — so one stalled call was
measured at about 16s against an 8s setting. Hence the small numbers: with
`CALL_TIMEOUT_SECONDS` 4 a stalled call costs about 9s, the budget is only
checked BETWEEN calls, and the worst pass is `BUDGET_SECONDS` plus one stalled
call, inside the 30s the client waits before it gives up.
"""
import logging

from django.conf import settings

from .deadline import Deadline

log = logging.getLogger(__name__)

BUDGET_SECONDS = 15          # the whole pass; a person is waiting on a button
CALL_TIMEOUT_SECONDS = 4     # one call to Stripe, per socket operation
# Subscriptions that cannot bill any more. Everything else — active, trialing,
# past_due, unpaid, incomplete, paused — can still produce a charge.
DONE = frozenset({"canceled", "incomplete_expired"})
# The `kind` a Checkout carries in its metadata when it starts a subscription.
SUBSCRIPTION_KINDS = frozenset({"autotopup", "founding_sub", "statz_sub", "premium_sub"})

REFUSAL = (
    "We couldn't cancel the billing on this account with Stripe, so it has not been "
    "deleted. Try again in a few minutes. If it keeps failing, email "
    "support@musicconnectz.net."
)
# Said only when part of it DID go through: Stripe's own webhook downgrades the
# plan the moment its subscription ends, so the member can see Free on a
# refusal and would otherwise have no way to know why.
PARTIAL = (
    " Some of your billing was cancelled before this failed, so your plan may "
    "already show as Free."
)


class CancelFailed(ValueError):
    """Billing could not be stopped, so the account must not be deleted.

    A `ValueError` on purpose: every caller of `delete_duplicate` already turns a
    `ValueError` into a refusal that says why, and this is exactly that.
    `cancelled` is whatever DID get cancelled before the failure.
    """

    def __init__(self, detail=REFUSAL, cancelled=()):
        super().__init__(detail)
        self.detail = detail
        self.cancelled = list(cancelled)


def _client(key):
    """One Stripe client, with its own timeout and no global state.

    The rest of the app sets `stripe.api_key` and uses the module-level calls,
    which carry the SDK's 80-second default — fine for a webhook, not for a
    button somebody is waiting on. A separate client bounds this without
    changing how anything else talks to Stripe.
    """
    import stripe
    return stripe.StripeClient(
        key,
        http_client=stripe.RequestsClient(timeout=CALL_TIMEOUT_SECONDS),
        max_network_retries=1,
    )


def _gone(exc):
    """Stripe says the thing is not there — which, for a cancel, is success.

    Unless the message says a similar object exists in the OTHER mode: that is a
    key that cannot see what it was asked about, and nothing was cancelled.
    """
    if getattr(exc, "code", None) != "resource_missing":
        return False
    if "similar object exists" in str(exc):
        return False
    log.warning("stripe cancel: treating as already gone: %s", exc)
    return True


def remember(user, customer_id, subscription_id, kind):
    """Write one subscription into the ledger. Never raises.

    The webhook has already moved the money and granted the tier by the time this
    runs, and a ledger that could undo that would be worse than the gap it
    closes — so a failure is logged and the membership row still holds the pair.
    """
    if not subscription_id:
        return
    try:
        from .models import StripeSubscription
        StripeSubscription.objects.update_or_create(
            stripe_subscription_id=subscription_id,
            defaults={"user": user, "stripe_customer_id": customer_id or "", "kind": kind or ""},
        )
    except Exception:  # noqa: BLE001
        log.exception("stripe ledger: could not record %s for user %s", subscription_id, getattr(user, "pk", "?"))


def cancel_orphan(subscription_id, kind="", uid=""):
    """Cancel a subscription that was paid for by an account that no longer exists.

    Raises on any failure other than "already gone" or "already ended", so the
    webhook answers 5xx and Stripe retries — the opposite of every other branch
    there, on purpose: a 200 here is a subscription that bills forever.
    """
    if not subscription_id:
        return False
    key = getattr(settings, "STRIPE_SECRET_KEY", "")
    if not key:
        return False
    client = _client(key)
    try:
        sub = client.v1.subscriptions.retrieve(subscription_id)
        if sub.status in DONE:
            return False
        client.v1.subscriptions.cancel(subscription_id)
    except Exception as exc:  # noqa: BLE001
        if _gone(exc):
            return False
        log.exception("stripe cancel: could not cancel orphan %s", subscription_id)
        raise
    log.warning("stripe cancel: cancelled %s (%s) — paid for by deleted account %s",
                subscription_id, kind, uid)
    return True


def _known(user):
    """(subscription ids, customer ids) that our own rows remember for `user`."""
    from .models import AutoTopUp, Membership, StripeSubscription

    ids, customers = set(), set()
    m = Membership.objects.filter(user=user).first()
    if m:
        if m.stripe_customer_id:
            customers.add(m.stripe_customer_id)
        # `last_payment_ref` is a subscription id for a subscription and a
        # PaymentIntent id (`pi_…`) for a lifetime purchase; only `sub_…` is
        # something that bills again.
        if (m.last_payment_ref or "").startswith("sub_"):
            ids.add(m.last_payment_ref)
    for a in AutoTopUp.objects.filter(user=user):
        if a.stripe_customer_id:
            customers.add(a.stripe_customer_id)
        if a.stripe_subscription_id:       # active or not: see the docstring
            ids.add(a.stripe_subscription_id)
    for s in StripeSubscription.objects.filter(user=user):
        if s.stripe_customer_id:
            customers.add(s.stripe_customer_id)
        ids.add(s.stripe_subscription_id)
    return ids, customers


def _shared_with_others(user, customers):
    """Customers that another account's rows ALSO point at.

    Listing a customer's subscriptions and cancelling them all is only right when
    the customer is this member's alone. Nothing in the schema makes
    `stripe_customer_id` unique, and a customer that two accounts share (a
    duplicate account is exactly how that happens) would have the OTHER member's
    subscription cancelled by this member's deletion. Cancelling a stranger's
    billing is the worse mistake of the two, so a shared customer is not swept;
    only the subscription ids this member's own rows hold are cancelled on it.
    """
    from .models import AutoTopUp, Membership, StripeSubscription

    others = set(Membership.objects.filter(stripe_customer_id__in=customers)
                 .exclude(user=user).values_list("stripe_customer_id", flat=True))
    others |= set(AutoTopUp.objects.filter(stripe_customer_id__in=customers)
                  .exclude(user=user).values_list("stripe_customer_id", flat=True))
    others |= set(StripeSubscription.objects.filter(stripe_customer_id__in=customers)
                  .exclude(user=user).values_list("stripe_customer_id", flat=True))
    return others


def cancel_for(user):
    """Cancel every live Stripe subscription belonging to `user`.

    Returns the ids it cancelled. Raises `CancelFailed` if anything that might
    still bill could not be cancelled or checked. An account whose rows name no
    Stripe id has nothing to cancel and gets an empty list; one that names ids
    when Stripe is not configured at all is a refusal, not a pass.
    """
    key = getattr(settings, "STRIPE_SECRET_KEY", "")
    ids, customers = _known(user)
    if not (ids or customers):
        return []
    if not key:
        log.error("stripe cancel: user %s has Stripe ids on file but STRIPE_SECRET_KEY is "
                  "not set; refusing the delete rather than leaving the billing running",
                  getattr(user, "pk", "?"))
        raise CancelFailed()

    shared = _shared_with_others(user, customers)
    if shared:
        log.warning("stripe cancel: customer(s) %s are shared with another account; "
                    "cancelling only the subscription ids this account holds", sorted(shared))
        customers -= shared

    client = _client(key)
    budget = Deadline(BUDGET_SECONDS)
    seen, failed = {}, 0

    # 1. Everything on every customer we know about, whatever its status — so a
    #    cancelled one is known to be cancelled and costs no second lookup.
    for cid in sorted(customers):
        try:
            budget.check()
            params = {"customer": cid, "status": "all", "limit": 100}
            for sub in client.v1.subscriptions.list(params).auto_paging_iter():
                seen[sub.id] = sub.status
        except Exception as exc:  # noqa: BLE001 — see below
            if _gone(exc):
                continue           # the customer is not at Stripe any more
            failed += 1
            log.exception("stripe cancel: could not list subscriptions for customer %s", cid)

    # 2. The ids we hold that the listing did not show.
    for sid in sorted(ids - set(seen)):
        try:
            budget.check()
            seen[sid] = client.v1.subscriptions.retrieve(sid).status
        except Exception as exc:  # noqa: BLE001
            if _gone(exc):
                continue
            failed += 1
            log.exception("stripe cancel: could not look up subscription %s", sid)

    live = {sid: st for sid, st in seen.items() if st not in DONE}

    # 3. Cancel what is live.
    cancelled = []
    for sid in sorted(live):
        try:
            budget.check()
            client.v1.subscriptions.cancel(sid)
            cancelled.append(sid)
            log.info("stripe cancel: cancelled %s (was %s) for account deletion", sid, live[sid])
        except Exception as exc:  # noqa: BLE001
            if _gone(exc):
                continue
            failed += 1
            log.exception("stripe cancel: could not cancel subscription %s", sid)

    # Every error above is caught and counted rather than allowed to end the
    # pass, so ONE bad subscription does not stop the others being cancelled:
    # a member with two should not be left with one still billing because the
    # first call timed out.
    if failed:
        raise CancelFailed(REFUSAL + (PARTIAL if cancelled else ""), cancelled)
    return cancelled
