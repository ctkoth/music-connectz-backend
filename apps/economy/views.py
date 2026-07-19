from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import AI_MODEL_COSTS, SPECZ_CATALOG, ai_cost, cashout_rate, limits_for
from .models import (
    DEV_TAX,
    MB,
    TIER_CHOICES,
    TIER_DEBUG,
    TIER_STATZ,
    Membership,
    RoyaltyEntry,
    SpecZPurchase,
    Transaction,
    Upload,
    charge_ai_usage,
    membership_for,
    split_cents,
    storage_used_bytes,
    wallet_for,
)
from .serializers import TransactionSerializer, WalletSerializer

User = get_user_model()
VALID_TIERS = {t[0] for t in TIER_CHOICES}
# The owner tier ("debug") is god-mode and must never be self-assignable by a
# normal member — only the platform owner / staff.
OWNER_ONLY_TIERS = {TIER_DEBUG}


def is_owner(user):
    return bool(user and (user.is_superuser or user.is_staff))


def ensure_owner(user):
    """Bootstrap the platform owner by email (settings.OWNER_EMAILS). On first
    detection we promote the account to staff+superuser and, if it's still on
    the Free default, set StatZ — then it's freely modifiable afterward."""
    from django.conf import settings
    from .models import TIER_FREE
    emails = getattr(settings, "OWNER_EMAILS", []) or []
    if not user or not user.email or user.email.lower() not in emails:
        return
    if not (user.is_staff and user.is_superuser):
        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=["is_staff", "is_superuser"])
        m = membership_for(user)
        if m.tier == TIER_FREE:  # first-time bootstrap; owner can change later
            m.tier = TIER_STATZ
            m.save(update_fields=["tier", "updated_at"])


class StatsView(APIView):
    """Powers the frontend CommunityBar + tier gating: /api/auth/stats/."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        ensure_owner(request.user)  # promote the configured owner account
        w = wallet_for(request.user)
        m = membership_for(request.user)
        # Presence: mark this member seen now, then count everyone seen recently.
        now = timezone.now()
        Membership.objects.filter(pk=m.pk).update(last_seen=now)
        online_cutoff = now - timedelta(minutes=5)
        online_qs = Membership.objects.filter(last_seen__gte=online_cutoff)
        online_now = online_qs.count() or 1
        online_members = list(
            online_qs.exclude(user=request.user).values_list("user__username", flat=True)[:50]
        )
        return Response(
            {
                "total_members": User.objects.count(),
                "online_now": online_now,
                "online_members": [request.user.username] + online_members,
                "is_owner": is_owner(request.user),
                "my_tier": m.tier,
                "my_money": w.money,
                "my_energy": w.energy,
                "my_spinaz": w.spinaz,
                "dev_tax_rate": m.dev_tax_rate,
            }
        )


class WalletView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        w = wallet_for(request.user)
        recent = request.user.transactions.all()[:50]
        return Response({"wallet": WalletSerializer(w).data, "transactions": TransactionSerializer(recent, many=True).data})


class AddFundsView(APIView):
    """Add funds — developer tax enforced server-side; net credited to wallet."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            amount_cents = int(request.data.get("amount_cents"))
        except (TypeError, ValueError):
            return Response({"detail": "amount_cents (integer) required"}, status=status.HTTP_400_BAD_REQUEST)
        if amount_cents <= 0:
            return Response({"detail": "amount must be positive"}, status=status.HTTP_400_BAD_REQUEST)

        m = membership_for(request.user)
        w = wallet_for(request.user)
        dev, net = split_cents(amount_cents, m.dev_tax_rate)
        w.money_cents += net
        w.save(update_fields=["money_cents", "updated_at"])
        Transaction.objects.create(
            user=request.user, kind=Transaction.KIND_ADD, amount_cents=net,
            dev_tax_cents=dev, note=request.data.get("note", "Add funds")[:200],
        )
        return Response(
            {
                "wallet": WalletSerializer(w).data,
                "breakdown": {"gross_cents": amount_cents, "dev_tax_cents": dev, "net_cents": net, "rate": m.dev_tax_rate},
            }
        )


