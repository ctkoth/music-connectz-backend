from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import AI_MODEL_COSTS, SPECZ_CATALOG, ai_cost, cashout_rate, limits_for
from .media import stable_media_url
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
    daily_prompt_state,
    energy_for_topup,
    ENERGY_TOPUP_MULT,
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


def platform_owner():
    """The account that receives platform revenue (e.g. OCC model charges).
    Prefers a configured owner by username/email, else the first superuser."""
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.db.models import Q
    User = get_user_model()
    usernames = [u for u in (getattr(settings, "OWNER_USERNAMES", []) or [])]
    emails = [e for e in (getattr(settings, "OWNER_EMAILS", []) or [])]
    q = Q()
    if usernames:
        q |= Q(username__in=usernames)
    if emails:
        q |= Q(email__in=emails)
    owner = User.objects.filter(q).first() if (usernames or emails) else None
    return owner or User.objects.filter(is_superuser=True).order_by("id").first()


def is_owner_candidate(user):
    """True if this account is a configured owner (by email OR username)."""
    from django.conf import settings
    if not user:
        return False
    emails = [e.lower() for e in (getattr(settings, "OWNER_EMAILS", []) or [])]
    usernames = [u.lower() for u in (getattr(settings, "OWNER_USERNAMES", []) or [])]
    return (user.email and user.email.lower() in emails) or (user.username and user.username.lower() in usernames)


def ensure_owner(user):
    """Bootstrap the platform owner by email/username (settings.OWNER_EMAILS /
    OWNER_USERNAMES). Promotes the account to staff+superuser, hands over the
    Owner badge, and keeps it at StatZ (bumping Free/Premium), never overriding
    a deliberate Debug switch."""
    from .models import TIER_FREE, TIER_PREMIUM, grant_badge
    if not is_owner_candidate(user):
        return
    if not (user.is_staff and user.is_superuser):
        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=["is_staff", "is_superuser"])
    # The Owner badge lands here rather than being gifted by hand. It is the
    # one badge whose condition is "this is whose app it is", and that is a
    # fact this function already knows — leaving it to a POST would mean the
    # owner has to gift it to themselves, and would leave the badge missing
    # on any account that got promoted before BadgeZ existed.
    tier_before = membership_for(user).tier
    grant_badge(user, "owner")
    m = membership_for(user)
    if tier_before == TIER_DEBUG and m.tier != TIER_DEBUG:
        # The badge applies StatZ the moment it lands. A deliberate Debug
        # switch outranks it, which has always been this function's rule.
        m.tier = TIER_DEBUG
        m.save(update_fields=["tier", "updated_at"])
    if m.tier in (TIER_FREE, TIER_PREMIUM):
        m.tier = TIER_STATZ
        m.save(update_fields=["tier", "updated_at"])
    return m


def credit_owner(payer, cost_cents, note):
    """Pay the platform owner for an AI run — and say so in the ledger.

    Four call sites used to bump `money_cents` directly. The money arrived and
    nothing anywhere said why, which is the exact thing LogZ exists to prevent:
    a balance that changed with no row leading back to the action that changed
    it. It is also why the intelligence royalties could not be totalled despite
    being genuinely paid — there was nothing to add up.

    Self-neutral: an owner running their own model charge moves nothing, so no
    row is written either. A ledger entry for money that didn't move would be
    its own kind of lie.

    Returns the cents credited (0 when there was nobody else to pay).
    """
    if not cost_cents:
        return 0
    owner = platform_owner()
    if not owner or owner.id == payer.id:
        return 0
    ow = wallet_for(owner)
    ow.money_cents = (ow.money_cents or 0) + cost_cents
    ow.save(update_fields=["money_cents", "updated_at"])
    Transaction.objects.create(
        user=owner, kind=Transaction.KIND_INTELLIGENCE,
        resource=Transaction.RES_MONEY,
        amount=cost_cents, amount_cents=cost_cents, note=note[:200],
    )
    return cost_cents


