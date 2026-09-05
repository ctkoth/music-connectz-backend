from datetime import timedelta

import re

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import (AI_MODEL_COSTS, SPECZ_APP_KEYS, SPECZ_APPS,
                      SPECZ_LABEL_MAX, SPECZ_PRICE_SPINAZ, SPECZ_VALUE_MAX,
                      ai_cost, cashout_rate, limits_for)
from .media import stable_media_url
from .models import (
    DEV_TAX,
    FUNNEL_KINDS,
    MB,
    TIER_CHOICES,
    TIER_DEBUG,
    TIER_STATZ,
    FunnelEvent,
    Membership,
    RoyaltyEntry,
    SpecZPurchase,
    Transaction,
    Upload,
    charge_ai_usage,
    DAILY_PROMPT_MAX_CENTS,
    daily_prompt_state,
    energy_for_topup,
    ENERGY_TOPUP_MULT,
    log_resource,
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
                # Free daily prompts by tier (free 3 / premium 5 / statz 10) — reset daily, don't stack.
                "my_promptz_daily": prompt_allowance,
                # What one of them is worth. Published because "you have 3 left"
                # is not the whole price when a dearer engine is billed anyway.
                "my_promptz_daily_max_cents": DAILY_PROMPT_MAX_CENTS,
                "my_promptz_daily_used": prompts_used,
                "my_promptz_daily_remaining": prompts_remaining,
                "dev_tax_rate": m.dev_tax_rate,
            }
        )


class PublicStatsView(APIView):
    """Real member/online counts for a visitor who has no session yet.

    StatsView (above) can't serve this: it's IsAuthenticated, and it marks
    the CALLER as seen as a side effect of being read — so a public caller
    with no membership row would either 500 or (worse) manufacture one.
    This reads the same two numbers and nothing else: no username list, no
    wallet, no per-member anything. Real counts or none — see CLAUDE.md on
    substance over decoration; a landing page showing a fake community size
    would be exactly the kind of number that "could look good without being
    good."
    """

    permission_classes = [AllowAny]

    def get(self, request):
        online_cutoff = timezone.now() - timedelta(minutes=5)
        online_now = Membership.objects.filter(last_seen__gte=online_cutoff).count()
        return Response({
            "total_members": User.objects.count(),
            "online_now": online_now,
        })


# A channel name: letters, digits, dash, underscore. Anything else is not a
# channel, it is somebody putting data in a URL.
_SRC_OK = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")


class FunnelEventView(APIView):
    """One step of the join funnel, logged by a visitor who may have no
    account yet: POST /api/auth/funnel/.

    Before this, nothing on the logged-out path was measured at all — "why
    isn't anybody joining" had no data behind it, only guesses. `kind` is
    checked against FUNNEL_KINDS so a client typo can't silently open a new,
    never-analysed event type; `meta` is checked against a small per-kind
    allowlist so this never becomes a place free-typed text (and therefore
    PII) can land by accident.
    """

    permission_classes = [AllowAny]

    ALLOWED_KINDS = {k for k, _ in FUNNEL_KINDS}
    # Per kind, the only meta keys accepted and how each is coerced. Anything
    # else in the posted meta is dropped, not stored.
    # Where somebody came FROM. A `?src=` on any entry URL, kept to a short
    # slug so it is a channel name and never a tracking payload.
    #
    # Without this the funnel counts arrivals and cannot say which of them a
    # given post, flyer or ad produced — so every channel looks identical at
    # zero, and the first thing marketing money buys is an unanswerable
    # question. It is deliberately NOT a full UTM set: source is the one field
    # that changes a decision, and campaign/medium/term/content would be four
    # more columns nobody reads.
    _SRC = lambda v: (str(v).strip().lower()[:24] or None) if _SRC_OK.match(str(v).strip().lower()[:24] or "") else None

    META_SHAPE = {
        "landing_view": {"src": _SRC},
        "try_view": {"app_key": lambda v: v if v in ("singz", "rapz") else None,
                     "src": _SRC},
        "try_scored": {"app_key": lambda v: v if v in ("singz", "rapz") else None,
                       "src": _SRC},
        "try_shared": {"app_key": lambda v: v if v in ("singz", "rapz") else None},
        "register_view": {
            "has_ref": lambda v: bool(v),
            "has_trial": lambda v: bool(v),
            "src": _SRC,
        },
        "registered": {"src": _SRC},
    }

    def post(self, request):
        kind = str(request.data.get("kind") or "")
        anon_id = str(request.data.get("anon_id") or "").strip()[:64]
        if kind not in self.ALLOWED_KINDS or not anon_id:
            return Response({"detail": "Invalid event."}, status=status.HTTP_400_BAD_REQUEST)

        raw_meta = request.data.get("meta") or {}
        shape = self.META_SHAPE.get(kind, {})
        meta = {}
        if isinstance(raw_meta, dict):
            for key, coerce in shape.items():
                if key in raw_meta:
                    value = coerce(raw_meta[key])
                    if value is not None:
                        meta[key] = value

        FunnelEvent.objects.create(kind=kind, anon_id=anon_id, meta=meta)
        # 204: there is nothing for the client to do with the response, and a
        # beacon-style call (sendBeacon, fire-and-forget) never reads the body.
        return Response(status=status.HTTP_204_NO_CONTENT)


