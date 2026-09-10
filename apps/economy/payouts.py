"""Taking the money out — the only path where funds leave the platform.

Everything else in this app moves money between columns of our own tables. A
booking pays a host, escrow releases, `royalties/cashout/` turns
`royalties_cents` into `money_cents`. All of it is store credit until here.

This is the highest-stakes code in the codebase, so the order of operations is
the design and not an implementation detail:

    1. Lock the wallet, check the balance, debit it, and write the Payout row —
       ALL in one transaction. Nothing else can spend the same balance while
       that is open, so two withdrawals racing cannot both pass the check.
    2. Call the provider OUTSIDE that transaction. A network call inside an
       open transaction holds a row lock for as long as the other end takes to
       answer, which under load is how a payments table stops accepting writes.
    3. On refusal, return the money and mark the row failed, atomically.

Debit-first is the load-bearing choice. Paying first and debiting after can
send money we then fail to charge for, and there is no way to get that back.
Debiting first can at worst hold somebody's money for the second it takes to
fail, and then hand it back. One of those failure modes is recoverable.

`Wallet.money_cents` is a PositiveIntegerField, so an overdraw does not quietly
go negative — the database raises. That is a backstop under the check, not a
replacement for it.

**This has never run against Stripe.** No key exists in CI or on a dev box, so
every test here stubs the client — which pins the protocol we BELIEVE in and
cannot tell us we believed the wrong thing. `tools/payout_live_check.sh` is the
check that can, the same way `coach_live_check.sh` is for the coach. Run it
before the first real withdrawal.
"""
import logging
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import PAYOUT_FEE_CENTS, PAYOUT_MAX_CENTS, PAYOUT_MIN_CENTS
from .models import Payout, PayoutAccount, Transaction, Wallet, wallet_for

logger = logging.getLogger(__name__)


def _stripe():
    """The configured Stripe client, or None when it isn't set up.

    Imported lazily like the rest of `payments.py` does, so a deploy without
    the SDK or the key answers "unavailable" instead of failing at import and
    taking the whole app down with it.
    """
    key = getattr(settings, "STRIPE_SECRET_KEY", "")
    if not key:
        return None
    try:
        import stripe
    except ImportError:
        return None
    stripe.api_key = key
    return stripe


def fee_for(amount_cents):
    """What we take off a withdrawal.

    Zero by default, deliberately. A fee here is a cut of money a member has
    already earned, and inventing one is a pricing decision — the kind this
    codebase records for Corey rather than making on its own (see the note
    beside PROMPT_ALLOWANCE). The mechanism is here so the number can be set in
    one place the day he wants one; taking money by default would be the worse
    error to ship.
    """
    return min(int(PAYOUT_FEE_CENTS), int(amount_cents))


def quote(user):
    """What a withdrawal would cost and whether it can happen yet.

    Stated before the button, like every other price in this app. It answers
    even when the member cannot withdraw, because "you have $12 and the minimum
    is $20" is a fact somebody can act on and a greyed-out button is not.
    """
    w = wallet_for(user)
    acct = PayoutAccount.objects.filter(user=user).first()
    balance = max(0, w.money_cents or 0)
    fee = fee_for(balance)

    reasons = []
    if not acct or not acct.account_id:
        reasons.append("Connect a payout account first.")
    elif not acct.payouts_enabled:
        reasons.append(
            "Your payout account isn't approved yet — "
            + (", ".join(acct.requirements[:3]) if acct.requirements
               else "the provider is still checking it.")
        )
    if balance < PAYOUT_MIN_CENTS:
        reasons.append(
            f"The minimum withdrawal is ${PAYOUT_MIN_CENTS / 100:.2f} "
            f"and you have ${balance / 100:.2f}."
        )
    if not _stripe():
        reasons.append("Withdrawals aren't switched on yet.")

    return {
        "balance_cents": balance,
        "min_cents": PAYOUT_MIN_CENTS,
        "max_cents": PAYOUT_MAX_CENTS,
        "fee_cents": fee,
        "net_cents": max(0, balance - fee),
        "connected": bool(acct and acct.account_id),
        "payouts_enabled": bool(acct and acct.payouts_enabled),
        "can_withdraw": not reasons,
        "why_not": reasons,
    }


