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

from .crosspost import log_destinations, log_line
from .features import can_use, feature_map, gate_detail
from django.contrib.auth import get_user_model

from .models import Transaction, membership_for, notify
from .resources import BY_RESOURCE

User = get_user_model()

# The marks, served with the rows so the client never keeps its own copy — a
# resource with two symbols is the bug we already fixed once. They live in
# `resources.py` now rather than here: this module was the closest thing the
# server had to one place for them, which meant every other module that needed
# a mark typed the character again.
RESOURCE_EMOJI = dict(BY_RESOURCE)
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
        # Where the movement came from, when the writer said. Blank means
        # nobody said — never guessed from the note.
        "app_key": t.app_key,
        "target": t.target,
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
        # Cross-pollination, on the app that made every other balance
        # leadable-back-to and was itself the most read-only surface here. A
        # member could see "+300 🍥 referral (referrer)" and do nothing with
        # it — not tell the person, not keep it, not post it, not open the app
        # it came from.
        for r in rows:
            r["destinations"] = log_destinations(
                r, app_key=r.get("app_key", ""), target=r.get("target", ""))

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


class LogZExportView(APIView):
    """POST {ids, to} — take LogZ rows somewhere: a post, a message, a journal entry.

    A ledger you can read and not act on is the read-only surface the
    cross-pollination rule calls unfinished. This is the acting-on.

    The rows are re-read from the database by id and never taken from the
    request body. A client that could hand us the text would be a client that
    could post "+50,000 💵 royalty" over somebody's name — the whole value of
    a line from LogZ is that the platform wrote it.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        d = request.data or {}
        to = str(d.get("to", "")).lower()
        if to not in ("postz", "messagez", "journalz"):
            return Response({"detail": "to must be postz, messagez or journalz"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            ids = [int(x) for x in (d.get("ids") or [])][:PAGE]
        except (TypeError, ValueError):
            return Response({"detail": "ids must be LogZ row ids"},
                            status=status.HTTP_400_BAD_REQUEST)
        if not ids:
            return Response({"detail": "Pick at least one row."},
                            status=status.HTTP_400_BAD_REQUEST)

        rows = list(request.user.transactions.filter(id__in=ids).order_by("-created_at"))
        if not rows:
            return Response({"detail": "Those rows aren't on your ledger."},
                            status=status.HTTP_404_NOT_FOUND)
        text = "\n".join(log_line(_row(t)) for t in rows)

        if to == "journalz":
            from .models import JournalEntry
            from django.utils import timezone
            entry = JournalEntry.objects.create(
                author=request.user, day=timezone.localdate(),
                title=d.get("title") or "From LogZ",
                body=text, visibility="private")
            return Response({"to": to, "id": entry.id, "text": text,
                             "detail": "Kept in today's entry — private, as the diary always is."},
                            status=status.HTTP_201_CREATED)

        if to == "messagez":
            from .models import Message
            username = str(d.get("to_username", "")).strip()
            recipient = User.objects.filter(username__iexact=username).first() if username else None
            if not recipient:
                return Response({"detail": "Who to? Name the member this goes to.",
                                 "needs": ["to_username"]},
                                status=status.HTTP_400_BAD_REQUEST)
            if recipient.id == request.user.id:
                return Response({"detail": "That's you. Keep it in JournalZ instead."},
                                status=status.HTTP_400_BAD_REQUEST)
            msg = Message.objects.create(sender=request.user, recipient=recipient, body=text)
            notify(recipient, "message", f"@{request.user.username} sent you a LogZ line",
                   actor=request.user, item_id="logz")
            return Response({"to": to, "id": msg.id, "text": text,
                             "detail": f"Sent to @{recipient.username}."},
                            status=status.HTTP_201_CREATED)

        # PostZ. Deliberately NOT created here: a post has a price, a slot
        # limit and a whole composer, and creating one from this endpoint would
        # be spending something from a screen that never showed the cost. The
        # text is handed back for the composer to open with, which is what
        # every other `seed` destination in `crosspost` does.
        return Response({"to": to, "text": text, "seeded": True,
                         "detail": "Opening PostZ with this — the post's own price is on its button."})
