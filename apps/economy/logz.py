"""LogZ — what Music ConnectZ did, and when.

Balances tell you where you are. They cannot tell you how you got there, and
until now nothing else could either: SpinaZ and Energy were written straight to
the wallet with the caller's `note` discarded, so "did my referral pay?" had no
answer short of watching a number and remembering what it used to be.

Every resource movement now lands here with its reason and its timestamp.
"""
from datetime import timedelta

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.utils import timezone

from .catalog import LOGZ_HISTORY_DAYS, logz_history_days
from .features import feature_map
from .models import Transaction, membership_for

# The marks from CLAUDE.md. Served with the rows so the client never keeps its
# own copy — a resource with two symbols is the bug we already fixed once.
RESOURCE_EMOJI = {
    Transaction.RES_MONEY: "💵",
    Transaction.RES_SPINAZ: "🍥",
    Transaction.RES_ENERGY: "⚡",
    Transaction.RES_PROMPTZ: "🏷️",
    Transaction.RES_XP: "⭐",
}
PAGE = 100


def _row(t):
    resource = t.resource or Transaction.RES_MONEY
    # Money is stored in cents; everything else is already whole units.
    amount = t.amount if t.amount else t.amount_cents
    return {
        "id": t.id,
        "at": t.created_at,
        "kind": t.kind,
        "resource": resource,
        "emoji": RESOURCE_EMOJI.get(resource, ""),
        "amount": amount,
        # Pre-rendered the way the paradigm wants it — signed, with the mark.
        "display": f"{'+' if amount > 0 else ''}{amount / 100:.2f} 💵"
                   if resource == Transaction.RES_MONEY
                   else f"{'+' if amount > 0 else ''}{amount} {RESOURCE_EMOJI.get(resource, '')}",
        "note": t.note,
        # Nothing is a dead end: a balance leads back to the action that moved
        # it. Empty when the writer did not record one — an absent link is
        # honest, a guessed one sends somebody to the wrong app.
        "open_in": t.open_in or "",
    }


class LogZView(APIView):
    """GET → this member's ledger, newest first.

    `?resource=spinaz` narrows to one resource; `?limit=` caps the page.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tier = membership_for(request.user).tier
        # LogZ is not gated. It was Premium-only, which meant a Free member
        # could not find out where their own SpinaZ went — the "it may never
        # say whether" rule broken on the member's own record, while
        # `occ_spec.py` was already advertising SpinaZ and Energy as things a
        # Free member opens IN LOGZ. What laddders is DEPTH.
        days = logz_history_days(tier)
        since = timezone.now() - timedelta(days=days) if days else None

        qs = request.user.transactions.all()
        if since:
            qs = qs.filter(created_at__gte=since)
        resource = (request.query_params.get("resource") or "").lower()
        if resource in RESOURCE_EMOJI:
            qs = qs.filter(resource=resource)
        try:
            limit = min(PAGE, max(1, int(request.query_params.get("limit", PAGE))))
        except (TypeError, ValueError):
            limit = PAGE

        rows = [_row(t) for t in qs.order_by("-created_at")[:limit]]

        # Totals per resource across the whole VISIBLE ledger, not just this
        # page — a running total that only counts the rows on screen is a wrong
        # number. It counts what this tier can see, for the same reason: a
        # total over rows the member is not shown cannot be checked.
        totals = {}
        window = request.user.transactions.all()
        if since:
            window = window.filter(created_at__gte=since)
        for t in window.only("resource", "amount", "amount_cents"):
            r = t.resource or Transaction.RES_MONEY
            totals[r] = totals.get(r, 0) + (t.amount if t.amount else t.amount_cents)

        return Response({
            "entries": rows,
            "totals": [
                {"resource": r, "emoji": RESOURCE_EMOJI.get(r, ""), "amount": v}
                for r, v in sorted(totals.items())
            ],
            "resources": [
                {"key": k, "emoji": v, "label": dict(Transaction.RESOURCE_CHOICES).get(k, k)}
                for k, v in RESOURCE_EMOJI.items()
            ],
            "count": qs.count(),
            # What this tier can see, said in the unit a member can check —
            # days — plus the whole ladder, so the number on screen and the
            # reason for it arrive together.
            "history_days": days,
            "history_label": "everything" if not days else f"the last {days} days",
            "history_ladder": [
                {"tier": t, "days": d, "label": "everything" if not d else f"{d} days"}
                for t, d in LOGZ_HISTORY_DAYS.items()
            ],
            "tier": tier,
            # Rows older than the window still exist and still count; saying so
            # is the difference between a limit and a disappearance.
            "hidden_by_tier": (
                request.user.transactions.filter(created_at__lt=since).count() if since else 0
            ),
        })


class FeaturesView(APIView):
    """GET → every gated feature and whether THIS member has it.

    The client renders locks from this rather than keeping its own copy of the
    tier rules, so a gate and the UI advertising it cannot disagree.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"features": feature_map(membership_for(request.user).tier)})