class OwnerRevenueView(APIView):
    """GET /api/economy/owner/revenue/ — what the platform has actually taken.

    The Owner badge's face says it receives the developer tax and the
    intelligence royalties. Both are true, and until now neither was visible
    anywhere — which is most of why the badge ended up writing them down as
    *effects*. An unseen fact reads as an unimplemented one.

    This is a READ-OUT, not a balance, and the difference is the whole point.
    The developer tax is not credited to a wallet and must not be: a member's
    wallet balance is a liability against cash the platform already holds, so
    declining to credit the tax IS how the tax is received. Crediting it again
    would book the same margin twice — once as cash held free and clear, again
    as a balance that could be cashed out.

    Contrast the AI model charges, which ARE moved wallet-to-wallet: one
    liability down, one up, total unchanged. That is why those conserve money
    and a developer-tax credit would not.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Sum
        if not is_owner(request.user):
            return Response({"detail": "Only the platform owner sees this."},
                            status=status.HTTP_403_FORBIDDEN)
        rows = Transaction.objects.exclude(dev_tax_cents=0)
        owner = platform_owner()
        royalties = Transaction.objects.filter(
            user=owner, kind=Transaction.KIND_INTELLIGENCE) if owner else Transaction.objects.none()
        return Response({
            "owner": owner.username if owner else "",
            # Every taxed movement already records what it took. Summing the
            # ledger beats storing a running total: a stored copy is how a
            # number outlives the rows that justify it.
            "dev_tax_collected_cents": rows.aggregate(n=Sum("dev_tax_cents"))["n"] or 0,
            "dev_tax_by_kind": {r["kind"]: r["n"] for r in
                                rows.values("kind").annotate(n=Sum("dev_tax_cents")).order_by()},
            "dev_tax_taxed_movements": rows.count(),
            "dev_tax_rates": DEV_TAX,
            "dev_tax_note": (
                "Received by not being paid out — a wallet balance is a liability "
                "against cash already held, so the tax never becoming a balance is "
                "the platform keeping it. It is deliberately not credited anywhere."
            ),
            # Real now. `credit_owner` writes a row for every AI charge routed
            # here, so this is a sum of the ledger rather than a read of the
            # wallet — that balance holds everything else too and would have
            # been a fake number dressed as this one.
            "intelligence_royalties_cents": royalties.aggregate(
                n=Sum("amount_cents"))["n"] or 0,
            "intelligence_royalties_runs": royalties.count(),
            # Rows only exist from the day they started being written. A total
            # that silently omits the credits made before that is a number
            # somebody would reconcile against Stripe and find short.
            "intelligence_royalties_since": (
                royalties.order_by("created_at").values_list("created_at", flat=True).first()
            ),
            "intelligence_royalties_note": (
                "Summed from the ledger, and only from when the rows began. AI "
                "charges credited before that arrived without one and are not in "
                "this figure."
            ),
            # Cross-pollination: the total leads back to the rows that made it.
            "open_in": "logz",
        })


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
        prompt_allowance, prompts_used, prompts_remaining = daily_prompt_state(request.user)
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
                "my_promptz": w.promptz,  # prepaid AI credits (persist)
                # Free daily prompts by tier (free 1 / premium 5 / statz 10) — reset daily, don't stack.
                "my_promptz_daily": prompt_allowance,
                "my_promptz_daily_used": prompts_used,
                "my_promptz_daily_remaining": prompts_remaining,
                "dev_tax_rate": m.dev_tax_rate,
            }
        )


class WalletView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Pay what's owed BEFORE reporting the balance, or the wallet screen is
        # the one place that shows a stale number.
        from .models import settle_energy
        w = settle_energy(request.user)
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
        energy_granted = energy_for_topup(request.user, amount_cents)
        w.money_cents += net
        w.energy = (w.energy or 0) + energy_granted
        w.save(update_fields=["money_cents", "energy", "updated_at"])
        Transaction.objects.create(
            user=request.user, kind=Transaction.KIND_ADD, amount_cents=net,
            dev_tax_cents=dev, note=request.data.get("note", "Add funds")[:200],
        )
        return Response(
            {
                "wallet": WalletSerializer(w).data,
                "breakdown": {
                    "gross_cents": amount_cents, "dev_tax_cents": dev, "net_cents": net, "rate": m.dev_tax_rate,
                    "energy_granted": energy_granted, "energy_mult": ENERGY_TOPUP_MULT.get(m.tier, 1),
                },
            }
        )


class MembershipView(APIView):
    """GET current tier; POST sets it (dev/testing — real upgrades go via billing)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        ensure_owner(request.user)  # self-heal owner promotion on any membership load
        m = membership_for(request.user)
        return Response({"tier": m.tier, "dev_tax_rate": m.dev_tax_rate, "rates": DEV_TAX, "lifetime": m.lifetime, "founding": m.founding, "is_owner": is_owner(request.user)})

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