class MembershipView(APIView):
    """GET current tier; POST sets it (dev/testing — real upgrades go via billing)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        m = membership_for(request.user)
        return Response({"tier": m.tier, "dev_tax_rate": m.dev_tax_rate, "rates": DEV_TAX, "lifetime": m.lifetime, "founding": m.founding})

    def post(self, request):
        tier = str(request.data.get("tier", "")).lower()
        if tier not in VALID_TIERS:
            return Response({"detail": f"tier must be one of {sorted(VALID_TIERS)}"}, status=status.HTTP_400_BAD_REQUEST)
        if tier in OWNER_ONLY_TIERS and not is_owner(request.user):
            return Response({"detail": "Debug tier is owner-only."}, status=status.HTTP_403_FORBIDDEN)
        m = membership_for(request.user)
        m.tier = tier
        m.save(update_fields=["tier", "updated_at"])
        return Response({"tier": m.tier, "dev_tax_rate": m.dev_tax_rate})


class AIChargeView(APIView):
    """Charge the minimum cost to cover an AI model run (OCC / Corey GPT etc.).

    Pure pass-through, no developer tax. Owner/debug runs are free. Returns the
    new balance, or 402 when the member can't afford the model.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Advertise the price list so the client can show costs.
        return Response({"costs": AI_MODEL_COSTS})

    def post(self, request):
        model = str(request.data.get("model", "corey-gpt")).lower()
        note = str(request.data.get("note", "OCC AI usage"))[:200]
        cost = 0 if is_owner(request.user) else ai_cost(model)
        remaining = charge_ai_usage(request.user, cost, note=note)
        if remaining is None:
            w = wallet_for(request.user)
            return Response(
                {"detail": "Not enough balance for this model.", "cost_cents": cost, "money_cents": w.money_cents},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )
        return Response({"model": model, "cost_cents": cost, "money_cents": remaining, "money": round(remaining / 100, 2)})


class LimitsView(APIView):
    """Per-tier caps for the client to enforce (char/upload/storage)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        m = membership_for(request.user)
        lim = dict(limits_for(m.tier))
        lim["tier"] = m.tier
        lim["dev_tax_rate"] = m.dev_tax_rate
        lim["storage_used_mb"] = round(storage_used_bytes(request.user) / MB, 2)
        return Response(lim)


class SpecZView(APIView):
    """GET the SpecZ catalog with owned flags; POST buys an item (StatZ only)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        owned = set(request.user.specz_purchases.values_list("item_id", flat=True))
        items = [
            {"id": iid, "name": d["name"], "price_cents": d["price_cents"], "owned": iid in owned}
            for iid, d in SPECZ_CATALOG.items()
        ]
        return Response({"items": items})

    def post(self, request):
        m = membership_for(request.user)
        if m.tier != TIER_STATZ:
            return Response({"detail": "SpecZ is a StatZ-only marketplace"}, status=status.HTTP_403_FORBIDDEN)
        item_id = str(request.data.get("item_id", ""))
        item = SPECZ_CATALOG.get(item_id)
        if not item:
            return Response({"detail": "unknown item"}, status=status.HTTP_400_BAD_REQUEST)
        if request.user.specz_purchases.filter(item_id=item_id).exists():
            return Response({"detail": "already owned"}, status=status.HTTP_409_CONFLICT)
        w = wallet_for(request.user)
        price = item["price_cents"]
        if w.money_cents < price:
            return Response({"detail": "insufficient balance"}, status=status.HTTP_402_PAYMENT_REQUIRED)
        dev, _ = split_cents(price, m.dev_tax_rate)  # developer tax recorded on the sale
        w.money_cents -= price
        w.save(update_fields=["money_cents", "updated_at"])
        SpecZPurchase.objects.create(user=request.user, item_id=item_id, price_cents=price, dev_tax_cents=dev)
        Transaction.objects.create(
            user=request.user, kind=Transaction.KIND_PURCHASE, amount_cents=-price,
            dev_tax_cents=dev, note=f"SpecZ: {item['name']}",
        )
        return Response({"wallet": WalletSerializer(w).data, "item_id": item_id, "dev_tax_cents": dev})


class RoyaltiesView(APIView):
    """GET royalty balance + ledger."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        w = wallet_for(request.user)
        entries = [
            {"kind": e.kind, "amount_cents": e.amount_cents, "tax_cents": e.tax_cents, "source": e.source, "created_at": e.created_at}
            for e in request.user.royalty_entries.all()[:50]
        ]
        return Response({"royalties_cents": w.royalties_cents, "royalties": w.royalties, "entries": entries})


class RoyaltyAccrueView(APIView):
    """Accrue royalties to a user (called when their media earns; open for testing)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            amount_cents = int(request.data.get("amount_cents"))
        except (TypeError, ValueError):
            return Response({"detail": "amount_cents (integer) required"}, status=status.HTTP_400_BAD_REQUEST)
        if amount_cents <= 0:
            return Response({"detail": "amount must be positive"}, status=status.HTTP_400_BAD_REQUEST)
        w = wallet_for(request.user)
        w.royalties_cents += amount_cents
        w.save(update_fields=["royalties_cents", "updated_at"])
        RoyaltyEntry.objects.create(
            user=request.user, kind=RoyaltyEntry.KIND_ACCRUAL, amount_cents=amount_cents,
            source=str(request.data.get("source", ""))[:200],
        )
        return Response({"royalties_cents": w.royalties_cents, "royalties": w.royalties})


