"""BudgetZ — a budget you can actually keep: money in, money out, a limit per category, what is left.

Free at every tier, typed by hand. What StatZ adds is the bank: link an account through Stripe
Financial Connections and the transactions arrive on their own. The tier buys the convenience, never
the budget — a member who cannot link a bank loses nothing they could do by hand.

* **Nothing is inferred and nothing is advice.** The screen adds up what was entered or imported.
  It does not score anybody's spending, recommend a product or call a habit good.
* **No credentials here.** The member signs in to their bank inside Stripe's own window; we keep
  Stripe's account id and a label (`BudgetBank`) and the lines it brings (`BudgetLine`).
* **A re-import never doubles** (`ext_id`), and a bank line the member deletes stays deleted only
  until the next sync — the screen says so rather than pretending otherwise.
* **Bank linking has never run against Stripe** (CI has no key). It refuses without
  `STRIPE_SECRET_KEY` rather than answering "linked".
* Erasing the account erases all of it (every table cascades from the user).
"""
import datetime as dt

from django.conf import settings
from django.db.models import Sum
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import BudgetBank, BudgetLimit, BudgetLine, TIER_DEBUG, TIER_STATZ, membership_for

DEFAULT_CATEGORIES = ["Housing", "Food", "Transport", "Gear", "Studio time", "Software", "Bills", "Fun", "Savings", "Other"]
MAX_CENTS = 100_000_000
MAX_LINES_PER_MONTH = 2000


def can_link(user):
    return membership_for(user).tier in (TIER_STATZ, TIER_DEBUG)


def _month(raw):
    try:
        y, m = str(raw or "").split("-")
        return dt.date(int(y), int(m), 1)
    except (ValueError, TypeError):
        t = dt.date.today()
        return dt.date(t.year, t.month, 1)


def _bounds(first):
    nxt = dt.date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return first, nxt


def _cat(raw):
    return " ".join(str(raw or "").replace("<", " ").replace(">", " ").split())[:40] or "Other"


def _cents(raw):
    try:
        v = int(round(float(raw) * 100))
    except (TypeError, ValueError):
        return None
    return v if 0 < v <= MAX_CENTS else None


def summary(user, first):
    lo, hi = _bounds(first)
    lines = list(BudgetLine.objects.filter(user=user, on__gte=lo, on__lt=hi)[:MAX_LINES_PER_MONTH])
    income = sum(l.amount_cents for l in lines if l.kind == "income")
    spent_by = {}
    for l in lines:
        if l.kind == "expense":
            spent_by[l.category] = spent_by.get(l.category, 0) + l.amount_cents
    limits = dict(BudgetLimit.objects.filter(user=user).values_list("category", "monthly_cents"))
    names = list(dict.fromkeys(list(limits) + list(spent_by) + DEFAULT_CATEGORIES))
    cats = [{"category": n, "limit_cents": limits.get(n), "spent_cents": spent_by.get(n, 0),
             "over": limits.get(n) is not None and spent_by.get(n, 0) > limits[n]} for n in names]
    spent = sum(spent_by.values())
    return {"month": first.strftime("%Y-%m"), "income_cents": income, "spent_cents": spent,
            "left_cents": income - spent, "categories": cats,
            "lines": [{"id": l.id, "kind": l.kind, "category": l.category, "amount_cents": l.amount_cents,
                       "on": l.on.isoformat(), "note": l.note, "source": l.source} for l in lines],
            "banks": [{"id": b.id, "label": b.label} for b in BudgetBank.objects.filter(user=user)],
            "can_link": can_link(user),
            "link_note": ("Link a bank and its transactions arrive on their own. You sign in inside Stripe's window; "
                          "we never see your bank password." if can_link(user) else
                          "Linking a bank is StatZ. Typing lines in yourself is free, and does everything else.")}