class FunnelSummaryView(APIView):
    """Owner-only read of the join funnel counts: GET /api/auth/funnel/summary/.

    Real counts of real events, nothing modeled or estimated — the same
    substance-over-decoration rule the rest of this file follows for scores
    and ratings applies here too: a funnel number that could look fine
    without the funnel actually working would be worse than no number.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        ensure_owner(request.user)  # promote the configured owner account, as StatsView does
        if not is_owner(request.user):
            return Response({"detail": "Only the platform owner sees this."},
                            status=status.HTTP_403_FORBIDDEN)
        days = min(max(int(request.query_params.get("days") or 30), 1), 90)
        since = timezone.now() - timedelta(days=days)
        rows = FunnelEvent.objects.filter(created_at__gte=since)

        steps = {}
        for kind, label in FUNNEL_KINDS:
            qs = rows.filter(kind=kind)
            steps[kind] = {
                "label": label,
                "events": qs.count(),
                # Unique browsers reaching this step — the number that
                # actually answers "how many people," not "how many clicks."
                "unique": qs.values("anon_id").distinct().count(),
            }

        # Conversion relative to the top of the funnel actually measured —
        # landing_view unless nobody hit it yet (e.g. only /try was shared
        # directly), in which case the largest step stands in as the base
        # rather than dividing by zero.
        base_kind = "landing_view" if steps["landing_view"]["unique"] else max(
            steps, key=lambda k: steps[k]["unique"]
        )
        base = steps[base_kind]["unique"] or 1
        for kind in steps:
            steps[kind]["pct_of_base"] = round(100 * steps[kind]["unique"] / base, 1)

        # Per channel. A count of arrivals that cannot say WHERE THEY CAME FROM
        # makes every channel look identical at zero, which is exactly the
        # state this platform is in — and the first thing marketing money buys
        # is otherwise an unanswerable question.
        #
        # Counted on unique browsers per source, and carried through to the
        # steps that matter: reaching the trial, getting a score, registering.
        # A source with arrivals and no scores is a channel sending the wrong
        # people; one with scores and no registers is a door problem, not a
        # traffic problem, and those need opposite responses.
        by_src = {}
        for row in rows.exclude(meta__src=None).values("kind", "anon_id", "meta"):
            src = (row["meta"] or {}).get("src")
            if not src:
                continue
            entry = by_src.setdefault(src, {k: set() for k, _ in FUNNEL_KINDS})
            entry[row["kind"]].add(row["anon_id"])
        sources = sorted(
            ({"src": src,
              **{k: len(v) for k, v in kinds.items()},
              "total": len(set().union(*kinds.values())) if any(kinds.values()) else 0}
             for src, kinds in by_src.items()),
            key=lambda r: -r["total"],
        )

        return Response({
            "days": days,
            "since": since,
            "base_kind": base_kind,
            "steps": steps,
            "sources": sources,
            # Said out loud so an empty list reads as "nothing tagged" rather
            # than "no traffic" — two very different problems.
            "sources_note": ("Add ?src=<channel> to any link you post. Untagged "
                             "arrivals are counted in the steps above but cannot "
                             "be attributed to a channel."),
        })


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


class PromptzConvertView(APIView):
    """GET / POST { spinaz } — turn earned SpinaZ into prepaid PromptZ at
    catalog.SPINAZ_PER_PROMPTZ to 1.

    GET states the rate and what the member's balance is worth BEFORE they
    spend it, because a price discovered by paying it is a bill. POST does it.
    """

    permission_classes = [IsAuthenticated]

    def _rate(self, w):
        from .catalog import SPINAZ_PER_PROMPTZ
        have = max(0, w.spinaz or 0)
        return {
            "spinaz_per_promptz": SPINAZ_PER_PROMPTZ,
            "spinaz": have,
            # What pressing it would get them, at everything they hold.
            "max_promptz": have // SPINAZ_PER_PROMPTZ,
            "note": f"{SPINAZ_PER_PROMPTZ} 🍥 → 1 🏷️. Earn 🍥 by rating, "
                    f"referring and OfferZ — no card needed.",
        }

    def get(self, request):
        return Response(self._rate(wallet_for(request.user)))

    def post(self, request):
        from .catalog import SPINAZ_PER_PROMPTZ

        spend = int((request.data or {}).get("spinaz") or 0)
        if spend <= 0:
            return Response({"detail": "spinaz required"}, status=status.HTTP_400_BAD_REQUEST)
        # Refuse a spend that would round down to nothing rather than taking it
        # and granting zero — a conversion that silently eats 9 🍥 is theft with
        # a rounding excuse.
        if spend < SPINAZ_PER_PROMPTZ:
            return Response(
                {"detail": f"That converts to nothing — {SPINAZ_PER_PROMPTZ} 🍥 is the "
                           f"smallest that buys 1 🏷️.",
                 "spinaz_per_promptz": SPINAZ_PER_PROMPTZ},
                status=status.HTTP_400_BAD_REQUEST)
        w = wallet_for(request.user)
        if (w.spinaz or 0) < spend:
            return Response({"detail": f"That's {spend} 🍥 and you have {w.spinaz or 0}.",
                             "spinaz": w.spinaz or 0},
                            status=status.HTTP_402_PAYMENT_REQUIRED)
        # Charge only for whole PromptZ. The remainder stays in their wallet.
        granted = spend // SPINAZ_PER_PROMPTZ
        charged = granted * SPINAZ_PER_PROMPTZ
        w.spinaz -= charged
        w.promptz = (w.promptz or 0) + granted
        w.save(update_fields=["spinaz", "promptz", "updated_at"])
        Transaction.objects.create(
            user=request.user, kind=Transaction.KIND_PURCHASE, amount_cents=0,
            dev_tax_cents=0, note=f"−{charged} 🍥 → +{granted} 🏷️",
        )
        return Response({"wallet": WalletSerializer(w).data,
                         "granted": granted, "charged": charged,
                         **self._rate(w)})


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
    """GET your SpecZ and what one costs; POST writes one; DELETE removes one.

    A SpecZ is a label and a value the member writes and attaches to an app —
    "Preferred BPM: 140-150, dark strings" on PostZ. It was authored in the tab
    and saved to `localStorage`: no API call, no balance touched, nothing on
    the server. Meanwhile MembershipZ sold the SpecZ marketplace as THE
    StatZ-only perk, so the one thing advertised as worth a subscription was
    the one thing that charged nothing and did not survive a new browser.
    """

    permission_classes = [IsAuthenticated]

    def _mine(self, user):
        return [
            {"id": p.id, "app_key": p.app_key, "label": p.label, "value": p.value,
             "price_spinaz": p.price_spinaz, "created_at": p.created_at}
            for p in user.specz_purchases.all()[:200]
        ]

    def get(self, request):
        w = wallet_for(request.user)
        have = w.spinaz or 0
        return Response({
            "items": self._mine(request.user),
            "price_spinaz": SPECZ_PRICE_SPINAZ,
            "spinaz": have,
            # Whether they can afford it travels WITH the price, so the tab
            # states it on the button instead of after it is pressed.
            "affordable": have >= SPECZ_PRICE_SPINAZ,
            "apps": SPECZ_APPS,
            "label_max": SPECZ_LABEL_MAX,
            "value_max": SPECZ_VALUE_MAX,
            "tier": membership_for(request.user).tier,
            "tier_required": TIER_STATZ,
        })

    def post(self, request):
        if membership_for(request.user).tier != TIER_STATZ:
            return Response({"detail": "SpecZ is a StatZ-only marketplace"},
                            status=status.HTTP_403_FORBIDDEN)
        d = request.data or {}
        app_key = str(d.get("app_key", "")).strip()
        if app_key not in SPECZ_APP_KEYS:
            return Response({"detail": "Pick an app to attach it to.",
                             "apps": SPECZ_APPS}, status=status.HTTP_400_BAD_REQUEST)
        label = str(d.get("label", "")).strip()
        value = str(d.get("value", "")).strip()
        if not label or not value:
            return Response({"detail": "A SpecZ needs both a label and a value."},
                            status=status.HTTP_400_BAD_REQUEST)
        # Refuse over-length rather than silently truncating. A save handler
        # that quietly cuts what somebody typed and answers "saved" is the
        # worst bug class in this app and has shipped twice.
        if len(label) > SPECZ_LABEL_MAX or len(value) > SPECZ_VALUE_MAX:
            return Response(
                {"detail": f"Label is up to {SPECZ_LABEL_MAX} characters and value up to {SPECZ_VALUE_MAX}.",
                 "label_max": SPECZ_LABEL_MAX, "value_max": SPECZ_VALUE_MAX},
                status=status.HTTP_400_BAD_REQUEST)
        w = wallet_for(request.user)
        have = w.spinaz or 0
        if have < SPECZ_PRICE_SPINAZ:
            # Name both numbers. "Insufficient balance" makes somebody go and
            # count their own SpinaZ to work out how short they are.
            return Response(
                {"detail": f"That's {SPECZ_PRICE_SPINAZ} 🍥 and you have {have}.",
                 "price_spinaz": SPECZ_PRICE_SPINAZ, "spinaz": have},
                status=status.HTTP_402_PAYMENT_REQUIRED)
        # Charge only once everything above has passed, so a refused SpecZ is
        # never a paid one — the rule the coach bills on.
        w.spinaz = have - SPECZ_PRICE_SPINAZ
        w.save(update_fields=["spinaz", "updated_at"])
        p = SpecZPurchase.objects.create(
            user=request.user, app_key=app_key, label=label, value=value,
            price_spinaz=SPECZ_PRICE_SPINAZ,
        )
        # Through log_resource so it lands in LogZ as a SpinaZ movement with
        # its reason, like every other spend. A purchase that moves a balance
        # and leaves no row is how "where did my SpinaZ go" starts.
        log_resource(request.user, Transaction.RES_SPINAZ, -SPECZ_PRICE_SPINAZ,
                     f"SpecZ on {app_key}: {label}")
        return Response({"item": {"id": p.id, "app_key": p.app_key, "label": p.label,
                                  "value": p.value, "price_spinaz": p.price_spinaz,
                                  "created_at": p.created_at},
                         "wallet": WalletSerializer(w).data, "spinaz": w.spinaz},
                        status=status.HTTP_201_CREATED)

    def delete(self, request, pk=None):
        p = request.user.specz_purchases.filter(pk=pk).first()
        if not p:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        p.delete()
        # Deliberately no refund, and the tab says so before the button. Buying
        # it back costs the same as buying it did; a delete that quietly
        # returned the SpinaZ would make the price meaningless.
        return Response({"deleted": pk, "refunded_spinaz": 0,
                         "spinaz": wallet_for(request.user).spinaz})


class RoyaltiesView(APIView):
    """GET royalty balance, ledger, and what each cashout plan would actually pay.

    The plans ship WITH their arithmetic already done for this member. Cashing
    out costs a percentage that depends on the plan and on the member's tier,
    so a client that wanted to state the price before the button — which is the
    rule — would otherwise have to hold its own copy of the tax table, and a
    tier number retyped in the client is exactly how "20 free prompts" reached
    nine places and drifted.

    So the server answers the whole question: for this balance, at this tier,
    each plan's rate, what it takes, and what lands. Same shape as the
    KeyConnectZ allowance ladder — publish the ladder before either button is
    pressed, so "quarterly keeps all of it" is a thing the member can SEE
    rather than a thing they discover by picking the wrong one.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        w = wallet_for(request.user)
        tier = membership_for(request.user).tier
        gross = w.royalties_cents
        plans = []
        for plan in ("instant", "weekly", "monthly", "quarterly"):
            rate = cashout_rate(plan, tier)
            tax = round(gross * rate)
            plans.append({
                "plan": plan,
                "rate": rate,
                "rate_percent": round(rate * 100, 2),
                # The two numbers the member is actually choosing between.
                "tax_cents": tax,
                "net_cents": gross - tax,
            })
        entries = [
            {"kind": e.kind, "amount_cents": e.amount_cents, "tax_cents": e.tax_cents, "source": e.source, "created_at": e.created_at}
            for e in request.user.royalty_entries.all()[:50]
        ]
        return Response({
            "royalties_cents": gross, "royalties": w.royalties,
            "tier": tier, "plans": plans, "entries": entries,
            # Nothing accrues on its own yet. Saying so is the honest version of
            # an empty screen — a member with 0 needs to know whether that means
            # "you have earned nothing" or "nothing pays into this yet".
            "accrual_is_live": False,
        })