class RoyaltyCashoutView(APIView):
    """Cash out royalties into the wallet, applying the plan's tax.

    Plans: instant (15%), weekly (per-tier 10/5/2), monthly (1%), quarterly (0%).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        plan = str(request.data.get("plan", "")).lower()
        m = membership_for(request.user)
        rate = cashout_rate(plan, m.tier)
        if rate is None:
            return Response({"detail": "plan must be instant|weekly|monthly|quarterly"}, status=status.HTTP_400_BAD_REQUEST)
        w = wallet_for(request.user)
        gross = w.royalties_cents
        if gross <= 0:
            return Response({"detail": "no royalties to cash out"}, status=status.HTTP_400_BAD_REQUEST)
        tax = round(gross * rate)
        net = gross - tax
        w.royalties_cents = 0
        w.money_cents += net
        w.save(update_fields=["royalties_cents", "money_cents", "updated_at"])
        RoyaltyEntry.objects.create(user=request.user, kind=RoyaltyEntry.KIND_CASHOUT, amount_cents=-gross, tax_cents=tax, source=f"{plan} cashout")
        Transaction.objects.create(user=request.user, kind=Transaction.KIND_ROYALTY, amount_cents=net, dev_tax_cents=tax, note=f"Royalty cashout ({plan})")
        return Response({"wallet": WalletSerializer(w).data, "breakdown": {"gross_cents": gross, "tax_cents": tax, "net_cents": net, "rate": rate, "plan": plan}})


def _upload_dict(u, request):
    return {
        "id": u.id,
        "name": u.name,
        "size_bytes": u.size_bytes,
        "size_mb": round(u.size_bytes / MB, 2),
        "content_type": u.content_type,
        "url": request.build_absolute_uri(u.file.url) if u.file else None,
        "created_at": u.created_at,
    }


def _storage_summary(user, tier):
    lim = limits_for(tier)
    used = storage_used_bytes(user)
    cap = lim["storage_mb"] * MB
    return {
        "storage_used_mb": round(used / MB, 2),
        "storage_mb": lim["storage_mb"],
        "upload_mb": lim["upload_mb"],
        "storage_free_mb": round(max(cap - used, 0) / MB, 2),
    }


class UploadsView(APIView):
    """GET lists the user's uploads + storage summary; POST uploads one file.

    Enforces two per-tier caps: single-file size (upload_mb) and total
    account storage (storage_mb). Mirrors the client-side checks so the
    server is the real gate.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        m = membership_for(request.user)
        uploads = [_upload_dict(u, request) for u in request.user.uploads.all()[:200]]
        return Response({"uploads": uploads, **_storage_summary(request.user, m.tier)})

    def post(self, request):
        f = request.FILES.get("file")
        if not f:
            return Response({"detail": "file (multipart) required"}, status=status.HTTP_400_BAD_REQUEST)
        m = membership_for(request.user)
        lim = limits_for(m.tier)

        if f.size > lim["upload_mb"] * MB:
            return Response(
                {"detail": f"file exceeds the {lim['upload_mb']}MB per-upload limit for {m.tier}", **_storage_summary(request.user, m.tier)},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        used = storage_used_bytes(request.user)
        if used + f.size > lim["storage_mb"] * MB:
            return Response(
                {"detail": f"upload would exceed your {lim['storage_mb']}MB storage quota", **_storage_summary(request.user, m.tier)},
                status=status.HTTP_409_CONFLICT,
            )

        u = Upload.objects.create(
            user=request.user, file=f, name=f.name[:255], size_bytes=f.size,
            content_type=getattr(f, "content_type", "")[:120],
        )
        return Response(
            {"upload": _upload_dict(u, request), **_storage_summary(request.user, m.tier)},
            status=status.HTTP_201_CREATED,
        )


class UploadDetailView(APIView):
    """DELETE removes an upload and frees its storage."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        u = request.user.uploads.filter(pk=pk).first()
        if not u:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        u.file.delete(save=False)  # remove the file from storage
        u.delete()
        m = membership_for(request.user)
        return Response(_storage_summary(request.user, m.tier))