class BudgetView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(summary(request.user, _month(request.query_params.get("month"))))

    def post(self, request):
        d = request.data or {}
        kind = d.get("kind") if d.get("kind") in ("income", "expense") else "expense"
        cents = _cents(d.get("amount"))
        if cents is None:
            return Response({"detail": "Enter an amount above zero."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            on = dt.date.fromisoformat(str(d.get("on") or dt.date.today().isoformat()))
        except ValueError:
            return Response({"detail": "That date isn't valid."}, status=status.HTTP_400_BAD_REQUEST)
        lo, hi = _bounds(dt.date(on.year, on.month, 1))
        if BudgetLine.objects.filter(user=request.user, on__gte=lo, on__lt=hi).count() >= MAX_LINES_PER_MONTH:
            return Response({"detail": f"That month holds {MAX_LINES_PER_MONTH} lines already."},
                            status=status.HTTP_400_BAD_REQUEST)
        BudgetLine.objects.create(user=request.user, kind=kind, category=_cat(d.get("category")),
                                  amount_cents=cents, on=on, note=str(d.get("note", ""))[:120])
        return Response(summary(request.user, dt.date(on.year, on.month, 1)), status=status.HTTP_201_CREATED)


class BudgetLineView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        n, _ = BudgetLine.objects.filter(pk=pk, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT if n else status.HTTP_404_NOT_FOUND)


class BudgetLimitView(APIView):
    """PUT {category, amount} — set a monthly limit; amount 0 or blank clears it."""
    permission_classes = [IsAuthenticated]

    def put(self, request):
        cat = _cat((request.data or {}).get("category"))
        raw = (request.data or {}).get("amount")
        if raw in (None, "", 0, "0"):
            BudgetLimit.objects.filter(user=request.user, category=cat).delete()
        else:
            cents = _cents(raw)
            if cents is None:
                return Response({"detail": "Enter an amount above zero, or leave it blank to clear."},
                                status=status.HTTP_400_BAD_REQUEST)
            BudgetLimit.objects.update_or_create(user=request.user, category=cat, defaults={"monthly_cents": cents})
        return Response(summary(request.user, _month(request.query_params.get("month"))))


def _stripe():
    key = getattr(settings, "STRIPE_SECRET_KEY", "")
    if not key:
        return None
    import stripe
    stripe.api_key = key
    return stripe


class BudgetBankSessionView(APIView):
    """POST budgetz/bank/session/ — StatZ: open a Stripe Financial Connections session. The client
    finishes it in Stripe's window and then POSTs the linked account ids to budgetz/bank/link/."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not can_link(request.user):
            return Response({"detail": "Linking a bank is StatZ. Typing lines in yourself is free."},
                            status=status.HTTP_403_FORBIDDEN)
        stripe = _stripe()
        if not stripe:
            return Response({"detail": "Bank linking isn't switched on yet."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            cust = stripe.Customer.create(metadata={"user_id": str(request.user.id), "purpose": "budgetz"})
            s = stripe.financial_connections.Session.create(
                account_holder={"type": "customer", "customer": cust["id"]},
                permissions=["transactions"], filters={"countries": ["US"]})
        except Exception:
            return Response({"detail": "Couldn't reach Stripe. Nothing was linked — try again."},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response({"client_secret": s["client_secret"], "publishable_key": getattr(settings, "STRIPE_PUBLISHABLE_KEY", "")})


class BudgetBankLinkView(APIView):
    """POST budgetz/bank/link/ {accounts: [{id, label}]} then POST budgetz/bank/sync/ — StatZ."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not can_link(request.user):
            return Response({"detail": "Linking a bank is StatZ."}, status=status.HTTP_403_FORBIDDEN)
        for a in ((request.data or {}).get("accounts") or [])[:10]:
            if isinstance(a, dict) and str(a.get("id", "")).startswith("fca_"):
                BudgetBank.objects.get_or_create(user=request.user, stripe_account=str(a["id"])[:80],
                                                 defaults={"label": _cat(a.get("label"))[:80]})
        return Response(summary(request.user, _month(None)))


class BudgetBankSyncView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not can_link(request.user):
            return Response({"detail": "Linking a bank is StatZ."}, status=status.HTTP_403_FORBIDDEN)
        stripe = _stripe()
        if not stripe:
            return Response({"detail": "Bank linking isn't switched on yet."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        added = 0
        try:
            for b in BudgetBank.objects.filter(user=request.user):
                for t in stripe.financial_connections.Transaction.list(account=b.stripe_account, limit=100).auto_paging_iter():
                    cents = abs(int(t["amount"]))
                    if not cents or BudgetLine.objects.filter(user=request.user, ext_id=t["id"]).exists():
                        continue
                    day = dt.datetime.fromtimestamp(t["transacted_at"], dt.timezone.utc).date()
                    BudgetLine.objects.create(user=request.user, kind="expense" if t["amount"] < 0 else "income",
                                              category="Other", amount_cents=cents, on=day,
                                              note=str(t.get("description", ""))[:120], source="bank", ext_id=t["id"])
                    added += 1
        except Exception:
            return Response({"detail": "Couldn't read the bank through Stripe. Nothing was lost — try again.",
                             "added": added}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({**summary(request.user, _month(None)), "added": added})


class BudgetBankUnlinkView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        n, _ = BudgetBank.objects.filter(pk=pk, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT if n else status.HTTP_404_NOT_FOUND)