def _refund(payout, reason):
    """Give it back, and say why. Atomic with marking the row failed.

    A failed payout that has been marked failed but not refunded is money
    missing from a member's wallet with a row next to it saying nothing was
    sent — the worst state this file can produce, so the two moves are one.
    """
    with transaction.atomic():
        w = Wallet.objects.select_for_update().get(user=payout.user)
        w.money_cents = (w.money_cents or 0) + payout.amount_cents
        w.save(update_fields=["money_cents", "updated_at"])
        payout.status = Payout.STATUS_FAILED
        payout.failure_reason = str(reason)[:300]
        payout.completed_at = timezone.now()
        payout.save(update_fields=["status", "failure_reason", "completed_at"])
        Transaction.objects.create(
            user=payout.user, kind=Transaction.KIND_PAYOUT,
            resource=Transaction.RES_MONEY,
            amount=payout.amount_cents, amount_cents=payout.amount_cents,
            note=f"Withdrawal returned — {payout.failure_reason}"[:200],
        )


class PayoutsView(APIView):
    """GET what a withdrawal costs and the history; POST to make one."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = Payout.objects.filter(user=request.user)[:50]
        return Response({
            "quote": quote(request.user),
            "payouts": [{
                "id": p.id,
                "amount_cents": p.amount_cents,
                "fee_cents": p.fee_cents,
                "net_cents": p.net_cents,
                "status": p.status,
                "failure_reason": p.failure_reason,
                "created_at": p.created_at,
                "completed_at": p.completed_at,
            } for p in rows],
        })

    def post(self, request):
        q = quote(request.user)
        if not q["can_withdraw"]:
            return Response({"detail": " ".join(q["why_not"]), "quote": q},
                            status=status.HTTP_409_CONFLICT)

        try:
            amount = int(request.data.get("amount_cents") or q["balance_cents"])
        except (TypeError, ValueError):
            return Response({"detail": "amount_cents must be a whole number of cents."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not (PAYOUT_MIN_CENTS <= amount <= PAYOUT_MAX_CENTS):
            return Response({
                "detail": f"A withdrawal is between ${PAYOUT_MIN_CENTS / 100:.2f} "
                          f"and ${PAYOUT_MAX_CENTS / 100:.2f}.",
                "quote": q,
            }, status=status.HTTP_400_BAD_REQUEST)

        fee = fee_for(amount)
        acct = PayoutAccount.objects.get(user=request.user)
        key = f"payout_{request.user.id}_{uuid.uuid4().hex}"

        # (1) The money leaves and the row is written together, with the wallet
        # locked. Two requests racing cannot both pass the balance check.
        with transaction.atomic():
            w = Wallet.objects.select_for_update().get(user=request.user)
            if (w.money_cents or 0) < amount:
                return Response({"detail": "That's more than your balance.",
                                 "quote": quote(request.user)},
                                status=status.HTTP_409_CONFLICT)
            w.money_cents -= amount
            w.save(update_fields=["money_cents", "updated_at"])
            payout = Payout.objects.create(
                user=request.user, amount_cents=amount, fee_cents=fee,
                net_cents=amount - fee, idempotency_key=key,
                provider=acct.provider,
            )
            Transaction.objects.create(
                user=request.user, kind=Transaction.KIND_PAYOUT,
                resource=Transaction.RES_MONEY,
                amount=-amount, amount_cents=-amount, dev_tax_cents=fee,
                note=f"Withdrawal to {acct.provider}",
            )

        # (2) The provider is told OUTSIDE the transaction. Holding a wallet
        # lock across a network call is how one slow request becomes a table
        # nobody else can write to.
        st = _stripe()
        try:
            tr = st.Transfer.create(
                amount=payout.net_cents,
                currency="usd",
                destination=acct.account_id,
                description=f"Music ConnectZ withdrawal #{payout.id}",
                # The provider's own guard: a retried request with this key is
                # the SAME transfer to them, never a second one.
                idempotency_key=key,
            )
        except Exception as exc:            # noqa: BLE001 — provider errors vary
            # (3) Refused. Give it back rather than leaving it in limbo.
            logger.exception("Payout %s refused", payout.id)
            _refund(payout, getattr(exc, "user_message", None) or exc)
            return Response({
                "detail": f"That didn't go through: {payout.failure_reason}. "
                          "Your balance hasn't changed.",
                "payout_id": payout.id,
                "quote": quote(request.user),
            }, status=status.HTTP_502_BAD_GATEWAY)

        # Coerced rather than trusted: this is a CharField, and an SDK that
        # hands back an object instead of a string would otherwise be written
        # straight into it — Django resolves the value as a query expression
        # and the payout is left PAID-but-unrecorded, which is the one state
        # that makes a withdrawal impossible to trace afterwards.
        payout.provider_ref = str(getattr(tr, "id", "") or "") or None
        payout.status = Payout.STATUS_PAID
        payout.completed_at = timezone.now()
        payout.save(update_fields=["provider_ref", "status", "completed_at"])
        return Response({
            "payout": {"id": payout.id, "amount_cents": payout.amount_cents,
                       "fee_cents": payout.fee_cents, "net_cents": payout.net_cents,
                       "status": payout.status},
            "quote": quote(request.user),
        }, status=status.HTTP_201_CREATED)


class PayoutConnectView(APIView):
    """Start (or resume) onboarding with the provider.

    We never see a bank detail. The member finishes on the provider's own
    pages, which is also where identity checks happen — including the age
    floor, which is the provider's rule rather than ours. `adult_only_reason`
    says getting paid stays open to under-18s, and it does: money still lands
    in the wallet. Moving it to a BANK is where somebody else's rules start.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        st = _stripe()
        if not st:
            return Response(
                {"detail": "Withdrawals aren't switched on yet — no payout "
                           "provider is configured on the server."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE)

        acct, _ = PayoutAccount.objects.get_or_create(user=request.user)
        try:
            if not acct.account_id:
                created = st.Account.create(
                    type="express",
                    email=request.user.email or None,
                    capabilities={"transfers": {"requested": True}},
                    metadata={"mcz_user_id": str(request.user.id),
                              "mcz_username": request.user.username},
                )
                acct.account_id = getattr(created, "id", "") or ""
                acct.save(update_fields=["account_id", "updated_at"])

            base = getattr(settings, "FRONTEND_URL", "").rstrip("/")
            link = st.AccountLink.create(
                account=acct.account_id,
                type="account_onboarding",
                refresh_url=f"{base}/royaltie?payout=retry",
                return_url=f"{base}/royaltie?payout=done",
            )
        except Exception as exc:            # noqa: BLE001
            logger.exception("Could not start payout onboarding")
            return Response({"detail": f"Couldn't start that: {exc}"[:200]},
                            status=status.HTTP_502_BAD_GATEWAY)

        return Response({"url": getattr(link, "url", ""), "account_id": acct.account_id})


class PayoutRefreshView(APIView):
    """Ask the provider whether this account can be paid yet.

    Their answer, mirrored — never our inference. Onboarding can sit for days
    on a document, so "they reached the end of the form" is not the same fact
    as "money can be sent", and only one of them is safe to act on.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        st = _stripe()
        acct = PayoutAccount.objects.filter(user=request.user).first()
        if not st or not acct or not acct.account_id:
            return Response({"quote": quote(request.user)})
        try:
            remote = st.Account.retrieve(acct.account_id)
            acct.payouts_enabled = bool(getattr(remote, "payouts_enabled", False))
            req = getattr(remote, "requirements", None) or {}
            due = req.get("currently_due") if isinstance(req, dict) else None
            acct.requirements = list(due or [])
            acct.save(update_fields=["payouts_enabled", "requirements", "updated_at"])
        except Exception:                    # noqa: BLE001
            logger.exception("Could not refresh payout account")
        return Response({"quote": quote(request.user)})
