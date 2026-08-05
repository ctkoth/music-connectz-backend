"""LogZ — what Music ConnectZ did, and when.

Balances tell you where you are. They cannot tell you how you got there, and
until now nothing else could either: SpinaZ and Energy were written straight to
the wallet with the caller's `note` discarded, so "did my referral pay?" had no
answer short of watching a number and remembering what it used to be.

Every resource movement now lands here with its reason and its timestamp.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework import status

from .features import can_use, feature_map, gate_detail
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
    }


class LogZView(APIView):
    """GET → this member's ledger, newest first.

    `?resource=spinaz` narrows to one resource; `?limit=` caps the page.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tier = membership_for(request.user).tier
        if not can_use(tier, "logz"):
            # One wording for every gate, naming the tier AND what it buys —
            # a member is never told "upgrade" without being told to what.
            return Response(gate_detail("logz"), status=status.HTTP_403_FORBIDDEN)

        qs = request.user.transactions.all()
        resource = (request.query_params.get("resource") or "").lower()
        if resource in RESOURCE_EMOJI:
            qs = qs.filter(resource=resource)
        try:
            limit = min(PAGE, max(1, int(request.query_params.get("limit", PAGE))))
        except (TypeError, ValueError):
            limit = PAGE

        rows = [_row(t) for t in qs.order_by("-created_at")[:limit]]

        # Totals per resource across the WHOLE ledger, not just this page — a
        # running total that only counts the rows on screen is a wrong number.
        totals = {}
        for t in request.user.transactions.all().only("resource", "amount", "amount_cents"):
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
        })


class FeaturesView(APIView):
    """GET → every gated feature and whether THIS member has it.

    The client renders locks from this rather than keeping its own copy of the
    tier rules, so a gate and the UI advertising it cannot disagree.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"features": feature_map(membership_for(request.user).tier)})
