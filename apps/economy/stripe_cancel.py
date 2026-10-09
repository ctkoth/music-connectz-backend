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

What it cancels is FOUND, not just read off our own rows:

- every live subscription on every Stripe customer we know for the member
  (`Membership.stripe_customer_id`, `AutoTopUp.stripe_customer_id`), because the
  membership row keeps only the LAST subscription id and a member who switched
  plans may have an older one still running;
- plus the ids we do hold, which may belong to a customer we never recorded.

`AutoTopUp.active` is NOT trusted. `AutoTopUpCancelView` flips it to False even
when its Stripe call failed ("already gone / network — flip local state
regardless"), so an inactive row can still be billing. Every id is checked at
Stripe instead, and one that is already cancelled is skipped rather than
cancelled twice — otherwise a stale id would answer an error forever and the
member could never delete their account.

It cancels IMMEDIATELY and refunds nothing: the rest of a paid period is not
returned (the 10-day refund window is `MembershipRefundView`, a separate door the
member opens on purpose before this one). The delete screen and the web page say
so before the button.

It does NOT delete the Stripe customer, so the saved card stays on Stripe's side
under their own retention. That is a different promise and a different call.

The whole pass runs on one `Deadline` and one client with its own timeout, for
the reason `deadline.py` exists: the member is sitting on a delete button, and a
pass that can legally take a minute and a half is the 853-second spinner again.
"""
import logging

from django.conf import settings

from .deadline import Deadline

log = logging.getLogger(__name__)

BUDGET_SECONDS = 20          # the whole pass; a person is waiting on a button
CALL_TIMEOUT_SECONDS = 8     # one call to Stripe
# Subscriptions that cannot bill any more. Everything else — active, trialing,
# past_due, unpaid, incomplete, paused — can still produce a charge.
DONE = frozenset({"canceled", "incomplete_expired"})

REFUSAL = (
    "We couldn't cancel the billing on this account with Stripe, so it has not been "
    "deleted. Try again in a few minutes. If it keeps failing, email "
    "support@musicconnectz.net."
)


class CancelFailed(ValueError):
    """Billing could not be stopped, so the account must not be deleted.

    A `ValueError` on purpose: every caller of `delete_duplicate` already turns a
    `ValueError` into a refusal that says why, and this is exactly that.
    """

    def __init__(self, detail=REFUSAL):
        super().__init__(detail)
        self.detail = detail


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
    """Stripe says the thing is not there — which, for a cancel, is success."""
    return getattr(exc, "code", None) == "resource_missing"


def _known(user):
    """(subscription ids, customer ids) that our own rows remember for `user`."""
    from .models import AutoTopUp, Membership

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
    from .models import AutoTopUp, Membership

    others = set(Membership.objects.filter(stripe_customer_id__in=customers)
                 .exclude(user=user).values_list("stripe_customer_id", flat=True))
    others |= set(AutoTopUp.objects.filter(stripe_customer_id__in=customers)
                  .exclude(user=user).values_list("stripe_customer_id", flat=True))
    return others


def cancel_for(user):
    """Cancel every live Stripe subscription belonging to `user`.

    Returns the ids it cancelled. Raises `CancelFailed` if anything that might
    still bill could not be cancelled or checked. Nothing to cancel, or Stripe
    not configured at all (a dev box has no key and so cannot be billing), is
    an empty list rather than an error.
    """
    key = getattr(settings, "STRIPE_SECRET_KEY", "")
    ids, customers = _known(user)
    if not key or not (ids or customers):
        return []

    shared = _shared_with_others(user, customers)
    if shared:
        log.warning("stripe cancel: customer(s) %s are shared with another account; "
                    "cancelling only the subscription ids this account holds", sorted(shared))
        customers -= shared

    client = _client(key)
    budget = Deadline(BUDGET_SECONDS)
    live, failed = {}, 0

    # 1. Everything live on every customer we know about.
    for cid in sorted(customers):
        try:
            budget.check()
            for sub in client.v1.subscriptions.list({"customer": cid, "limit": 100}).auto_paging_iter():
                if sub.status not in DONE:
                    live[sub.id] = sub.status
        except Exception as exc:  # noqa: BLE001 — see below
            if _gone(exc):
                continue           # the customer is not at Stripe any more
            failed += 1
            log.exception("stripe cancel: could not list subscriptions for customer %s", cid)

    # 2. The ids we hold that the listing did not already show.
    for sid in sorted(ids - set(live)):
        try:
            budget.check()
            sub = client.v1.subscriptions.retrieve(sid)
            if sub.status not in DONE:
                live[sid] = sub.status
        except Exception as exc:  # noqa: BLE001
            if _gone(exc):
                continue
            failed += 1
            log.exception("stripe cancel: could not look up subscription %s", sid)

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
        raise CancelFailed()
    return cancelled