class OwnerClaimView(APIView):
    """Self-serve owner promotion — succeeds only if the caller matches the
    configured OWNER_EMAILS / OWNER_USERNAMES. Idempotent fallback if the
    automatic bootstrap was missed."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not is_owner_candidate(request.user):
            return Response({"detail": "This account isn't a configured owner."}, status=status.HTTP_403_FORBIDDEN)
        m = ensure_owner(request.user)
        return Response({"promoted": True, "tier": m.tier, "is_owner": is_owner(request.user)})


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
        # Optional custom charge — e.g. an AI-score fee (rating × 10% × skill
        # price, in cents). When omitted, fall back to the flat model minimum.
        override = request.data.get("cents", None)
        if override is not None:
            try:
                cost = max(0, int(round(float(override))))
            except (TypeError, ValueError):
                cost = 0
        else:
            cost = ai_cost(model)
        if is_owner(request.user):
            cost = 0
        # A flat model run (no custom cents) is a genuine "prompt" — the tier's
        # free daily allowance covers it before any paid balance is touched.
        remaining = charge_ai_usage(request.user, cost, note=note, count_daily=(override is None))
        if remaining is None:
            w = wallet_for(request.user)
            return Response(
                {"detail": "Not enough balance for this model.", "cost_cents": cost, "money_cents": w.money_cents},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )
        # Route the charge to the platform owner as revenue (money conserved),
        # with a row saying where it came from.
        credit_owner(request.user, cost, note)
        return Response({"model": model, "cost_cents": cost, "money_cents": remaining, "money": round(remaining / 100, 2)})


class PromptzBuyView(APIView):
    """POST { cents } — spend cash to buy prepaid PromptZ at 80% of face
    ($0.80 → 100 PromptZ = a 25% bonus). 1 PromptZ = 1¢ of AI spend, applied to
    translate / OCC / profile edits / AI-rate before cash."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        pay_cents = int((request.data or {}).get("cents") or 0)
        if pay_cents <= 0:
            return Response({"detail": "cents required"}, status=status.HTTP_400_BAD_REQUEST)
        w = wallet_for(request.user)
        if w.money_cents < pay_cents:
            return Response({"detail": "Not enough balance — add funds first.", "cost_cents": pay_cents},
                            status=status.HTTP_402_PAYMENT_REQUIRED)
        from .catalog import PROMPTZ_BONUS

        w.money_cents -= pay_cents
        # Buy at 80% of face value. The rate is named in catalog.py rather than
        # written here, because it is what makes pass-through AI pricing a loss
        # — and a pricing relationship only one file can see is one nothing else
        # can price against.
        granted = round(pay_cents * PROMPTZ_BONUS)
        w.promptz = (w.promptz or 0) + granted
        w.save(update_fields=["money_cents", "promptz", "updated_at"])
        Transaction.objects.create(
            user=request.user, kind=Transaction.KIND_PURCHASE, amount_cents=-pay_cents,
            dev_tax_cents=0, note=f"Bought {granted} PromptZ 🏷️",
        )
        return Response({"wallet": WalletSerializer(w).data, "granted": granted})


class LimitsView(APIView):
    """Per-tier caps for the client to enforce (char/upload/storage), plus the
    one policy answer the client can't work out for itself."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .catalog import chars_unlimited
        from .models import third_party_ads_allowed

        m = membership_for(request.user)
        lim = dict(limits_for(m.tier))
        lim["tier"] = m.tier
        # So the client can print "Unlimited" instead of a nine-figure number.
        lim["char_limit_unlimited"] = chars_unlimited(m.tier)
        lim["dev_tax_rate"] = m.dev_tax_rate
        lim["storage_used_mb"] = round(storage_used_bytes(request.user) / MB, 2)
        # Whether a third-party ad frame may be rendered for this member.
        #
        # Answered here rather than by the client, because the client would have
        # to be told an age to work it out — and an age sent purely so the
        # browser can decide whether to show an advert is more of a member's
        # birthday travelling further than it needs to, not less. The server
        # knows; it can just say yes or no.
        #
        # `play/data-safety.md` answers "Committed to the Play Families Policy:
        # Yes". Third-party ads to a member we know to be 13-17 would make that
        # answer untrue.
        lim["third_party_ads"] = third_party_ads_allowed(request.user)
        # JournalZ's per-entry room, from the same table the diary enforces.
        # Served here as well as on `/journalz/cost/` so any screen that talks
        # about what a tier buys reads the number rather than retyping it —
        # MembershipZ's copy is where that drift starts.
        from .catalog import JOURNAL_LIMITS, journal_limits_for
        lim["journal"] = journal_limits_for(m.tier)
        lim["journal_by_tier"] = {t: v for t, v in JOURNAL_LIMITS.items()
                                  if t != TIER_DEBUG}
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
        # NOT `u.file.url`. That is the storage's own address, and on a bucket
        # it carries a signature that expires in an hour — which every caller
        # then STORES on a post, a deal or a battle entry. See media.py.
        "url": stable_media_url(u, request) or None,
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