class RoyaltyAccrueView(APIView):
    """Credit royalties to a member. OWNER ONLY.

    This said "open for testing" and was exactly that: any authenticated member
    could POST an arbitrary `amount_cents` to their own balance, and
    `RoyaltyCashoutView` below moves that balance into `money_cents` — which
    pays other members (`pay_between`), buys PromptZ, and settles CollabZ
    deals. So the two endpoints together were an open mint, and the money did
    not stay in the account that printed it.

    Nothing here was ever load-bearing for a member: no client has ever called
    it, and royalties do not accrue automatically yet (`accrual_is_live` above
    says so out loud). Closing it costs nobody anything and had to happen
    before any screen pointed at this balance.

    `username` lets the owner credit the member whose media actually earned,
    which is the job this endpoint exists to do — crediting only yourself was
    never the useful version of it.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        ensure_owner(request.user)
        if not is_owner(request.user):
            return Response({"detail": "Only the platform owner credits royalties."},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            amount_cents = int(request.data.get("amount_cents"))
        except (TypeError, ValueError):
            return Response({"detail": "amount_cents (integer) required"}, status=status.HTTP_400_BAD_REQUEST)
        if amount_cents <= 0:
            return Response({"detail": "amount must be positive"}, status=status.HTTP_400_BAD_REQUEST)
        target = request.user
        username = str(request.data.get("username") or "").strip()
        if username:
            target = User.objects.filter(username__iexact=username).first()
            if not target:
                return Response({"detail": f"No member called {username}."},
                                status=status.HTTP_404_NOT_FOUND)
        w = wallet_for(target)
        w.royalties_cents += amount_cents
        w.save(update_fields=["royalties_cents", "updated_at"])
        RoyaltyEntry.objects.create(
            user=target, kind=RoyaltyEntry.KIND_ACCRUAL, amount_cents=amount_cents,
            source=str(request.data.get("source", ""))[:200],
        )
        return Response({"username": target.username,
                         "royalties_cents": w.royalties_cents, "royalties": w.royalties})


class RoyaltyCashoutView(APIView):
    """Cash out royalties into the wallet, applying the plan's tax.

    Plans: instant (15%), weekly (per-tier 10/5/3), monthly (1%), quarterly (0%).
    The rates live in `catalog.cashout_rate` and are published, already
    applied to this balance, by RoyaltiesView above — never retyped here.
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
