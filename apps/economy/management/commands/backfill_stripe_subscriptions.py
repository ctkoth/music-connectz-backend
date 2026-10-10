"""Find the Stripe subscriptions our own rows have forgotten, and the ones that outlived their account.

Two gaps, one source:

1. **The ledger starts empty.** `StripeSubscription` is written by the webhook
   from now on. A member who bought Premium and later StatZ BEFORE it existed has
   one subscription named by their membership row and one named by nothing, and
   `cancel_for` cannot find the second when they delete their account. Stripe
   can: every subscription Checkout carries the member's id
   (`client_reference_id` and `metadata.user_id`), and a Session is kept
   indefinitely.
2. **Accounts deleted before the cancel existed.** Their rows cascaded away, and
   what is left is a live subscription whose Checkout names a user that no
   longer exists — still billing a card, with nothing to stop it. Those are
   listed here, and `--cancel-orphans` ends them.

Dry by default, like `reconcile_uploads`: it prints what it found and changes
nothing without `--write`. Cancelling is a second, separate switch, because
ending somebody's billing is not the same kind of act as writing a row down.
Cancelling is immediate and refunds nothing.

It needs the live `STRIPE_SECRET_KEY`, so it can only be run where that is set.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.economy import stripe_cancel
from apps.economy.models import StripeSubscription

User = get_user_model()


def _get(obj, name):
    """Read a field off a Stripe object. They stopped being dicts in SDK 15."""
    try:
        return getattr(obj, name, None)
    except Exception:  # noqa: BLE001
        return None


class Command(BaseCommand):
    help = "Record subscriptions the ledger is missing; list (and optionally cancel) ones whose account was deleted."

    def add_arguments(self, parser):
        parser.add_argument("--write", action="store_true",
                            help="Write the missing ledger rows. Without it, nothing changes.")
        parser.add_argument("--cancel-orphans", action="store_true",
                            help="With --write: cancel live subscriptions whose account no longer exists.")

    def handle(self, *args, **opts):
        write, cancel = opts["write"], opts["cancel_orphans"]
        if cancel and not write:
            raise CommandError("--cancel-orphans needs --write; a dry run cancels nothing.")
        key = getattr(settings, "STRIPE_SECRET_KEY", "")
        if not key:
            raise CommandError("STRIPE_SECRET_KEY is not set, so there is no Stripe to read.")

        client = stripe_cancel._client(key)
        params = {"limit": 100, "status": "complete", "expand": ["data.subscription"]}
        exists, recorded = {}, set(StripeSubscription.objects.values_list("stripe_subscription_id", flat=True))
        seen = to_add = cancelled = 0
        orphans = []

        for session in client.v1.checkout.sessions.list(params).auto_paging_iter():
            sub = _get(session, "subscription")
            if _get(session, "mode") != "subscription" or not sub:
                continue
            sub_id = sub if isinstance(sub, str) else _get(sub, "id")
            status = None if isinstance(sub, str) else _get(sub, "status")
            meta = _get(session, "metadata")
            uid = _get(meta, "user_id") or _get(session, "client_reference_id")
            kind = _get(meta, "kind") or ""
            customer = _get(session, "customer")
            customer = customer if isinstance(customer, str) or customer is None else _get(customer, "id")
            if not (sub_id and uid):
                continue
            try:
                int(uid)
            except (TypeError, ValueError):
                continue                      # not an id of ours; say nothing about it
            seen += 1

            if uid not in exists:
                exists[uid] = User.objects.filter(pk=uid).first()
            user = exists[uid]

            if user is not None:
                if sub_id not in recorded:
                    to_add += 1
                    recorded.add(sub_id)
                    self.stdout.write(f"record   {sub_id}  {kind or '?'}  -> {user.get_username()}")
                    if write:
                        StripeSubscription.objects.update_or_create(
                            stripe_subscription_id=sub_id,
                            defaults={"user": user, "stripe_customer_id": customer or "", "kind": kind})
                continue

            if status in stripe_cancel.DONE:
                continue                      # an ended subscription of a deleted account bills nothing
            orphans.append(sub_id)
            self.stdout.write(self.style.WARNING(
                f"ORPHAN   {sub_id}  {kind or '?'}  status={status or 'unknown'}  account {uid} no longer exists"))
            if write and cancel:
                if stripe_cancel.cancel_orphan(sub_id, kind, uid):
                    cancelled += 1
                    self.stdout.write(f"cancelled {sub_id}")

        self.stdout.write(
            f"{seen} subscription checkouts read. {to_add} {'written' if write else 'would be written'} to the ledger. "
            f"{len(orphans)} live subscriptions belong to deleted accounts"
            + (f"; {cancelled} cancelled." if cancel else
               ("." if not orphans else ". Run again with --write --cancel-orphans to end them.")))
        if not write and to_add:
            self.stdout.write("Dry run: nothing was written. Re-run with --write.")
