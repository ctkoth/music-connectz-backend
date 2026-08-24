"""
Economy layer: membership tier, wallet (money/energy/spinaz), and a
transaction ledger. The developer tax (platform's cut on every money
transaction) is enforced here, server-side, so the client can't bypass it.

Rates match the frontend: Free 10% · Premium 5% · StatZ 2%.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

TIER_FREE = "free"
TIER_PREMIUM = "premium"
TIER_STATZ = "statz"
# Owner-only god-mode tier: unlimited limits, 0% tax. Set only for staff/owner.
TIER_DEBUG = "debug"
TIER_CHOICES = [
    (TIER_FREE, "Free"),
    (TIER_PREMIUM, "Premium"),
    (TIER_STATZ, "StatZ"),
    (TIER_DEBUG, "Debug"),
]

# Developer tax (platform cut) per tier, as a fraction of the transaction.
DEV_TAX = {TIER_FREE: 0.10, TIER_PREMIUM: 0.05, TIER_STATZ: 0.03, TIER_DEBUG: 0.0}


def split_cents(amount_cents, rate):
    """Split a transaction into (developer_cut, remainder) in whole cents."""
    amount_cents = int(amount_cents or 0)
    dev = round(amount_cents * rate)
    return dev, amount_cents - dev


class Membership(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="membership"
    )
    tier = models.CharField(max_length=16, choices=TIER_CHOICES, default=TIER_FREE)
    # Opt-in: when True, RateZ attractiveness ratings move the user's median and
    # it's public (usable as a filter on CollabZ / BattleZ / VenueZ).
    attractiveness_public = models.BooleanField(default=True)
    since = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Presence: touched on every stats poll; powers the header "online now" count.
    last_seen = models.DateTimeField(null=True, blank=True, db_index=True)
    # Founding lifetime membership: tier never expires and never re-bills.
    lifetime = models.BooleanField(default=False, db_index=True)
    # Founding member: claimed StatZ in the Founding 50 (any plan). Powers the badge.
    founding = models.BooleanField(default=False, db_index=True)
    # Stripe customer id for founding StatZ subscriptions (year/month), so a
    # cancellation webhook can find and downgrade the right member.
    stripe_customer_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    # Last paid purchase — powers the 10-day downgrade-for-refund window.
    last_paid_at = models.DateTimeField(null=True, blank=True)
    last_payment_ref = models.CharField(max_length=64, blank=True, default="")   # PaymentIntent or Subscription id
    last_payment_kind = models.CharField(max_length=16, blank=True, default="")  # lifetime | year | month

    @property
    def dev_tax_rate(self):
        return DEV_TAX.get(self.tier, DEV_TAX[TIER_FREE])

    def __str__(self):
        return f"{self.user} · {self.tier}"


class Wallet(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet"
    )
    money_cents = models.PositiveIntegerField(default=0)
    royalties_cents = models.PositiveIntegerField(default=0)
    energy = models.IntegerField(default=0)
    spinaz = models.IntegerField(default=0)
    promptz = models.IntegerField(default=0)  # prepaid AI credits; 1 PromptZ = 1¢ of AI spend
    # Free daily prompt allowance by tier (free 1 / premium 5 / statz 10). Resets
    # each day — it does NOT stack. `prompt_day` is the YYYY-MM-DD the counter
    # belongs to; a new day zeroes `prompts_used_today`. Prepaid promptz above is
    # separate and persists.
    prompt_day = models.CharField(max_length=10, blank=True, default="")
    prompts_used_today = models.PositiveIntegerField(default=0)
    # Up to when passive Energy has been paid. Settled lazily on read, the same
    # way the daily prompt counter rolls over — there is no scheduler on Render
    # and a resource that only accrues while a cron is healthy is a resource
    # that silently stops.
    energy_accrued_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def money(self):
        return round(self.money_cents / 100, 2)

    @property
    def royalties(self):
        return round(self.royalties_cents / 100, 2)

    def __str__(self):
        return f"Wallet<{self.user}> ${self.money}"


class Transaction(models.Model):
    KIND_ADD = "add_funds"
    KIND_PURCHASE = "purchase"
    KIND_ROYALTY = "royalty"
    KIND_REWARD = "reward"
    KIND_SPEND = "spend"
    # An AI model charge arriving in the platform owner's wallet. Its own kind
    # rather than KIND_ROYALTY: that one is a member cashing out their accrued
    # royalties, and putting both in one bucket would make either impossible to
    # total. These are the "intelligence royalties" the Owner badge names.
    KIND_INTELLIGENCE = "intelligence"
    KIND_CHOICES = [
        (KIND_ADD, "Add funds"),
        (KIND_PURCHASE, "Purchase"),
        (KIND_ROYALTY, "Royalty"),
        (KIND_REWARD, "Reward"),
        (KIND_SPEND, "Spend"),
        (KIND_INTELLIGENCE, "Intelligence royalty"),
    ]

    # Which resource moved. Money was the only thing ever recorded, so SpinaZ
    # and Energy — the two things members actually earn — left no trace at all
    # and "did my referral pay?" was unanswerable except by watching a balance.
    RES_MONEY, RES_SPINAZ, RES_ENERGY, RES_PROMPTZ, RES_XP = "money", "spinaz", "energy", "promptz", "xp"
    RESOURCE_CHOICES = [
        (RES_MONEY, "Money"), (RES_SPINAZ, "SpinaZ"), (RES_ENERGY, "Energy"),
        (RES_PROMPTZ, "PromptZ"), (RES_XP, "XP"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transactions"
    )
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    resource = models.CharField(max_length=12, choices=RESOURCE_CHOICES, default=RES_MONEY)
    # Signed, in the resource's own unit: cents for money, whole SpinaZ/Energy.
    # amount_cents stays authoritative for money so nothing that reads it moves.
    amount = models.IntegerField(default=0)
    amount_cents = models.IntegerField(help_text="Signed: positive credit, negative debit")
    dev_tax_cents = models.PositiveIntegerField(default=0)
    note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.kind} {self.amount_cents}c ({self.user})"


class SpecZPurchase(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="specz_purchases"
    )
    item_id = models.CharField(max_length=64)
    price_cents = models.PositiveIntegerField()
    dev_tax_cents = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "item_id")
        ordering = ["-created_at"]


class RoyaltyEntry(models.Model):
    KIND_ACCRUAL = "accrual"
    KIND_CASHOUT = "cashout"
    KIND_CHOICES = [(KIND_ACCRUAL, "Accrual"), (KIND_CASHOUT, "Cashout")]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="royalty_entries"
    )
    kind = models.CharField(max_length=12, choices=KIND_CHOICES)
    amount_cents = models.IntegerField(help_text="Signed: + accrual, - cashout")
    tax_cents = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class PaymentIntent(models.Model):
    """A wallet-funding attempt via an external provider (Stripe / PayPal).

    Created pending when checkout starts and marked completed exactly once when
    the provider confirms payment (Stripe webhook / PayPal capture). The unique
    provider_ref makes crediting idempotent — a replayed webhook or double
    capture can't credit the wallet twice.
    """

    PROVIDER_STRIPE = "stripe"
    PROVIDER_PAYPAL = "paypal"
    PROVIDER_CHOICES = [(PROVIDER_STRIPE, "Stripe"), (PROVIDER_PAYPAL, "PayPal")]

    STATUS_PENDING = "pending"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES = [(STATUS_PENDING, "Pending"), (STATUS_COMPLETED, "Completed")]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payment_intents"
    )
    provider = models.CharField(max_length=12, choices=PROVIDER_CHOICES)
    provider_ref = models.CharField(max_length=255, unique=True)
    amount_cents = models.PositiveIntegerField(help_text="Gross charged to the card/PayPal")
    net_cents = models.PositiveIntegerField(default=0)
    dev_tax_cents = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider} {self.amount_cents}c {self.status} <{self.user}>"


class AutoTopUp(models.Model):
    """A Stripe subscription that auto-funds the wallet on a schedule. Stripe owns
    the billing + retries; each paid invoice credits money + tier Energy via the
    webhook (idempotent per invoice id through PaymentIntent.provider_ref)."""
    INTERVAL_CHOICES = [("week", "Weekly"), ("month", "Monthly"), ("year", "Annual")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="auto_topups")
    stripe_subscription_id = models.CharField(max_length=255, unique=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True, default="")
    amount_cents = models.PositiveIntegerField()
    interval = models.CharField(max_length=8, choices=INTERVAL_CHOICES, default="month")
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-active", "-created_at"]

    def __str__(self):
        return f"AutoTopUp {self.amount_cents}c/{self.interval} {'on' if self.active else 'off'} <{self.user}>"


def upload_path(instance, filename):
    """Namespace uploaded files per user so quotas and cleanup stay isolated."""
    return f"uploads/{instance.user_id}/{filename}"


class Upload(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="uploads"
    )
    file = models.FileField(upload_to=upload_path)
    name = models.CharField(max_length=255)
    size_bytes = models.PositiveBigIntegerField(default=0)
    content_type = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.size_bytes}B) <{self.user}>"


# ---- helpers ----
MB = 1024 * 1024


def storage_used_bytes(user):
    return Upload.objects.filter(user=user).aggregate(t=models.Sum("size_bytes"))["t"] or 0


def wallet_for(user):
    return Wallet.objects.get_or_create(user=user)[0]


def membership_for(user):
    # Owner/staff default to StatZ on first touch (their editable god-mode is the
    # separate "debug" tier they can switch into from MembershipZ).
    default = TIER_STATZ if (user and (user.is_superuser or user.is_staff)) else TIER_FREE
    return Membership.objects.get_or_create(user=user, defaults={"tier": default})[0]


def founding_status():
    """How many founding lifetime seats are claimed / remaining, plus the
    founding StatZ prices (lifetime one-time, and grandfathered year/month)."""
    from .catalog import (
        FOUNDING_LIMIT, FOUNDING_PRICE_CENTS, LIFETIME_PRICE_CENTS, FOUNDING_TIER,
        FOUNDING_YEAR_CENTS, FOUNDING_MONTH_CENTS,
    )
    claimed = Membership.objects.filter(lifetime=True).count()
    return {
        "claimed": claimed,
        "limit": FOUNDING_LIMIT,
        "remaining": max(0, FOUNDING_LIMIT - claimed),
        "sold_out": claimed >= FOUNDING_LIMIT,
        "tier": FOUNDING_TIER,
        "price_cents": FOUNDING_PRICE_CENTS,
        "full_price_cents": LIFETIME_PRICE_CENTS,
        "year_cents": FOUNDING_YEAR_CENTS,
        "month_cents": FOUNDING_MONTH_CENTS,
    }


# Members may downgrade for a refund within this many days of a paid purchase.
REFUND_WINDOW_DAYS = 10


def refund_window(m):
    """Refund eligibility for a membership. Returns {eligible, days_left, kind}."""
    from django.utils import timezone
    from datetime import timedelta
    if not m.last_paid_at or not m.last_payment_kind:
        return {"eligible": False, "days_left": 0, "kind": ""}
    deadline = m.last_paid_at + timedelta(days=REFUND_WINDOW_DAYS)
    now = timezone.now()
    left = (deadline - now).days if now <= deadline else 0
    return {"eligible": now <= deadline, "days_left": max(0, left), "kind": m.last_payment_kind}


def grant_lifetime(user):
    """Grant the founding lifetime tier to `user`, race-safely capped at the
    founding limit. Returns the Membership, or None if the offer is sold out.
    Idempotent: a user who is already lifetime just keeps it."""
    from django.db import transaction
    from .catalog import FOUNDING_LIMIT, FOUNDING_TIER
    with transaction.atomic():
        m = Membership.objects.select_for_update().get_or_create(user=user)[0]
        if m.lifetime:
            return m
        claimed = Membership.objects.select_for_update().filter(lifetime=True).count()
        if claimed >= FOUNDING_LIMIT:
            return None
        m.lifetime = True
        m.founding = True
        m.tier = FOUNDING_TIER
        m.save(update_fields=["lifetime", "founding", "tier", "updated_at"])
    # The badge arrives with the seat, not on the member's next visit. Waiting
    # to be noticed is a poor way to be told you got the thing you just paid for.
    recheck_badges(m.user)
    return m


# Topping up your wallet also grants Energy = gross cents × your tier multiplier
# (so $1 = 100¢ = 100⚡ on Free). Premium doubles it, StatZ quadruples it.
ENERGY_TOPUP_MULT = {TIER_FREE: 1, TIER_PREMIUM: 2, TIER_STATZ: 4, TIER_DEBUG: 4}


def energy_for_topup(user, amount_cents):
    """Energy granted for a wallet top-up: gross cents × tier multiplier."""
    tier = membership_for(user).tier
    return int(amount_cents or 0) * ENERGY_TOPUP_MULT.get(tier, 1)


def credit_funds(user, amount_cents, note="Add funds"):
    """Credit a gross funding amount to a user's wallet, applying the developer
    tax server-side. Shared by manual add-funds and card/PayPal checkout so the
    tax is enforced identically everywhere. Returns (dev_cents, net_cents)."""
    m = membership_for(user)
    w = wallet_for(user)
    dev, net = split_cents(amount_cents, m.dev_tax_rate)
    w.money_cents += net
    w.save(update_fields=["money_cents", "updated_at"])
    Transaction.objects.create(
        user=user, kind=Transaction.KIND_ADD, amount_cents=net,
        dev_tax_cents=dev, note=note[:200],
    )
    return dev, net


def pay_between(payer, payee, amount_cents, note=""):
    """Move money payer -> payee, applying the payer's developer tax. The payee
    receives the net; the platform keeps the tax. Caller must ensure the payer
    has the balance and wrap in a transaction. Returns (dev_cents, net_cents)."""
    m = membership_for(payer)
    pw = wallet_for(payer)
    rw = wallet_for(payee)
    dev, net = split_cents(amount_cents, m.dev_tax_rate)
    pw.money_cents -= amount_cents
    rw.money_cents += net
    pw.save(update_fields=["money_cents", "updated_at"])
    rw.save(update_fields=["money_cents", "updated_at"])
    Transaction.objects.create(user=payer, kind=Transaction.KIND_SPEND, amount_cents=-amount_cents, dev_tax_cents=dev, note=note[:200])
    Transaction.objects.create(user=payee, kind=Transaction.KIND_REWARD, amount_cents=net, dev_tax_cents=dev, note=note[:200])
    return dev, net


def can_afford_ai(user, cost_cents):
    """Whether the member can cover an AI action — prepaid PromptZ (1 PromptZ =
    1¢) plus cash together."""
    cost_cents = int(cost_cents or 0)
    if cost_cents <= 0:
        return True
    w = wallet_for(user)
    return (w.promptz or 0) + (w.money_cents or 0) >= cost_cents


def award_promptz(user, amount, note="PromptZ"):
    """Grant prepaid AI credits (1 PromptZ = 1¢ of AI spend)."""
    w = wallet_for(user)
    w.promptz = (w.promptz or 0) + int(amount)
    w.save(update_fields=["promptz", "updated_at"])
    return w.promptz


# Free daily prompt allowance by tier. Resets each day — it does NOT stack.
# Prepaid PromptZ (Wallet.promptz) is separate and persists. Owner/debug is
# effectively unlimited (their AI runs are already free anyway).
#
# StatZ is 10 rather than 20 because 20 does not pay for itself: at the 3c
# AI_MODEL_COSTS["standard"] floor, 20/day is $18/mo of model cost against a
# $15/mo subscription, and $18 against $7.50 for a founding seat. At 10/day it
# is $9 against $15 — a real margin, and still twice what Premium gets. Anyone
# who wants more buys prepaid PromptZ, which is priced to cover itself.
PROMPT_ALLOWANCE = {"free": 1, "premium": 5, "statz": 10, "debug": 10 ** 6}


def daily_prompt_state(user):
    """Return (allowance, used, remaining) for today's free prompts, rolling the
    counter over at the start of a new day. Persists the reset when it happens."""
    from django.utils import timezone
    w = wallet_for(user)
    allowance = PROMPT_ALLOWANCE.get(membership_for(user).tier, 1)
    today = timezone.now().strftime("%Y-%m-%d")
    if w.prompt_day != today:
        w.prompt_day = today
        w.prompts_used_today = 0
        w.save(update_fields=["prompt_day", "prompts_used_today", "updated_at"])
    remaining = max(0, allowance - (w.prompts_used_today or 0))
    return allowance, (w.prompts_used_today or 0), remaining


def _consume_daily_prompt(user):
    """Spend one of today's free prompts if any remain. Returns True if one was
    consumed (the caller should treat the run as free), else False."""
    _, _, remaining = daily_prompt_state(user)  # also handles the daily reset
    if remaining <= 0:
        return False
    w = wallet_for(user)
    w.prompts_used_today = (w.prompts_used_today or 0) + 1
    w.save(update_fields=["prompts_used_today", "updated_at"])
    return True


def charge_ai_usage(user, cost_cents, note="AI usage", count_daily=False):
    """Debit the *minimum* cost to cover an AI model run — pure pass-through, no
    developer tax. When `count_daily` is set (a genuine prompt run), the day's
    free allowance is spent first and the run is free; otherwise spends prepaid
    PromptZ (1 PromptZ = 1¢), then cash. Returns remaining money_cents, or None
    if the member can't afford it even with PromptZ (caller returns 402)."""
    cost_cents = int(cost_cents or 0)
    w = wallet_for(user)
    if cost_cents <= 0:
        return w.money_cents
    # A free daily prompt covers the whole run before any paid balance is touched.
    if count_daily and _consume_daily_prompt(user):
        Transaction.objects.create(
            user=user, kind=Transaction.KIND_SPEND, amount_cents=0,
            dev_tax_cents=0, note=(note + " · daily prompt 🏷️")[:200],
        )
        return w.money_cents
    if (w.promptz or 0) + w.money_cents < cost_cents:
        return None
    from_promptz = min(w.promptz or 0, cost_cents)  # PromptZ first
    from_cash = cost_cents - from_promptz
    if from_promptz:
        w.promptz -= from_promptz
    if from_cash:
        w.money_cents -= from_cash
    w.save(update_fields=["promptz", "money_cents", "updated_at"])
    tag = f" · {from_promptz}🏷️" if from_promptz else ""
    Transaction.objects.create(
        user=user, kind=Transaction.KIND_SPEND, amount_cents=-from_cash,
        dev_tax_cents=0, note=(note + tag)[:200],
    )
    return w.money_cents


# ---- VenueZ ----
class Venue(models.Model):
    MODE_COLLAB = "collaborative"
    MODE_PERF = "performance"
    MODE_CHOICES = [(MODE_COLLAB, "Collaborative"), (MODE_PERF, "Performance")]

    host = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="venues")
    title = models.CharField(max_length=120)
    mode = models.CharField(max_length=16, choices=MODE_CHOICES, default=MODE_COLLAB)
    vtype = models.CharField(max_length=24, default="party")  # party/openmic/theater/show/custom
    custom_name = models.CharField(max_length=60, blank=True, default="")
    host_price_cents = models.PositiveIntegerField(default=0)
    visitor_pay_cents = models.PositiveIntegerField(default=0)
    min_attract = models.PositiveSmallIntegerField(default=0)  # 0-10, legacy
    # All five range gates: {"rating": [lo, hi], "price": [...], "attract": ...,
    # "age": ..., "km": [None, hi]}. Exclusive — no value for a gated metric
    # means excluded. min_attract above is kept so old venues keep working.
    gates = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class VenueAttendance(models.Model):
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="attendances")
    visitor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="venue_attendances")
    paid_cents = models.PositiveIntegerField(default=0)
    earned_cents = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("venue", "visitor")
        ordering = ["-created_at"]


# ---- Attractiveness (RateZ) ----
class AttractivenessRating(models.Model):
    rater = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attractiveness_given")
    target = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attractiveness_received")
    score = models.PositiveSmallIntegerField()  # 1-10
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("rater", "target")


def _median(scores):
    scores = sorted(scores)
    n = len(scores)
    if n == 0:
        return None
    mid = n // 2
    return scores[mid] if n % 2 else round((scores[mid - 1] + scores[mid]) / 2, 1)


# ---- FaceZ ----
def face_path(instance, filename):
    return f"facez/{instance.owner_id}/{filename}"


class Face(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="faces")
    image = models.ImageField(upload_to=face_path)
    name = models.CharField(max_length=80, blank=True, default="")
    # The member tagged in this media (who the face is), for likeness/credit.
    tagged = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="tagged_faces")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class FaceRating(models.Model):
    rater = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="face_ratings")
    face = models.ForeignKey(Face, on_delete=models.CASCADE, related_name="ratings")
    score = models.PositiveSmallIntegerField()  # 1-10
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("rater", "face")


def face_median(face):
    return _median(face.ratings.values_list("score", flat=True))


def attractiveness_median(user):
    """A user's community attractiveness median (1-10), combining direct RateZ
    ratings and every rating their FaceZ faces have received. None if unrated."""
    scores = list(AttractivenessRating.objects.filter(target=user).values_list("score", flat=True))
    scores += list(FaceRating.objects.filter(face__owner=user).values_list("score", flat=True))
    return _median(scores)


class OverallRating(models.Model):
    """Overall (holistic) rating of a member's profile, 1-10, one per rater."""
    rater = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="overall_given")
    target = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="overall_received")
    score = models.PositiveSmallIntegerField()  # 1-10
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("rater", "target")


def overall_median(user):
    """A member's overall profile rating median (1-10). None if unrated."""
    return _median(OverallRating.objects.filter(target=user).values_list("score", flat=True))


# ---- Cross-user Profile ----
class Profile(models.Model):
    """A member's public, searchable profile. Denormalized filter fields
    (sign, regions, gender, sober, attracted_to) let search match on metrics;
    the JSON fields carry the full display data."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mcz_profile")
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)  # profile picture
    display_name = models.CharField(max_length=80, blank=True, default="")
    # TextField, not CharField(500): the tier char limit runs to 1,500 for
    # Premium and is unlimited for StatZ, so no column width can express it.
    # The cap belongs to the tier and is applied on write, not to the storage.
    bio = models.TextField(blank=True, default="")
    location = models.CharField(max_length=120, blank=True, default="")
    gender = models.CharField(max_length=24, blank=True, default="")
    birthday = models.CharField(max_length=10, blank=True, default="")  # YYYY-MM-DD
    sign = models.CharField(max_length=16, blank=True, default="")
    nationalities = models.JSONField(default=list, blank=True)
    regions = models.JSONField(default=list, blank=True)          # for filtering
    substances = models.JSONField(default=dict, blank=True)
    sober = models.BooleanField(default=False)
    attracted_to = models.JSONField(default=list, blank=True)     # partnerGenders
    asexual = models.BooleanField(default=False)
    traits = models.JSONField(default=list, blank=True)
    personas = models.JSONField(default=list, blank=True)
    # The title being worn, from a badge held AND shown. Stored rather than
    # derived so a member with several can choose which one they lead with.
    badge_title = models.CharField(max_length=60, blank=True, default="")
    # Which AI engine this member's paid AI actions run on. Blank means "never
    # chose" — resolved at read time to the best rung their tier owns, so the
    # default follows an upgrade or a lapse without anything having to migrate
    # the stored value. Always read it through catalog.ai_model_for().
    ai_model = models.CharField(max_length=16, blank=True, default="")
    links = models.JSONField(default=list, blank=True)  # [{label, url}] public links
    # Location (opt-in) for in-person CollabZ / VenueZ distance filtering.
    share_location = models.BooleanField(default=False)
    lat = models.FloatField(null=True, blank=True)
    lng = models.FloatField(null=True, blank=True)
    # Declared external-account followers (sum across connected socials) — feeds
    # the hourly energy rate alongside Music ConnectZ followers.
    external_followers = models.PositiveIntegerField(default=0)
    # 18+ age verification (Stripe Identity). Set by the identity webhook once a
    # government ID confirms the member is 18 or older — gates money betting +
    # adult content. Never trust a self-reported birthday for this.
    verified_18plus = models.BooleanField(default=False, db_index=True)
    verified_18plus_at = models.DateTimeField(null=True, blank=True)
    # One-time onboarding reward: set when the member finishes the intro flow so
    # the grant (SpinAZ + Energy) can never be claimed twice.
    onboarded = models.BooleanField(default=False)
    onboarded_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


def profile_for(user):
    return Profile.objects.get_or_create(user=user)[0]


def profile_age(p):
    """Age in years from a YYYY-MM-DD birthday, or None."""
    import datetime
    try:
        y, m, d = (int(x) for x in (p.birthday or "").split("-"))
        today = datetime.date.today()
        return today.year - y - ((today.month, today.day) < (m, d))
    except (ValueError, TypeError):
        return None


# Last MMDD of each sign, in calendar order — e.g. Capricorn runs through Jan 19,
# Aquarius Jan 20–Feb 18, and Capricorn resumes Dec 22. Matched with `md <= cutoff`.
_ZODIAC_CUTOFFS = [
    (119, "Capricorn"), (218, "Aquarius"), (320, "Pisces"), (419, "Aries"),
    (520, "Taurus"), (620, "Gemini"), (722, "Cancer"), (822, "Leo"),
    (922, "Virgo"), (1022, "Libra"), (1121, "Scorpio"), (1221, "Sagittarius"),
    (1231, "Capricorn"),
]


# ---- The age wall.
#
# Two surfaces in this app are adult-only under Play's Families policy: rating
# people on looks, and collecting sexual orientation. The app also carries a
# "Teen-safe" badge on the InstrumentZ screens, so teens are an intended
# audience — and a label is not a boundary.
#
# `Profile.verified_18plus` already existed, is already set properly by Stripe
# Identity from a government ID, and its own comment claimed it "gates money
# betting + adult content". It gated nothing: thirteen references across the
# codebase, every one of them setting it or displaying it, none consulting it
# before allowing anything. This is where it starts being read.
#
# Corey's call on the unknown case: a member with no birthday and no
# verification is treated as an ADULT. Most of the existing user base has
# neither, and locking them out of what they use today to satisfy a form would
# punish real people for a gap in our own data. What we wall is what we
# actually know — a stated age of 13-17.
TEEN_MIN_AGE, ADULT_AGE = 13, 18


def profile_is_minor(p):
    """The wall, evaluated against a Profile — including one not yet saved.

    Takes the profile rather than the user so a save can be judged on the state
    it is ABOUT to have. Reading the stored row instead let a member set a teen
    birthday and an orientation in the same request and keep both, because at
    the top of that request they were still an unknown age.
    """
    if p.verified_18plus:
        return False
    age = profile_age(p)
    return age is not None and TEEN_MIN_AGE <= age < ADULT_AGE


def is_minor(user):
    """True only when we KNOW this member is under 18.

    Knowing means a stated birthday in the teen range. Absence of information is
    not evidence of youth, so an unknown age is not a minor — see the note
    above. ID verification always wins over a self-reported birthday, in the
    permissive direction only: a verified adult is an adult whatever the
    birthday field says, because the ID outranks the typing.
    """
    return profile_is_minor(getattr(user, "mcz_profile", None) or profile_for(user))


def third_party_ads_allowed(user):
    """Whether this member may be shown a third-party ad frame.

    The DECISION, deliberately, not the input. Nothing outside this function
    needs to know a member's age to answer it, and a client that re-derives
    "under 18" for itself is a second copy of a policy rule that Google audits
    — the kind that drifts and is only noticed when an app is pulled.

    Why the rule exists: `play/data-safety.md` answers "Committed to the Play
    Families Policy: Yes", and that answer was earned by hard-walling the adult
    surfaces. Teens are an intended audience (RapZ carries a "Teen-safe" badge),
    and the Families Policy requires ads shown to them to come from a
    Play-certified SDK. An arbitrary third-party frame is not one and cannot
    attest to being one, so it is not shown to anyone we know to be a minor.

    Unknown age counts as an adult here, matching `is_minor` and the decision
    recorded in `play/data-safety.md`. That is the one line to tighten if the
    Families exposure ever needs to be reduced further — and tightening it here
    changes every surface at once, which is the whole point of it living in one
    function.
    """
    return not is_minor(user)


def adult_only_reason(user):
    """Why this surface is closed to them, in words, or "" when it's open."""
    if not is_minor(user):
        return ""
    return ("This part of Music ConnectZ is 18+. Everything else — posting, "
            "collabs, BattleZ, the coach, getting paid — stays open.")


def zodiac_for(birthday):
    """Western zodiac sign from a YYYY-MM-DD birthday, or "" if unparseable."""
    try:
        _, m, d = (int(x) for x in (birthday or "").split("-"))
    except (ValueError, TypeError):
        return ""
    md = m * 100 + d
    for cutoff, name in _ZODIAC_CUTOFFS:
        if md <= cutoff:
            return name
    return "Capricorn"


def haversine_km(lat1, lng1, lat2, lng2):
    """Great-circle distance in km between two lat/lng points."""
    from math import radians, sin, cos, asin, sqrt
    if None in (lat1, lng1, lat2, lng2):
        return None
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return round(2 * r * asin(sqrt(a)), 1)


# ---- PostZ (cross-user posts with visibility + restricted-join rewards) ----
RESTRICTED_JOIN_REWARD_SPINAZ = 300

# --- Rating-based CollabZ splits.
#
# Three questions had to be answered before money could move on a number
# strangers control, and each answer is a rule below.
#
# WHOSE RATING? Each contributor's rating ON THIS WORK — `collab:<id>:<user>` in
# the same item space RateZ already serves. Not their global reputation: rating
# the person hands the biggest cut to the most famous name regardless of what
# they actually did on this track.
#
# MEASURED WHEN? Frozen at release. A live split means your share changes after
# you agreed to it.
#
# WHAT STOPS FARMING? Nobody on the deal may rate it, and below a real number of
# distinct raters the split falls back to the agreed worth. Two opinions are not
# a mandate to move somebody's money.
RATING_SPLIT_MIN_RATERS = 3


def contributor_item_key(deal_id, username):
    return f"collab:{deal_id}:{username}"


# The composer has promised these two numbers from day one — "rating unlocks 30s
# after posting, comments 60s" — and NOTHING ENFORCED THEM. A rule stated on
# screen and checked nowhere is not a rule; anyone calling the API directly
# could rate a post the instant it landed, and rate their own.
POST_RATE_UNLOCK_SEC = 30
POST_COMMENT_UNLOCK_SEC = 60


def post_interaction_block(item_id, user, kind):
    """Why `user` may not rate/comment on `item_id` yet, or None if they may.

    Speaks about posts (unlock timers, no self-rating) and about CollabZ
    contributor ratings (nobody on the deal may rate it). Every other id in the
    shared space — a playlist, a face, a work — has no author and no timer.
    """
    item_id = str(item_id or "")

    # collab:<deal>:<username> — the ratings a rating-split pays out on. Money
    # moves on these, so the people it moves between must not be voting.
    if kind == "rate" and item_id.startswith("collab:"):
        bits = item_id.split(":")
        if len(bits) == 3:
            try:
                deal = CollabDeal.objects.only("id", "participants").get(pk=int(bits[1]))
            except (ValueError, CollabDeal.DoesNotExist):
                return None
            username = getattr(user, "username", "")
            if any(p.get("username") == username for p in deal.participants):
                return {"detail": "You're on this deal — you can't rate its contributors."}
        return None

    if not item_id.startswith("post:"):
        return None
    try:
        post = Post.objects.only("id", "author_id", "created_at").get(
            pk=int(str(item_id).split(":", 1)[1]))
    except (ValueError, Post.DoesNotExist):
        return None
    if kind == "rate" and post.author_id == getattr(user, "id", None):
        return {"detail": "You can't rate your own post."}
    unlock = POST_RATE_UNLOCK_SEC if kind == "rate" else POST_COMMENT_UNLOCK_SEC
    age = (timezone.now() - post.created_at).total_seconds()
    if age < unlock:
        left = int(unlock - age) + 1
        return {"detail": f"{'Rating' if kind == 'rate' else 'Commenting'} opens {unlock}s after a post lands — {left}s to go.",
                "unlock_seconds": unlock, "seconds_left": left}
    return None


class Post(models.Model):
    """A member post. Visibility gates who sees it; restricted posts reward the
    author 300 SpinAZ per valid join from a distinct non-author visitor."""
    VIS_CHOICES = [("public", "Public"), ("restricted", "Restricted"), ("private", "Private")]
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="posts")
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    links = models.JSONField(default=list, blank=True)
    media_type = models.CharField(max_length=24, blank=True, default="")
    media_url = models.CharField(max_length=500, blank=True, default="")  # uploaded audio/video take
    # Album support: a post is either single (uses media_url) or an album whose
    # `items` carry multiple media entries [{url, type, title, lyrics}].
    is_album = models.BooleanField(default=False)
    items = models.JSONField(default=list, blank=True)
    # Optional scored-take payload (e.g. RapZ/SingZ lab result) for context on the post.
    score = models.JSONField(default=dict, blank=True)
    visibility = models.CharField(max_length=12, choices=VIS_CHOICES, default="public")
    # The composer has always shown a genre picker and the value was discarded
    # on the way in, so every post in the app is genreless and ChartZ has
    # nothing to slice by.
    genre = models.CharField(max_length=40, blank=True, default="")
    # 🆓 Freestyle — off the top, unwritten. Deliberately NOT a genre: a
    # freestyle is a way of making the thing, not a kind of music, so a freestyle
    # Trap verse and a freestyle Jazz solo are both freestyles and both keep
    # their own genre. Putting it in the genre list would have forced a choice
    # between the two and split the tag across every family in it.
    freestyle = models.BooleanField(default=False)
    # Which skills went into it — 2.2 required this on every example, and it is
    # what makes a post matchable to the people who have those skills and
    # priceable against their rates. A post without it is a file with a caption.
    skills_used = models.JSONField(default=list, blank=True)
    # Everyone this post belongs to, and what each of them brought:
    # [{username, slot, role}]. `author` is only whoever pressed post.
    #
    # This is the point of a collab. An artist arrives with a song and needs a
    # cover and a video; the designer and the videographer put theirs up; the
    # finished thing is ONE post that belongs to all three. Crediting it to
    # whoever happened to publish it would be the same erasure the escrow
    # exists to prevent, one step later.
    contributors = models.JSONField(default=list, blank=True)
    # The deal it came out of, when it came out of one. SET_NULL so deleting a
    # deal never takes the published work with it.
    source_deal = models.ForeignKey("CollabDeal", on_delete=models.SET_NULL, null=True,
                                    blank=True, related_name="posts")
    # May other members put this in THEIR playlists? Default yes — being in
    # someone else's set is reach, and a public post is already public. This is
    # the author's off switch for the case where it isn't welcome.
    allow_in_playlists = models.BooleanField(default=True)
    skill_cost_cents = models.PositiveIntegerField(default=0)  # combined skill price of what's used
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    edit_history = models.JSONField(default=list, blank=True)  # [{title, description, at}] prior versions

    class Meta:
        ordering = ("-created_at",)


class PostJoin(models.Model):
    """A visit to a restricted post. One reward per distinct IP (non-author)."""
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="joins")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="post_joins")
    ip = models.GenericIPAddressField(null=True, blank=True)
    active_seconds = models.PositiveIntegerField(default=0)
    rewarded = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("post", "ip")


# Sharing another member's post rewards the sharer once, gated by a genuine dwell.
SHARE_REWARD_ENERGY = 5
SHARE_MIN_ACTIVE_SECONDS = 30           # must have genuinely viewed it
SHARE_MAX_ACTIVE_SECONDS = 300          # 5 min — beyond this we don't require more


class PostShare(models.Model):
    """A member sharing someone else's post. One +5⚡ reward per user+post."""
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="shares")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="post_shares")
    ip = models.GenericIPAddressField(null=True, blank=True)
    active_seconds = models.PositiveIntegerField(default=0)
    rewarded = models.BooleanField(default=False)
    shared_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("post", "user")


class DailySubmission(models.Model):
    """Counts scored/creator submissions per user per day, for tier daily caps
    (Free 5 · Premium 15 · StatZ 50)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="daily_submissions")
    day = models.DateField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("user", "day")


SUBMISSION_DAILY_CAP = {"free": 5, "premium": 15, "statz": 50}


def submission_cap_for(user):
    tier = membership_for(user).tier if user and user.is_authenticated else "free"
    return SUBMISSION_DAILY_CAP.get(tier, SUBMISSION_DAILY_CAP["free"])


def submissions_used_today(user):
    row = DailySubmission.objects.filter(user=user, day=timezone.localdate()).first()
    return row.count if row else 0


def record_submission(user):
    """Increment today's submission count; returns the new count."""
    row, _ = DailySubmission.objects.get_or_create(user=user, day=timezone.localdate())
    row.count = (row.count or 0) + 1
    row.save(update_fields=["count"])
    return row.count


# ---- Member link clicks (tally + rewarded, safety-scanned) ----
LINK_CLICK_REWARD_ENERGY = 5
LINK_CLICK_MIN_ACTIVE_SECONDS = 30      # genuine visit before the reward
LINK_CLICK_REWARD_DAILY_CAP = 20        # per clicker, per day


class LinkCounter(models.Model):
    """Running click tally for a member link (keyed by owner + URL)."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="link_counters", null=True, blank=True)
    url = models.CharField(max_length=600)
    clicks = models.PositiveIntegerField(default=0)
    safe = models.BooleanField(default=True)          # Safe Browsing verdict (best-effort)
    scanned = models.BooleanField(default=False)      # whether we've checked it
    threat = models.CharField(max_length=60, blank=True, default="")

    class Meta:
        unique_together = ("owner", "url")


class LinkClick(models.Model):
    """A click on a member's link. One +5⚡ reward per clicker+link per day, for
    clicking someone else's link, gated by a genuine dwell."""
    counter = models.ForeignKey(LinkCounter, on_delete=models.CASCADE, related_name="click_events")
    clicker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="link_clicks")
    ip = models.GenericIPAddressField(null=True, blank=True)
    active_seconds = models.PositiveIntegerField(default=0)
    rewarded = models.BooleanField(default=False)
    day = models.DateField()
    clicked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("counter", "clicker", "day")


def award_spinaz(user, amount, note=""):
    """Credit SpinAZ to a user's wallet and record it.

    The `note` every caller already passes used to be accepted and thrown
    away, so a member could watch their balance change and never learn what
    moved it or when.
    """
    w = wallet_for(user)
    w.spinaz = (w.spinaz or 0) + int(amount)
    w.save(update_fields=["spinaz", "updated_at"])
    log_resource(user, Transaction.RES_SPINAZ, int(amount), note or "SpinaZ")
    return w.spinaz


def award_energy(user, amount, note=""):
    """Credit Energy to a user's wallet, and record it."""
    w = wallet_for(user)
    w.energy = (w.energy or 0) + int(amount)
    w.save(update_fields=["energy", "updated_at"])
    log_resource(user, Transaction.RES_ENERGY, int(amount), note or "Energy")
    return w.energy


def log_resource(user, resource, amount, note=""):
    """One line in LogZ: what moved, which way, and when.

    Best-effort — a ledger write must never be the reason a reward fails to
    land. The balance is the truth; this is the account of how it got there.
    """
    if not user or not amount:
        return None
    try:
        return Transaction.objects.create(
            user=user,
            kind=Transaction.KIND_REWARD if amount > 0 else Transaction.KIND_SPEND,
            resource=resource,
            amount=int(amount),
            amount_cents=int(amount) if resource == Transaction.RES_MONEY else 0,
            dev_tax_cents=0,
            note=str(note)[:200],
        )
    except Exception:  # pragma: no cover - never break a reward over its log
        return None


# ---- Referrals (two-sided) — inviting a new member rewards both people once.
# The joinee redeems the referrer's code (their username) during/after signup;
# the referrer earns more (they brought the growth), the joinee gets a welcome
# bonus. A member can only ever be referred once, and never by themselves.
REFERRAL_REWARD_REFERRER_SPINAZ = 300
REFERRAL_REWARD_JOINEE_SPINAZ = 100


class Referral(models.Model):
    referrer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name="referrals_made")
    # A user can be referred at most once — enforced by the one-to-one joinee.
    joinee = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                  related_name="referred_by")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Referral<{self.referrer} -> {self.joinee}>"


def record_referral(referrer, joinee):
    """Link joinee to referrer and pay both sides once. Returns the Referral, or
    None if it couldn't be recorded (self-referral, or already referred)."""
    if not referrer or not joinee or referrer.id == joinee.id:
        return None
    if Referral.objects.filter(joinee=joinee).exists():
        return None
    ref = Referral.objects.create(referrer=referrer, joinee=joinee)
    award_spinaz(referrer, REFERRAL_REWARD_REFERRER_SPINAZ, "referral (referrer)")
    award_spinaz(joinee, REFERRAL_REWARD_JOINEE_SPINAZ, "referral (welcome)")
    return ref


# ---- Onboarding — a one-time reward for finishing the intro flow.
# Rating pays. The working notes have said so from the start — "+1 ⚡ on a
# rating is the reason people rate" — and no rating view ever awarded anything,
# so the single most common action in the app paid nothing at all.
#
# Only a NEW rating pays (changing your mind is free but not profitable), and a
# daily cap keeps it from being a faucet somebody can sit on.
RATING_REWARD_ENERGY = 1
RATING_REWARD_DAILY_CAP = 20
RATING_NOTE = "Rating"


def reward_for_rating(user, what=""):
    """Credit the rating reward, respecting the daily cap. Returns what landed."""
    from datetime import timedelta
    if not user:
        return 0
    day_ago = timezone.now() - timedelta(hours=24)
    paid = Transaction.objects.filter(
        user=user, resource=Transaction.RES_ENERGY,
        note__startswith=RATING_NOTE, created_at__gte=day_ago,
    ).count()
    cap = RATING_REWARD_DAILY_CAP + badge_effects(user).get("rating_cap_bonus", 0)
    if paid >= cap:
        return 0
    note = f"{RATING_NOTE} — {what}" if what else RATING_NOTE
    award_energy(user, RATING_REWARD_ENERGY, note)
    return RATING_REWARD_ENERGY


ONBOARD_REWARD_SPINAZ = 150
ONBOARD_REWARD_ENERGY = 50


def complete_onboarding(user):
    """Mark onboarding done and grant the one-time reward. Idempotent — returns
    the amounts granted (zeros if already onboarded)."""
    from django.utils import timezone
    p = profile_for(user)
    if p.onboarded:
        return {"spinaz": 0, "energy": 0, "already": True}
    p.onboarded = True
    p.onboarded_at = timezone.now()
    p.save(update_fields=["onboarded", "onboarded_at", "updated_at"])
    award_spinaz(user, ONBOARD_REWARD_SPINAZ, "onboarding")
    award_energy(user, ONBOARD_REWARD_ENERGY, "onboarding")
    return {"spinaz": ONBOARD_REWARD_SPINAZ, "energy": ONBOARD_REWARD_ENERGY, "already": False}


# ---- AdZ (Watch & Earn) — a commercial pays the owner; the viewer earns SpinAZ
# equal to the cents the owner is paid per view. ----
class Commercial(models.Model):
    """A rewarded commercial. `payout_cents` = what the owner is paid per view;
    the viewer earns that many SpinAZ (SpinAZ pegged to cents)."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="commercials")
    title = models.CharField(max_length=160)
    sponsor = models.CharField(max_length=120, blank=True, default="")
    media_url = models.CharField(max_length=500, blank=True, default="")
    media_type = models.CharField(max_length=24, blank=True, default="video")
    link_url = models.CharField(max_length=600, blank=True, default="")   # optional advertiser link
    payout_cents = models.PositiveIntegerField(default=1)                 # owner's revenue per view = viewer SpinAZ
    min_watch_seconds = models.PositiveIntegerField(default=15)           # must watch this long to earn
    daily_cap_per_user = models.PositiveIntegerField(default=3)           # rewards per viewer per day for THIS ad
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class AdView(models.Model):
    """A view of a commercial. One reward per viewer per ad per day (up to the
    ad's daily cap), gated by a genuine watch time."""
    commercial = models.ForeignKey(Commercial, on_delete=models.CASCADE, related_name="views")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ad_views")
    ip = models.GenericIPAddressField(null=True, blank=True)
    watched_seconds = models.PositiveIntegerField(default=0)
    rewarded = models.BooleanField(default=False)
    reward_spinaz = models.PositiveIntegerField(default=0)
    day = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)


AD_REWARD_DAILY_CAP_PER_USER = 30  # total rewarded ad views per viewer per day (anti-farm)


def owns_post(post, user):
    """The author OR anyone credited on it.

    A collab post belongs to everyone who put something into it, so every
    check that used to mean "is this yours" has to mean that too — otherwise
    the designer whose cover is on the post can't see their own private work.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if post.author_id == user.id:
        return True
    return any(c.get("username") == user.username for c in (post.contributors or []))


def can_view_post(post, user):
    if post.visibility == "public":
        return True
    if owns_post(post, user):
        return True
    if post.visibility == "restricted":
        return bool(user and user.is_authenticated)  # members only
    return False  # private


# ---- Notifications ----
class Notification(models.Model):
    """An in-app notification for `user`, optionally caused by `actor`."""
    KIND_CHOICES = [
        ("follow", "Follow"), ("rate", "Rating"), ("like", "Like"),
        ("comment", "Comment"), ("join", "Restricted join"), ("pay", "Payment"),
        ("message", "Message"), ("system", "System"),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications_sent")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default="system")
    text = models.CharField(max_length=280)
    item_id = models.CharField(max_length=160, blank=True, default="")  # deep-link target
    read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


# ---- BugZ 🐞 — find something broken, say so, get paid when it's fixed.
#
# The screen has existed and called /api/bugz/ since it shipped; nothing served
# it, so every report 404'd and the 200 SpinaZ bounty on the page was a promise
# with no code behind it. This is that code.
#
# A report carries an optional screenshot or screen recording, because "it
# looked wrong" is the hardest kind of bug to write down and the easiest to
# photograph. Evidence is what makes a report actionable — half of triage is
# working out what the reporter actually saw.
BUG_BOUNTY_SPINAZ = 200
BUG_MAX_MB = 25


def bug_shot_path(instance, filename):
    return f"bugz/{instance.reporter_id}/{filename}"


class BugReport(models.Model):
    STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_SQUASHED, STATUS_DECLINED = (
        "open", "in_progress", "squashed", "declined")
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"), (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_SQUASHED, "Squashed"), (STATUS_DECLINED, "Declined"),
    ]
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name="bug_reports")
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True, default="")
    # A screenshot or a screen recording. One field, either kind — a bug is one
    # piece of evidence, and making the reporter pick the right slot first is
    # friction on the one screen that exists to reduce friction.
    shot = models.FileField(upload_to=bug_shot_path, blank=True, null=True)
    shot_type = models.CharField(max_length=24, blank=True, default="")   # image | video
    # Where the reporter was standing. Cross-pollination: a report that knows
    # its app opens back on the screen that broke.
    app_key = models.CharField(max_length=32, blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_OPEN)
    # Paid once, recorded here, so a report reopened and re-squashed can never
    # pay the bounty twice.
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self):
        return f"BugReport<{self.id}> {self.status} {self.title[:40]}"


def pay_bug_bounty(bug, by=None):
    """Pay the reporter once, and hand them the Bug Hunter badge.

    Returns True if this call paid. Idempotent on purpose: the bounty is
    advertised on the screen as a fixed 200, so paying it twice would be the
    platform inventing SpinaZ, and paying it zero times would be the screen
    lying.
    """
    if bug.paid_at or bug.status != BugReport.STATUS_SQUASHED:
        return False
    award_spinaz(bug.reporter, BUG_BOUNTY_SPINAZ, note=f"BugZ bounty: {bug.title}"[:200])
    grant_badge(bug.reporter, "bug_hunter", by=by)
    bug.paid_at = timezone.now()
    bug.save(update_fields=["paid_at", "updated_at"])
    notify(bug.reporter, "bugz",
           f"🐞 Squashed — {bug.title[:80]}. +{BUG_BOUNTY_SPINAZ} 🍥 and the Bug Hunter badge.",
           actor=by)
    return True


def notify(user, kind, text, actor=None, item_id=""):
    """Create a notification, skipping self-notifications and missing users."""
    if not user or (actor and actor.id == user.id):
        return None
    return Notification.objects.create(user=user, actor=actor, kind=kind, text=text[:280], item_id=item_id or "")


# ---- Direct messages ----
class Message(models.Model):
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="messages_sent")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="messages_received")
    body = models.TextField(blank=True, default="")
    # Optional recorded/uploaded audio or video attachment (a stored upload URL).
    media_url = models.CharField(max_length=500, blank=True, default="")
    media_type = models.CharField(max_length=60, blank=True, default="")  # MIME, e.g. audio/webm
    read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    edit_history = models.JSONField(default=list, blank=True)  # [{body, at}] prior versions

    class Meta:
        ordering = ("created_at",)


# ---- Moderation: report content + block users ----
class Report(models.Model):
    """A user report on any item (post, profile, comment…). Owner reviews these."""
    REASONS = [
        ("spam", "Spam"), ("harassment", "Harassment"), ("hate", "Hate/abuse"),
        ("nsfw", "Adult/NSFW"), ("stolen", "Stolen content"), ("other", "Other"),
    ]
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports_made")
    item_id = models.CharField(max_length=160, db_index=True)
    reason = models.CharField(max_length=16, choices=REASONS, default="other")
    note = models.CharField(max_length=280, blank=True, default="")
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        unique_together = ("reporter", "item_id")


class Block(models.Model):
    """`blocker` has blocked `blocked` — they can't follow/appear to each other."""
    blocker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocking_set")
    blocked = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocked_by_set")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("blocker", "blocked")


def blocked_user_ids(user):
    """IDs the user has blocked OR been blocked by — hide both directions."""
    if not user or not user.is_authenticated:
        return set()
    out = set(Block.objects.filter(blocker=user).values_list("blocked_id", flat=True))
    out |= set(Block.objects.filter(blocked=user).values_list("blocker_id", flat=True))
    return out


# ---- Social graph: follow / friends / fans ----
class Follow(models.Model):
    """follower → following. Mutual follows are friends; a one-way follower is
    a fan of the followed user."""
    follower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="following_set")
    following = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="follower_set")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("follower", "following")


def social_sources(user):
    """Every follower source that counts toward reach: the Music ConnectZ
    follower count (always verified — it's our own number) plus each connected
    external account from Profile.links that has been VERIFIED (real count +
    proven to belong to this user). Unverified links are returned too but
    flagged so callers can exclude them from the median (anti-cheat: nobody
    games reach by typing a stranger's big follower number).

    Each source: {label, followers, verified}."""
    mcz_followers = len(set(
        Follow.objects.filter(following=user).values_list("follower_id", flat=True)
    ))
    sources = [{"label": "Music ConnectZ", "followers": mcz_followers, "verified": True}]
    p = getattr(user, "mcz_profile", None)
    for link in (getattr(p, "links", None) or []):
        if not isinstance(link, dict):
            continue
        try:
            followers = int(link.get("followers") or 0)
        except (TypeError, ValueError):
            followers = 0
        verified = bool(link.get("verified"))
        # Prefer the independently verified count when we have one.
        if verified and link.get("verified_count") is not None:
            try:
                followers = int(link.get("verified_count") or 0)
            except (TypeError, ValueError):
                pass
        sources.append({
            "label": link.get("label") or link.get("url") or "link",
            "followers": followers,
            "verified": verified,
        })
    return sources


def reach_median(user):
    """Median follower count across all VERIFIED sources. Median (not sum) so a
    single huge account can't dominate — it's the typical reach across the
    creator's proven presence. Unverified links are excluded."""
    counts = [s["followers"] for s in social_sources(user) if s.get("verified")]
    m = _median(counts)
    return int(m) if m is not None else 0


def follow_counts(user):
    """followers / following / friends(mutual) / fans(one-way) for a user, plus
    verified external social sources and the median reach across them."""
    following_ids = set(Follow.objects.filter(follower=user).values_list("following_id", flat=True))
    follower_ids = set(Follow.objects.filter(following=user).values_list("follower_id", flat=True))
    friends = following_ids & follower_ids           # mutual
    fans = follower_ids - following_ids              # follow you, you don't follow back
    sources = social_sources(user)
    verified_external = sum(
        s["followers"] for s in sources
        if s.get("verified") and s["label"] != "Music ConnectZ"
    )
    return {
        "followers": len(follower_ids),
        "following": len(following_ids),
        "friends": len(friends),
        "fans": len(fans),
        "sources": sources,
        "reach_median": reach_median(user),
        # Back-compat: external_followers = sum of verified externals.
        "external_followers": verified_external,
        "total_followers": len(follower_ids) + verified_external,
    }


def energy_rate_per_hour(user):
    """Hourly passive energy by tier, from the MEDIAN reach across a creator's
    verified sources (Music ConnectZ + verified external accounts):
    Free = median/10, Premium = median/5, StatZ = median/1."""
    reach = reach_median(user)
    m = membership_for(user)
    divisor = {TIER_FREE: 10, TIER_PREMIUM: 5, TIER_STATZ: 1, TIER_DEBUG: 1}.get(m.tier, 10)
    base = reach // divisor
    # BadgeZ effects are read HERE, by the thing they affect. A badge whose
    # multiplier lived only in its description would be a sticker.
    mult = badge_effects(user).get("energy_multiplier", 1.0)
    return int(base * mult)


# Being away shouldn't bank Energy forever — it regenerates like mana, it is
# not a savings account. A member gone a week comes back to a day's worth.
ENERGY_CATCHUP_HOURS = 24


def settle_energy(user):
    """Pay the passive Energy owed since the last settlement. Returns the wallet.

    `energy_rate_per_hour` has been published on the profile since reach
    shipped and NOTHING EVER PAID IT — the app stated an hourly rate and the
    wallet never moved, so every member's passive income was a number on a
    screen. This is the other half of that promise.

    Whole hours only, with the remainder left on the clock: a member who
    refreshes every ten minutes must earn exactly what one who refreshes once a
    day earns. Advancing the clock to `now` would round their partial hour away
    on every single page load, which is worse than not accruing at all.
    """
    from datetime import timedelta

    from django.utils import timezone

    w = wallet_for(user)
    now = timezone.now()
    # First ever settlement starts the clock rather than back-paying to signup.
    if w.energy_accrued_at is None:
        w.energy_accrued_at = now
        w.save(update_fields=["energy_accrued_at", "updated_at"])
        return w
    hours = int((now - w.energy_accrued_at).total_seconds() // 3600)
    if hours <= 0:
        return w
    w.energy_accrued_at = w.energy_accrued_at + timedelta(hours=hours)
    w.save(update_fields=["energy_accrued_at", "updated_at"])
    granted = energy_rate_per_hour(user) * min(hours, ENERGY_CATCHUP_HOURS)
    if granted:
        # Through award_energy so it lands in LogZ. A balance that changes
        # while you were away, with no line saying why, reads as a bug.
        award_energy(user, granted, f"Passive Energy — {min(hours, ENERGY_CATCHUP_HOURS)}h at reach")
        w.refresh_from_db()
    return w


def relationship(me, other):
    """How `me` relates to `other`: is_following (me→other), follows_me
    (other→me), and a label (friends | fan | following | none)."""
    if not me or not other or me.id == other.id:
        return {"is_following": False, "follows_me": False, "label": "self"}
    i_follow = Follow.objects.filter(follower=me, following=other).exists()
    they_follow = Follow.objects.filter(follower=other, following=me).exists()
    label = "friends" if (i_follow and they_follow) else "fan" if they_follow else "following" if i_follow else "none"
    return {"is_following": i_follow, "follows_me": they_follow, "label": label}


# ---- DirectZ video works (ReelZ / EpisodeZ / MovieZ) ----
class DirectZWork(models.Model):
    """A collaborative video work. Contributors bring skills at a price; the
    work is AI-rated on submit, then real user ratings take over as they land."""
    FMT_CHOICES = [("reelz", "ReelZ"), ("episodez", "EpisodeZ"), ("moviez", "MovieZ")]
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="directz_works")
    fmt = models.CharField(max_length=12, choices=FMT_CHOICES, default="reelz")
    video_type = models.CharField(max_length=40, blank=True, default="")   # Music / Bio / Promotional Video
    genre = models.CharField(max_length=40, blank=True, default="")        # format-appropriate: TV / movie / short
    mood = models.CharField(max_length=32, blank=True, default="")
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    duration_sec = models.PositiveIntegerField(default=0)
    media_url = models.CharField(max_length=500, blank=True, default="")   # uploaded video
    media_type = models.CharField(max_length=60, blank=True, default="")
    contributors = models.JSONField(default=list, blank=True)  # [{name, tier, skills:[{name, price}]}]
    # NULL means "not rated", and that is a real state rather than a gap.
    #
    # This used to default to 0 and be filled by `directz_ai_rating`, which
    # called itself a craft estimate and measured contributor count, description
    # length and money spent. It taught members to pad the form. It is gone; the
    # score now comes from a model that watches the video (`directz_craft.py`).
    #
    # When the video can't be watched — no key, an unreadable container, or a
    # MovieZ far past the 14MB the inline path can carry — the work keeps NO
    # rating and `rating_note` says why. An empty rating invites a real one from
    # members; a fabricated one ends the question.
    ai_rating = models.FloatField(null=True, blank=True)
    # The dimensions behind the score — framing, editing, lighting, sound,
    # story — plus the verdict and what to fix. See directz_craft.CRAFT_SCORES.
    craft = models.JSONField(default=dict, blank=True)
    rating_note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class DirectZRating(models.Model):
    rater = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="directz_ratings")
    work = models.ForeignKey(DirectZWork, on_delete=models.CASCADE, related_name="ratings")
    score = models.PositiveSmallIntegerField()  # 1-10
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("rater", "work")


# Real user ratings take over once RATING_MIN_RATERS people have rated;
# before that the AI seed stands.
DIRECTZ_MIN_RATERS = 3

# Length bands per category (seconds): ReelZ 30s–30m · EpisodeZ 30–60m · MovieZ 1–3h.
DIRECTZ_BANDS = {"reelz": (30, 1800), "episodez": (1800, 3600), "moviez": (3600, 10800)}


def directz_band_for(sec):
    """Which format a given duration (seconds) fits, or None if out of all bands."""
    for fmt, (lo, hi) in DIRECTZ_BANDS.items():
        if lo <= sec <= hi:
            return fmt
    return None


def directz_ai_rating(work):
    """DEPRECATED — do not call this for a rating. See `directz_craft.py`.

    It called itself "a deterministic AI craft estimate" and measured contributor
    count, skills listed, description length, money spent and duration fit. None
    of that is craft: a weak video with five contributors and a padded
    description scored ~8, a good one-person video with a terse description
    scored ~4. It taught members to pad the form, which is the failure
    `CLAUDE.md`'s third rule names.

    Kept only because a handful of old rows were seeded by it and the number is
    still on them; nothing should produce a NEW one. A work whose video cannot be
    watched now carries no rating at all, which is the honest answer.
    """
    contribs = work.get("contributors") if isinstance(work, dict) else work.contributors
    desc = work.get("description") if isinstance(work, dict) else work.description
    dur = work.get("duration_sec") if isinstance(work, dict) else work.duration_sec
    fmt = work.get("fmt") if isinstance(work, dict) else work.fmt
    contribs = contribs or []
    n_people = len(contribs)
    n_skills = sum(len(c.get("skills") or []) for c in contribs)
    worth = sum((float(s.get("price") or 0) for c in contribs for s in (c.get("skills") or [])))
    # Duration-fit: does the length match the format band?
    lo, hi = DIRECTZ_BANDS.get(fmt, (0, 10 ** 9))
    fit = 1.0 if (dur and lo <= dur <= hi) else 0.4
    score = (
        3.0
        + min(n_people, 5) * 0.7        # collaboration breadth
        + min(n_skills, 8) * 0.35       # skills brought
        + min(len(desc or ""), 300) / 300 * 1.5  # described intent
        + min(worth, 500) / 500 * 1.0   # investment
    ) * fit
    return round(max(1.0, min(10.0, score)), 1)


def directz_display_rating(work):
    """Real-user median once >=3 rate; otherwise the AI score, if there is one.

    Three states rather than two, because "nobody has rated this and the model
    couldn't watch it" is a real answer and it used to be reported as a number.
    `source` is "users", "ai", or None — and when it is None, `rating` is None
    too. Callers must render the absence rather than reaching for a zero.
    """
    scores = list(work.ratings.values_list("score", flat=True))
    user_median = _median(scores)
    ai = round(work.ai_rating, 1) if work.ai_rating is not None else None
    if len(scores) >= DIRECTZ_MIN_RATERS:
        return {"rating": user_median, "source": "users", "ai_rating": ai,
                "user_median": user_median, "count": len(scores)}
    return {"rating": ai, "source": "ai" if ai is not None else None,
            "ai_rating": ai, "user_median": user_median, "count": len(scores)}


# ---- Universal social layer (cross-user reactions + comments) ----
class Reaction(models.Model):
    """One like (+1) or dislike (-1) per user per item. `item_id` is an opaque
    client key like 'post:123', 'battle:1v1', 'collab:...'."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reactions")
    item_id = models.CharField(max_length=160, db_index=True)
    value = models.SmallIntegerField(default=0)  # 1 like, -1 dislike
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "item_id")


class ItemRating(models.Model):
    """A 1-10 rating on any social item (post, work, profile, battle…), keyed by
    the same opaque item_id as reactions/comments. One rating per user per item."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="item_ratings")
    item_id = models.CharField(max_length=160, db_index=True)
    score = models.PositiveSmallIntegerField()  # 1-10
    created_at = models.DateTimeField(auto_now_add=True, null=True)  # window anchor
    updated_at = models.DateTimeField(auto_now=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    edit_history = models.JSONField(default=list, blank=True)  # [{score, at}] prior scores

    class Meta:
        unique_together = ("user", "item_id")


def item_rating_median(item_id):
    return _median(ItemRating.objects.filter(item_id=item_id).values_list("score", flat=True))


class SocialComment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_comments")
    item_id = models.CharField(max_length=160, db_index=True)
    # TextField for the same reason as Profile.bio — comments are covered by
    # the tier char limit, which Premium takes to 1,500 and StatZ removes.
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    edit_history = models.JSONField(default=list, blank=True)  # [{body, at}] prior versions

    class Meta:
        ordering = ["-created_at"]


# ---- MerchZ (legal goods marketplace) ----
def merch_path(instance, filename):
    return f"merch/{instance.seller_id}/{filename}"


class MerchItem(models.Model):
    # Legal goods only — apparel, art, audio, digital. No substances/paraphernalia.
    CATEGORIES = ["apparel", "art", "beats", "samples", "accessories", "digital", "routines"]
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="merch_items")
    title = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True, default="")
    category = models.CharField(max_length=32, default="apparel")
    price_cents = models.PositiveIntegerField(default=0)
    image = models.ImageField(upload_to=merch_path, blank=True, null=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class MerchPurchase(models.Model):
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="merch_purchases")
    item = models.ForeignKey(MerchItem, on_delete=models.CASCADE, related_name="purchases")
    price_cents = models.PositiveIntegerField(default=0)
    dev_tax_cents = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


# ---- CollabZ escrow deals ----
def collab_settlement(participants, currency="money"):
    """Server-side port of the frontend `collabSettlement()` (economy.js): the
    "everyone paid their worth" rule. Each participant pays an equal
    worth/(n-1) share of every OTHER person's worth, and receives their own
    worth funded by the others, net of the payer's developer tax. SpinAZ deals
    carry no dev tax (matching how SpinAZ is treated elsewhere).

    Input:  [{username, tier, worth_cents}]
    Output: same dicts with pays_cents / receives_cents / tax_cents added.

    Conservation: sum(pays) == pot, and sum(receives) + platform_tax == pot.
    Because each value is rounded to whole cents independently, the *actual*
    platform take is defined at settlement as (held - sum(receives)); tax_cents
    here is the informational per-payer figure."""
    ps = [{
        "username": p.get("username"),
        "tier": p.get("tier") or TIER_FREE,
        "worth_cents": max(0, int(p.get("worth_cents") or 0)),
    } for p in (participants or [])]
    n = len(ps)
    if n < 2:
        for p in ps:
            p.update(pays_cents=0, receives_cents=0, tax_cents=0)
        return ps

    def rate(p):
        return 0.0 if currency == "spinaz" else DEV_TAX.get(p["tier"], DEV_TAX[TIER_FREE])

    for i, p in enumerate(ps):
        pays = 0.0
        receives = 0.0
        for j, q in enumerate(ps):
            if j == i:
                continue
            pays += q["worth_cents"] / (n - 1)               # p funds a share of q's worth
            receives += (p["worth_cents"] / (n - 1)) * (1 - rate(q))  # q funds p's worth, net of q's tax
        p["pays_cents"] = int(round(pays))
        p["receives_cents"] = int(round(receives))
        p["tax_cents"] = int(round(pays * rate(p)))
    return ps


class CollabDeal(models.Model):
    """An escrowed CollabZ settlement. Money (or SpinAZ) each payer owes is HELD
    by the deal — not paid to recipients — until the payers approve release (or
    it auto-releases after a window). Refundable during the dispute window. This
    is the trust primitive that lets a stranger take the first deal."""
    CURRENCY_MONEY = "money"
    CURRENCY_SPINAZ = "spinaz"
    CURRENCY_CHOICES = [(CURRENCY_MONEY, "Money"), (CURRENCY_SPINAZ, "SpinAZ")]

    STATUS_DRAFT = "draft"
    STATUS_FUNDED = "funded"
    STATUS_DELIVERED = "delivered"
    STATUS_RELEASED = "released"
    STATUS_DISPUTED = "disputed"
    STATUS_REFUNDED = "refunded"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_FUNDED, "Funded"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_RELEASED, "Released"),
        (STATUS_DISPUTED, "Disputed"),
        (STATUS_REFUNDED, "Refunded"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    initiator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="collab_deals")
    title = models.CharField(max_length=160, blank=True, default="")
    currency = models.CharField(max_length=8, choices=CURRENCY_CHOICES, default=CURRENCY_MONEY)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    stake_spinaz = models.PositiveIntegerField(default=0)  # optional good-faith stake per participant
    # Settlement plan: [{username, tier, worth_cents, pays_cents, receives_cents,
    # tax_cents, funded, stake_paid}]
    participants = models.JSONField(default=list, blank=True)
    held_cents = models.PositiveIntegerField(default=0)
    held_spinaz = models.PositiveIntegerField(default=0)
    held_stake_spinaz = models.PositiveIntegerField(default=0)
    gates = models.JSONField(default=dict, blank=True)
    # PostZ is for show; CollabZ is for collaboration. This is the seam between
    # them: the post somebody heard and then wanted to work on. SET_NULL because
    # deleting the showcase must never delete the deal — money is escrowed
    # against it.
    source_post = models.ForeignKey(Post, on_delete=models.SET_NULL, null=True,
                                    blank=True, related_name="collab_deals")
    # What this deal is LOOKING FOR: [{slot, skill}]. An artist arrives with a
    # song and needs a cover and a video — saying which slots are open, and
    # what skill fills them, is what turns a deal into something findable by
    # the designer who can take it.
    needs = models.JSONField(default=list, blank=True)
    # A deal carries the WORK, in the same shape a post does: record or upload
    # audio/video, an image, and the lyrics or script. Without it a deal is a
    # settlement about something nobody in it can actually hear.
    description = models.TextField(blank=True, default="")
    media_type = models.CharField(max_length=24, blank=True, default="")
    media_url = models.CharField(max_length=500, blank=True, default="")
    image_url = models.CharField(max_length=500, blank=True, default="")
    lyrics = models.TextField(blank=True, default="")
    items = models.JSONField(default=list, blank=True)   # album: [{url,type,title,lyrics}]
    # How the pot is divided at release. "worth" is the agreed settlement;
    # "rating" re-cuts it by what the community thought each person contributed.
    SPLIT_WORTH, SPLIT_RATING = "worth", "rating"
    SPLIT_CHOICES = [(SPLIT_WORTH, "By agreed worth"), (SPLIT_RATING, "By contribution rating")]
    split_mode = models.CharField(max_length=8, choices=SPLIT_CHOICES, default=SPLIT_WORTH)
    # What the ratings were AT RELEASE, and why the split came out as it did.
    # Frozen deliberately: a live split means your cut changes after you agreed
    # to it, and money that moves under you is not a deal.
    split_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    auto_release_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"CollabDeal<{self.id}> {self.status} {self.title}"

    def payers(self):
        return [p for p in self.participants if int(p.get("pays_cents") or 0) > 0]

    def all_funded(self):
        return all(p.get("funded") for p in self.payers())


# --- Rewarded ads (AdMob SSV) & offerwall (OfferZ) grants -------------------
# One row per external reward callback, keyed by the provider's unique
# transaction id, so a replayed callback can never pay a user twice.
class RewardGrant(models.Model):
    PROVIDER_ADMOB = "admob"
    PROVIDER_OFFERZ = "offerz"
    provider = models.CharField(max_length=16)
    txn_id = models.CharField(max_length=191)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reward_grants")
    spinaz = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("provider", "txn_id")
        indexes = [models.Index(fields=["provider", "-created_at"])]


# ---- ObservationZ — HabitZ 🫠 / CodeZ 🧩 / PathZ 🛤️ / MistakeZ 😢
#
# Four tabs, one shape: notice something happen, tally it, surface what repeats
# enough to matter. Building them separately would mean four slightly different
# tally semantics, the way the char limit ended up in nine places.
#
# These record what a member types and where they go, which is surveillance
# unless they asked for it. Nothing is recorded without an explicit opt-in per
# kind, and every kind can be wiped. Consent bolted on afterwards leaves you
# holding data you were never allowed to keep.
OBS_HABIT, OBS_CODE, OBS_PATH, OBS_MISTAKE = "habit", "code", "path", "mistake"
OBSERVATION_KINDS = [
    (OBS_HABIT, "HabitZ"), (OBS_CODE, "CodeZ"),
    (OBS_PATH, "PathZ"), (OBS_MISTAKE, "MistakeZ"),
]


class ObservationConsent(models.Model):
    """Per-kind opt-in. Absent means off — never on by default."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="observation_consents")
    kind = models.CharField(max_length=12, choices=OBSERVATION_KINDS)
    enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "kind")


class Observation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="observations")
    kind = models.CharField(max_length=12, choices=OBSERVATION_KINDS, db_index=True)
    # Stable identity of the thing repeating — a slug, a route, an error code.
    key = models.CharField(max_length=160)
    # What to show a human. The key is for matching, this is for reading.
    label = models.CharField(max_length=200, blank=True, default="")
    # Cross-pollination: nothing is a dead end. Whatever noticed this records
    # WHERE it happened, so the row can open in that app to be edited or
    # analysed rather than being a fact you can only read.
    app_key = models.CharField(max_length=32, blank=True, default="")
    target = models.CharField(max_length=160, blank=True, default="")
    count = models.PositiveIntegerField(default=0)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    # Member said "this isn't a habit" — kept so it stops being re-surfaced,
    # rather than deleted and immediately re-learned.
    dismissed = models.BooleanField(default=False, db_index=True)

    class Meta:
        unique_together = ("user", "kind", "key")
        ordering = ["-count", "-last_seen"]

    def __str__(self):
        return f"{self.kind}:{self.key} x{self.count}"


def observing(user, kind):
    """Whether this member asked to be observed for this kind. Default: no."""
    if not user or not getattr(user, "is_authenticated", True):
        return False
    c = ObservationConsent.objects.filter(user=user, kind=kind).first()
    return bool(c and c.enabled)


def record_observation(user, kind, key, label="", app_key="", target=""):
    """Tally one occurrence. Silent no-op without consent.

    Best-effort: noticing a habit must never be the reason the thing the member
    was actually doing fails.
    """
    key = str(key or "").strip()[:160]
    if not key or not observing(user, kind):
        return None
    try:
        obs, made = Observation.objects.get_or_create(
            user=user, kind=kind, key=key,
            defaults={"label": str(label or key)[:200], "count": 0,
                      "app_key": str(app_key or "")[:32], "target": str(target or "")[:160]},
        )
        obs.count = (obs.count or 0) + 1
        if label and not obs.label:
            obs.label = str(label)[:200]
        if app_key and not obs.app_key:
            obs.app_key = str(app_key)[:32]
        if target and not obs.target:
            obs.target = str(target)[:160]
        obs.save(update_fields=["count", "label", "app_key", "target", "last_seen"])
        return obs
    except Exception:  # pragma: no cover - never break the caller
        return None


# How many repeats before it is worth telling somebody about. Twice is a
# coincidence; this is the line where "you keep doing this" stops being noise.
SIGNIFICANT_AT = 3


# ---- Trial Boss Take (no account required) ----
#
# A stranger records one take, gets it scored, and is handed a token. Signing up
# with that token attaches the take to the new account, so the trial is not a
# dead end — the thing they made in the door opens inside SingZ/RapZ.
#
# It costs real money to run (Gemini), and an unauthenticated endpoint that
# spends money is a bill anybody with curl can run up. Hence both caps below.
TRIAL_MAX_MB = 8
TRIAL_PER_IP_HOURS = 24          # one free scored take per address per day
TRIAL_CLAIM_DAYS = 30            # a token stays claimable this long


def trial_daily_cap():
    """Global ceiling on trial takes per day. Tunable without a deploy."""
    import os
    try:
        return max(0, int(os.environ.get("TRIAL_TAKES_PER_DAY", "200")))
    except (TypeError, ValueError):
        return 200


class TrialTake(models.Model):
    """One Boss Take scored for somebody who has no account yet."""
    token = models.CharField(max_length=64, unique=True, db_index=True)
    app_key = models.CharField(max_length=32, default="singz")
    ip = models.CharField(max_length=64, blank=True, default="", db_index=True)
    result = models.JSONField(default=dict, blank=True)
    claimed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name="trial_takes",
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.app_key} trial {self.token[:8]}"


def claim_trial_take(user, token):
    """Attach a trial take to a brand-new account. Returns it, or None.

    Idempotent and best-effort: a bad or expired token must never be the reason
    a registration fails.
    """
    from datetime import timedelta
    token = str(token or "").strip()[:64]
    if not token:
        return None
    cutoff = timezone.now() - timedelta(days=TRIAL_CLAIM_DAYS)
    take = TrialTake.objects.filter(
        token=token, claimed_by__isnull=True, created_at__gte=cutoff
    ).first()
    if not take:
        return None
    take.claimed_by = user
    take.claimed_at = timezone.now()
    take.save(update_fields=["claimed_by", "claimed_at"])
    return take


# ---- PlaylistZ ----
#
# A playlist mixes what lives HERE with what lives everywhere else: a member's
# Music ConnectZ posts sitting in the same running order as their Spotify,
# YouTube, SoundCloud and Bandcamp links. That mix is the point. A member's work
# is scattered across half a dozen distributors and no single page has ever been
# able to say "this is the set, in this order" without picking one platform and
# abandoning the rest.
#
# Every row knows where it came from and where it opens, so a playlist is a
# junction rather than a terminus: a post row opens the post, a link row opens
# the distributor AND tallies through the same LinkCounter a profile link does.
PLAYLIST_MAX_ITEMS = 200

# Host → provider key. Matched on the registrable suffix, so
# `open.spotify.com` and `play.spotify.com` are both spotify.
LINK_PROVIDERS = [
    ("spotify.com", "spotify"),
    ("youtube.com", "youtube"),
    ("youtu.be", "youtube"),
    ("music.apple.com", "apple"),
    ("apple.com", "apple"),
    ("soundcloud.com", "soundcloud"),
    ("bandcamp.com", "bandcamp"),
    ("tidal.com", "tidal"),
    ("deezer.com", "deezer"),
    ("audiomack.com", "audiomack"),
    ("music.amazon.com", "amazon"),
    ("pandora.com", "pandora"),
    ("audius.co", "audius"),
    ("mixcloud.com", "mixcloud"),
    ("bandlab.com", "bandlab"),
    ("distrokid.com", "distrokid"),
    ("tiktok.com", "tiktok"),
    ("instagram.com", "instagram"),
]


def link_provider(url):
    """Which distributor a URL points at, or "" when it's nobody we know.

    An unknown host is still a perfectly good playlist row — it just renders
    without a badge. Guessing a provider we can't identify would be worse than
    saying nothing.
    """
    from urllib.parse import urlparse
    try:
        host = (urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    for suffix, key in LINK_PROVIDERS:
        if host == suffix or host.endswith("." + suffix):
            return key
    return ""


class Playlist(models.Model):
    """An ordered set that may mix Music ConnectZ posts and outside links."""
    VIS_CHOICES = [("public", "Public"), ("restricted", "Restricted"), ("private", "Private")]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="playlists")
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    cover_url = models.CharField(max_length=600, blank=True, default="")
    visibility = models.CharField(max_length=12, choices=VIS_CHOICES, default="public")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)

    def __str__(self):
        return self.title

    @property
    def item_key(self):
        """The id RateZ / comments / reactions already key off. A playlist gets
        ratings and a comment thread for free by reusing SocialView's item
        space rather than growing a second one beside it."""
        return f"playlist:{self.id}"


class PlaylistItem(models.Model):
    KIND_POST, KIND_LINK = "post", "link"
    KIND_CHOICES = [(KIND_POST, "Music ConnectZ post"), (KIND_LINK, "Outside link")]

    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name="items")
    position = models.PositiveIntegerField(default=0)
    kind = models.CharField(max_length=8, choices=KIND_CHOICES, default=KIND_LINK)
    # SET_NULL, not CASCADE: a deleted post should leave a gap the owner can see
    # and remove, not silently reshuffle a set list they curated.
    post = models.ForeignKey(Post, on_delete=models.SET_NULL, null=True, blank=True, related_name="playlist_items")
    url = models.CharField(max_length=600, blank=True, default="")
    provider = models.CharField(max_length=24, blank=True, default="")
    title = models.CharField(max_length=200, blank=True, default="")
    artist = models.CharField(max_length=160, blank=True, default="")
    # Who put it in. On a collaborative list this decides two things: whose
    # reach an outside link's clicks feed, and who is allowed to take it back
    # out. Null on rows added before playlists were collaborative.
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="playlist_rows")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("position", "id")

    def __str__(self):
        return self.title or self.url or f"item {self.pk}"


class PlaylistCollaborator(models.Model):
    """Someone the owner let add to their playlist.

    Invite-only, deliberately. An open playlist anybody can append to is a spam
    target with the owner's name on it.
    """
    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name="collaborators")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="playlist_seats")
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="playlist_invites_sent")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("playlist", "user")
        ordering = ("added_at",)


def can_add_to_playlist(pl, user):
    """Owner or invited collaborator."""
    if not user or not user.is_authenticated:
        return False
    if pl.owner_id == user.id:
        return True
    return PlaylistCollaborator.objects.filter(playlist=pl, user=user).exists()


# ---- KeyConnectZ ----
#
# The keyboard. Two halves, gated differently on purpose:
#
#   * The WALLPAPER is Premium. It is decoration — pure want, no utility lost
#     by not having it — which makes it exactly the right thing to sell.
#   * TRANSLATE is free for every member, in any direction. Being understood is
#     not a luxury. A Free member typing to somebody in another language is the
#     single most useful thing this keyboard does, and charging for it would
#     price the app out of the rooms it exists to open.
#
# Free doesn't mean uncapped: it runs a real model and an unmetered LLM call is
# a bill anybody can run up. The cap is per member per day and is published by
# the API before anyone types, not discovered by hitting it.
KEY_WALLPAPER_MAX_MB = 8
KEY_TRANSLATE_DAILY_CHARS = 20_000       # per member, per day — ~40 messages
KEY_TRANSLATE_MAX_CHARS = 2_000          # per single translation


class KeyboardSkin(models.Model):
    """A member's KeyConnectZ look. One row per member."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="keyboard_skin")
    wallpaper = models.ImageField(upload_to="keyboards/", blank=True, null=True)
    # Falls back to a flat colour when there's no wallpaper, so a Free member
    # still gets a keyboard that looks like a choice rather than a default.
    accent = models.CharField(max_length=9, blank=True, default="")     # #rrggbb
    key_opacity = models.PositiveSmallIntegerField(default=85)          # 0-100
    dark_keys = models.BooleanField(default=True)
    # Last language pair used, so the keyboard opens where it was left.
    source_lang = models.CharField(max_length=12, blank=True, default="auto")
    target_lang = models.CharField(max_length=12, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)


def keyboard_skin_for(user):
    return KeyboardSkin.objects.get_or_create(user=user)[0]


class KeyTranslation(models.Model):
    """One translation run, for the daily allowance and for LogZ-style honesty
    about what the keyboard has been doing."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="key_translations")
    source_lang = models.CharField(max_length=12, blank=True, default="")
    target_lang = models.CharField(max_length=12, blank=True, default="")
    chars = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


def key_translate_used_today(user):
    """Characters translated in the last 24h."""
    from datetime import timedelta
    rows = KeyTranslation.objects.filter(
        user=user, created_at__gte=timezone.now() - timedelta(hours=24))
    return sum(rows.values_list("chars", flat=True))


def key_translate_state(user):
    """(used, cap, remaining) — published BEFORE anyone types, not on refusal.

    `cap` and `remaining` come back as None for a member whose badges lift the
    cap. None rather than a very large number on purpose: a screen that reads
    the number would print "999,999,999 characters left", which is a limit
    nobody set pretending to be one somebody did.
    """
    used = key_translate_used_today(user)
    if badge_effects(user).get("translate_uncapped"):
        return used, None, None
    return used, KEY_TRANSLATE_DAILY_CHARS, max(0, KEY_TRANSLATE_DAILY_CHARS - used)


# ---- BattleZ ----
#
# BattleZ has been named in the app since the tab bar was written and has never
# had a single row behind it — so "BattleZ carries the range gates" was a
# promise with nothing to enforce. This is the smallest honest version: a
# challenge that carries the work in the PostZ format, gates who may enter, and
# is judged by the same RateZ item space everything else is judged by.
# A contestant needs a real number of judges before a win means anything. Same
# figure as the CollabZ rating split — three is where "somebody liked it" turns
# into "people thought so".
BATTLE_MIN_RATINGS = 3
BATTLE_WINDOW_HOURS = 48


class Battle(models.Model):
    # 1v1 is the shape people actually mean by a battle: you name somebody, they
    # accept, you both put a take up, the room decides. `open` is the
    # host-a-challenge variant where anyone may enter.
    MODE_1V1, MODE_OPEN = "1v1", "open"
    MODE_CHOICES = [(MODE_1V1, "1v1"), (MODE_OPEN, "Open challenge")]

    STATUS_PENDING = "pending"      # challenged, not answered
    STATUS_OPEN = "open"            # live — takes and ratings accepted
    STATUS_DECLINED = "declined"
    STATUS_SETTLED = "settled"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"), (STATUS_OPEN, "Open"),
        (STATUS_DECLINED, "Declined"), (STATUS_SETTLED, "Settled"),
        (STATUS_CLOSED, "Closed"),
    ]

    host = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="battles")
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    # The work, same shape as a post.
    media_type = models.CharField(max_length=24, blank=True, default="")
    media_url = models.CharField(max_length=500, blank=True, default="")
    image_url = models.CharField(max_length=500, blank=True, default="")
    lyrics = models.TextField(blank=True, default="")
    genre = models.CharField(max_length=40, blank=True, default="")
    # The same five exclusive ranges search and VenueZ use. One spec, so what a
    # host advertises and what the door enforces cannot diverge.
    gates = models.JSONField(default=dict, blank=True)
    entry_spinaz = models.PositiveIntegerField(default=0)
    # Defaults to OPEN: a battle created without an opponent has nobody to
    # face, and calling that a 1v1 is a state that should not exist. The
    # challenge endpoint sets 1v1 explicitly, alongside the opponent.
    mode = models.CharField(max_length=8, choices=MODE_CHOICES, default=MODE_OPEN)
    kind = models.CharField(max_length=16, blank=True, default="1v1")   # 1v1 | freestyle | cypher

    # 1v1 only. Null on an open challenge.
    opponent = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 null=True, blank=True, related_name="battles_faced")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN)
    accepted_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    winner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                               null=True, blank=True, related_name="battles_won")
    settled_at = models.DateTimeField(null=True, blank=True)
    # SpinaZ held from spectators until the result is in. Held, not spent — a
    # battle that never settles must give every wager back.
    held_wager_spinaz = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    @property
    def item_key(self):
        return f"battle:{self.id}"

    @property
    def contestants(self):
        """The two people whose work is being judged. Nobody else may wager."""
        return [u for u in (self.host, self.opponent) if u]


class BattleWager(models.Model):
    """A spectator's SpinaZ on one side.

    The stake leaves their wallet the moment it's placed and is HELD by the
    battle — the same escrow shape CollabZ uses, for the same reason: a promise
    to pay later is not a wager, and a pool that only exists on paper can't be
    paid out.
    """
    SIDE_HOST, SIDE_OPPONENT = "host", "opponent"
    SIDE_CHOICES = [(SIDE_HOST, "Host"), (SIDE_OPPONENT, "Opponent")]

    battle = models.ForeignKey(Battle, on_delete=models.CASCADE, related_name="wagers")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="battle_wagers")
    side = models.CharField(max_length=8, choices=SIDE_CHOICES)
    amount = models.PositiveIntegerField(default=0)
    paid_out = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # One wager per person per battle. Letting somebody stack both sides
        # turns a bet into a no-op with extra steps.
        unique_together = ("battle", "user")
        ordering = ("created_at",)


class MoneyBattleVote(models.Model):
    """"Should real-money battles exist?" — one vote per member.

    Real-money wagering is regulated gambling in most places, so this stays a
    signal rather than a switch. Counting who wants it is honest; shipping it
    on a show of hands would not be.
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="money_battle_vote")
    created_at = models.DateTimeField(auto_now_add=True)


class BattleEntry(models.Model):
    """One member's answer to the challenge — again in the PostZ format."""
    battle = models.ForeignKey(Battle, on_delete=models.CASCADE, related_name="entries")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="battle_entries")
    title = models.CharField(max_length=160, blank=True, default="")
    media_type = models.CharField(max_length=24, blank=True, default="")
    media_url = models.CharField(max_length=500, blank=True, default="")
    image_url = models.CharField(max_length=500, blank=True, default="")
    lyrics = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("battle", "user")
        ordering = ("created_at",)

    @property
    def item_key(self):
        return f"battle:{self.battle_id}:entry:{self.id}"


# ---- OCC: TaskZ ----
#
# The spec's own priority: "prioritize git integration synchronous with taskz
# because git integration becomes a task". So a git action is not a side
# channel — it is a TaskZ row like any other, with the same status, the same
# live updates, and the same undo window. One list, one truth about what OCC
# is doing to your code.
OCC_UNDO_SECONDS = {TIER_FREE: 4 * 60, TIER_PREMIUM: 40 * 60,
                    TIER_STATZ: 4 * 3600, TIER_DEBUG: 10 ** 9}


def occ_undo_window(tier):
    """How long a task stays undoable. Deliberately the same ladder as the edit
    window — "how long can I take it back" should not mean two different things
    in two parts of the same app."""
    return OCC_UNDO_SECONDS.get(tier, OCC_UNDO_SECONDS[TIER_FREE])


class OccTask(models.Model):
    """One thing OCC has been asked to do."""
    STATUS_SUGGESTED = "suggested"   # SuggestionZ proposed it; not started
    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_UNDONE = "undone"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_SUGGESTED, "Suggested"), (STATUS_QUEUED, "Queued"),
        (STATUS_RUNNING, "Running"), (STATUS_DONE, "Done"),
        (STATUS_FAILED, "Failed"), (STATUS_UNDONE, "Undone"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    KIND_EDIT, KIND_GIT, KIND_BUILD, KIND_EXPORT, KIND_OTHER = (
        "edit", "git", "build", "export", "other")
    KIND_CHOICES = [(KIND_EDIT, "Edit"), (KIND_GIT, "Git"), (KIND_BUILD, "Build"),
                    (KIND_EXPORT, "Export"), (KIND_OTHER, "Other")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="occ_tasks")
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=8, choices=KIND_CHOICES, default=KIND_OTHER)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    # SuggestionZ must explain itself before anything runs — the spec is explicit
    # that "what, why and how must be explained to the user". A suggestion
    # missing any of the three is refused rather than shown half-argued.
    what = models.TextField(blank=True, default="")
    why = models.TextField(blank=True, default="")
    how = models.TextField(blank=True, default="")
    progress = models.PositiveSmallIntegerField(default=0)      # 0-100
    eta_seconds = models.PositiveIntegerField(default=0)
    detail = models.TextField(blank=True, default="")
    # Git, when this task IS a git action.
    git_repo = models.CharField(max_length=200, blank=True, default="")
    git_branch = models.CharField(max_length=120, blank=True, default="")
    git_ref = models.CharField(max_length=80, blank=True, default="")    # commit sha
    # Enough to put back what was changed. Without it "undo" is a button that
    # lies, so a task that can't describe its own reversal says undoable=False.
    undo_payload = models.JSONField(default=dict, blank=True)
    automated = models.BooleanField(default=False)   # ran with no confirmation
    # Sandbox seconds this task actually consumed. Kept on the task rather than
    # in a second table because a run IS a task — the spec's own rule is one
    # list and one truth — and the daily ceiling is summed from here.
    run_seconds = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def undo_deadline(self, tier):
        base = self.finished_at or self.created_at
        from datetime import timedelta
        return base + timedelta(seconds=occ_undo_window(tier))

    def can_undo(self, tier):
        if self.status != self.STATUS_DONE or not self.undo_payload:
            return False
        return timezone.now() <= self.undo_deadline(tier)


class OccSettings(models.Model):
    """The two toggles the spec puts front and centre, per member."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="occ_settings")
    # AutomationZ runs without asking. It is StatZ-gated and OFF by default —
    # a setting that acts on your code unasked is not one to inherit silently.
    automation = models.BooleanField(default=False)
    suggestionz = models.BooleanField(default=True)
    pinned_tabs = models.JSONField(default=list, blank=True)   # Pick ConnectZ
    updated_at = models.DateTimeField(auto_now=True)


def occ_settings_for(user):
    return OccSettings.objects.get_or_create(user=user)[0]


RATING_KINDS = [
    {"key": "post", "name": "Post rating", "of": "the work",
     "scale": "1-10", "how": "given directly on a post",
     "desc": "What people thought of this piece of work."},
    {"key": "skill", "name": "Skill rating", "of": "a skill you used",
     "scale": "1-10", "how": "derived from the posts that used it",
     "desc": "Nobody rates a skill directly. Rating a post rates every skill "
             "that went into it, for the person who brought it."},
    {"key": "contribution", "name": "Contribution rating", "of": "your part of a deal",
     "scale": "1-10", "how": "given on a CollabZ deal, by people not on it",
     "desc": "What the room thought each collaborator did — and what re-cuts "
             "the split when a deal pays on rating."},
    {"key": "overall", "name": "Overall rating", "of": "you",
     "scale": "1-10", "how": "given directly on a profile",
     "desc": "The member, not any one thing they made."},
    {"key": "attractiveness", "name": "Attractiveness", "of": "you",
     "scale": "1-10", "how": "given directly on a profile or a face",
     "desc": "Kept apart from everything else on purpose — it is not a "
             "judgement of anybody's work."},
]


# ---- BadgeZ ----
#
# A badge that only looks nice is a sticker. Every one of these changes a number
# the member can point at, and every effect is READ by the system it affects
# rather than described in copy nobody enforces.
#
# `check` is what makes a badge earned rather than claimed: it reads evidence
# already in the database. A badge with no check is `gifted` and says so.
from .catalog import FOUNDING_LIMIT as FOUNDING_SEATS   # one seat count, not two

# The most Energy any stack of badges can earn. Multipliers compound, so
# without this the ceiling is whatever badges happen to exist rather than
# something anybody chose. Today's maximum is 2 x 1.25 x 2 = 5.0, so this
# binds — which is the point of setting it before it's an accident.
MAX_ENERGY_MULTIPLIER = 3.0


def _post_rating_median(user):
    """The median of what this member's own posts scored. None if unrated."""
    keys = [f"post:{pid}" for pid in
            Post.objects.filter(author=user).values_list("id", flat=True)[:200]]
    scores = list(ItemRating.objects.filter(item_id__in=keys)
                  .values_list("score", flat=True))
    return _median(scores)


def _rated_posts(user):
    keys = [f"post:{pid}" for pid in
            Post.objects.filter(author=user).values_list("id", flat=True)[:200]]
    return ItemRating.objects.filter(item_id__in=keys).values("item_id").distinct().count()


def _shipped_collabs(user):
    return Post.objects.filter(contributor_rows__user=user).count()


def _ratings_given(user):
    return ItemRating.objects.filter(user=user).count()


def _verified_sources(user):
    p = getattr(user, "mcz_profile", None)
    return sum(1 for l in (getattr(p, "links", None) or [])
               if isinstance(l, dict) and l.get("verified"))


def _clean_deals(user):
    """Deals released with this member on them, and never disputed."""
    done = CollabDeal.objects.filter(status=CollabDeal.STATUS_RELEASED)
    n = 0
    for d in done[:500]:
        if any(p.get("username") == user.username for p in (d.participants or [])):
            n += 1
    disputed = CollabDeal.objects.filter(status=CollabDeal.STATUS_DISPUTED)
    for d in disputed[:500]:
        if any(p.get("username") == user.username for p in (d.participants or [])):
            return 0        # one open dispute and the badge isn't yours yet
    return n


def _funded_clean_deals(user):
    """Deals this member PUT MONEY INTO that released without a dispute.

    Deliberately narrower than `_clean_deals`: being credited on a deal and
    bankrolling one are different acts, and this badge is for the second. The
    `funded` flag survives release and is cleared by `refund_deal`, so a
    refunded deal never counts — money that came back was never spent.
    """
    n = 0
    for d in CollabDeal.objects.filter(status=CollabDeal.STATUS_RELEASED)[:500]:
        if any(p.get("username") == user.username and p.get("funded")
               and int(p.get("pays_cents") or 0) > 0
               for p in (d.participants or [])):
            n += 1
    for d in CollabDeal.objects.filter(status=CollabDeal.STATUS_DISPUTED)[:500]:
        if any(p.get("username") == user.username for p in (d.participants or [])):
            return 0        # same rule as Straight Shooter: one open dispute, no badge
    return n


def _translations_done(user):
    return KeyTranslation.objects.filter(user=user).count()


BADGES = {
    # ---- gifted ----
    # This badge shipped claiming `dev_tax_share: 1.0` and
    # `intelligence_royalties: True`, and NOTHING read either one. Same mistake
    # the founding badge made below, so the same fix: a badge reflects a real
    # record, it never asserts a second version of one.
    #
    # Both facts are true and neither is the badge's doing:
    #
    #   * The intelligence royalties are real and already paid. AI model
    #     charges route to `views.platform_owner()`, which resolves by
    #     OWNER_EMAILS / OWNER_USERNAMES — settings, not badges.
    #   * The developer tax is received by NOT being paid out. A member's
    #     wallet balance is a liability against cash the platform already
    #     holds, so declining to credit the tax IS the platform keeping it.
    #     `credit_funds` does exactly that.
    #
    # Wiring either to badge possession would put a deletable row in charge of
    # where money goes. What the badge genuinely applies is the tier, and
    # `grant_badge` applies it the moment it lands.
    #
    # The two facts were invisible, which is most of why they got written down
    # as effects — an unseen fact reads as an unimplemented one. They are
    # visible now: OwnerRevenueView serves what the tax has actually collected.
    "owner": {
        "icon": "badge_owner.png", "name": "Owner", "emoji": "👑", "title": "Owner", "gifted": True,
        "desc": "This is whose app it is. The developer tax and the intelligence "
                "royalties come with the job.",
        "how": "Held by the platform owner.",
        "effects": {"tier": "statz"},
        "effect_note": "StatZ for life.",
    },
    # NOT gifted, and it does NOT own the discount. A founding seat is already a
    # real thing — catalog.FOUNDING_PLANS prices it, payments.py claims it, and
    # Membership.founding records it. This badge REFLECTS that record; it must
    # never assert a second version of it.
    #
    # It shipped for one commit claiming `lifetime_discount_pct: 50`, which
    # nothing read, while the actual half-price lived in FOUNDING_PLANS. Two
    # sources of truth for "am I founding" is the exact drift this codebase
    # keeps closing, and I introduced it. The badge now adds only what is
    # genuinely its own: the Energy.
    "founding": {
        "icon": "badge_founding.png", "name": "Founding Fifty", "emoji": "🏛️", "title": "Founding Fifty", "gifted": False,
        "desc": f"One of the first {FOUNDING_SEATS} members to pay for this.",
        "how": f"Claim a founding seat in MembershipZ — {FOUNDING_SEATS} of them, "
               "at half price, and when they're gone they're gone.",
        # x2, matching Sexy on its own and clearing it once you have also
        # proven an audience (x1.25 -> 2.5). A member who paid $150 for one of
        # fifty scarce seats should not earn LESS than a member the room rated
        # attractive; the founder is exactly who would notice.
        #
        # x1.5 was the first attempt and it did not work: 1.5 x 1.25 = 1.875,
        # still under Sexy's 2.0. The test that pins the ordering caught it.
        "effects": {"energy_multiplier": 2.0},
        "effect_note": "Double Energy, on top of the half-price seat itself.",
        "check": lambda u: membership_for(u).founding,
    },
    # ---- earned ----
    "verified_reach": {
        "name": "Verified Reach", "emoji": "📡", "title": "Verified", "gifted": False,
        "desc": "An outside audience, proven rather than typed.",
        "how": "Verify one social account in SocialZ.",
        "effects": {"energy_multiplier": 1.25},
        "effect_note": "+25% passive Energy.",
        "check": lambda u: _verified_sources(u) >= 1,
    },
    "collaborator": {
        "name": "Collaborator", "emoji": "🤝", "title": "Collaborator", "gifted": False,
        "desc": "Ten pieces of work shipped with other people on them.",
        "how": "Be credited on 10 posts that came out of a CollabZ deal.",
        "effects": {"submission_bonus": 5, "needs_priority": True},
        "effect_note": "+5 submissions a day, and your open needs list first.",
        "check": lambda u: _shipped_collabs(u) >= 10,
    },
    "straight_shooter": {
        "name": "Straight Shooter", "emoji": "🎯", "title": "Straight Shooter", "gifted": False,
        "desc": "Ten deals delivered and not one dispute.",
        "how": "Release 10 CollabZ deals with no dispute open against you.",
        # Reputation buying lower friction is the honest opposite of punishing
        # flakes: it can't be aimed at anybody, so nobody can weaponise it.
        "effects": {"stake_waived": True},
        "effect_note": "No good-faith stake — your record is the stake.",
        "check": lambda u: _clean_deals(u) >= 10,
    },
    "ear": {
        "name": "The Ear", "emoji": "👂", "title": "The Ear", "gifted": False,
        "desc": "A hundred ratings given. Somebody has to do the listening.",
        "how": "Rate 100 things.",
        "effects": {"rating_cap_bonus": 20},
        "effect_note": "+20 paid ratings a day — the cap that pays, raised.",
        "check": lambda u: _ratings_given(u) >= 100,
    },
    # "Translation stops costing" needed one honest translation itself, because
    # translation already costs no 💵 and no 🏷️ — keyconnectz.py gives it away
    # at every tier on purpose. What it DOES cost is the daily character
    # allowance, so that is the thing this badge lifts. Anything else would be
    # a badge removing a price that was never charged.
    "polyglot": {
        "icon": "badge_polyglot.png", "name": "Polyglot", "emoji": "🗺️",
        "title": "Polyglot", "gifted": False,
        "desc": "Fifty translations. You talk to rooms this app couldn't reach without you.",
        "how": "Run 50 KeyConnectZ translations.",
        "effects": {"translate_uncapped": True},
        "effect_note": f"No daily limit on KeyConnectZ translation — the "
                       f"{KEY_TRANSLATE_DAILY_CHARS:,}-character allowance stops applying to you.",
        "check": lambda u: _translations_done(u) >= 50,
    },
    # The effect costs the holder their own protection and nobody else's, which
    # is what makes it safe to hand out: the auto-release window is the payer's
    # last moment to open a dispute, so shortening it is a Patron saying "pay
    # them sooner, I don't need the extra week." collab.escrow_release_days
    # only applies it when EVERY payer on the deal holds it.
    "patron": {
        "icon": "badge_patron.png", "name": "Patron", "emoji": "💸",
        "title": "Patron", "gifted": False,
        "desc": "Five deals you bankrolled, and every one released clean.",
        "how": "Fund 5 CollabZ deals that release with no dispute against you.",
        "effects": {"escrow_days_off": 7},
        "effect_note": f"Escrow on deals you fund releases in "
                       f"{max(settings.ESCROW_MIN_RELEASE_DAYS, settings.ESCROW_AUTO_RELEASE_DAYS - 7)} "
                       f"days instead of {settings.ESCROW_AUTO_RELEASE_DAYS} — "
                       "your collaborators get paid sooner for working with you.",
        "check": lambda u: _funded_clean_deals(u) >= 5,
    },
    "gifted": {
        "name": "Gifted", "emoji": "🎁", "title": "Gifted", "gifted": False,
        "icon": "badge_gifted.png", "temporary": True,
        "desc": "Your work scores 8+. Posting costs you less.",
        "how": "Hold a median rating of 8+ across at least 5 rated posts. It "
               "lapses if the median falls.",
        # Rewards the WORK, which is the thing this economy is supposed to
        # price. It reads through post_cost_cents, so the discount is on the
        # button before the post is made.
        "effects": {"post_discount_pct": 25},
        "effect_note": "25% off the Energy every post costs you.",
        "check": lambda u: (_rated_posts(u) >= 5
                            and (_post_rating_median(u) or 0) >= 8),
    },
    # Corey's call: attractiveness 8+ doubles Energy. I argued for keeping
    # attractiveness out of the economy entirely and he decided otherwise, so
    # it's ⚡×2 — and it is TEMPORARY, which is most of what worried me. It
    # tracks a live median rather than being a permanent advantage: the room
    # can take it back, and does, the moment the median drops.
    "sexy": {
        "name": "Sexy", "emoji": "🔥", "title": "Sexy", "gifted": False,
        "icon": "badge_sexy.png", "temporary": True,
        "desc": "The room rates you above 8.",
        "how": "Hold an attractiveness median above 8. Drops below and the "
               "badge goes with it.",
        "effects": {"energy_multiplier": 2.0, "social_boost": True},
        "effect_note": "⚡×2 while you hold it, and you surface higher in "
                       "member discovery.",
        "check": lambda u: (attractiveness_median(u) or 0) > 8,
    },
    "bug_hunter": {
        "name": "Bug Hunter", "emoji": "🐛", "title": "Bug Hunter", "gifted": True,
        "desc": "Found something broken and said so.",
        "how": "Gifted when a BugZ report is accepted.",
        "effects": {"promptz_grant": 50},
        "effect_note": "+50 🏷️ PromptZ, once.",
    },
}


class Badge(models.Model):
    """A badge a member holds. The catalogue itself lives in BADGES."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="badges")
    key = models.CharField(max_length=40)
    # Per-badge privacy. An achievement is also a disclosure — "Straight
    # Shooter" tells the room about your deal history — so showing it is the
    # member's call. The EFFECT applies either way: hiding a badge must never
    # cost somebody the thing they earned.
    visible = models.BooleanField(default=True)
    awarded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="badges_given")
    awarded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "key")
        ordering = ("awarded_at",)


def badges_for(user, only_visible=False):
    qs = Badge.objects.filter(user=user)
    if only_visible:
        qs = qs.filter(visible=True)
    return [b for b in qs if b.key in BADGES]


def badge_effects(user):
    """Every effect the member's badges add up to.

    Multipliers multiply, bonuses add, flags OR together. Computed rather than
    stored so revoking a badge takes its effect with it — a stored copy is how
    an effect outlives the thing that justified it.
    """
    out = {}
    for b in badges_for(user):
        for k, v in BADGES[b.key].get("effects", {}).items():
            if isinstance(v, bool):
                out[k] = out.get(k, False) or v
            elif k.endswith("_multiplier"):
                # Multiplied at full precision and rounded once at the end —
                # rounding at each step compounds the error as badges stack.
                out[k] = out.get(k, 1.0) * float(v)
            elif isinstance(v, (int, float)):
                out[k] = out.get(k, 0) + v
            else:
                out[k] = v
    return {k: (min(round(v, 4), MAX_ENERGY_MULTIPLIER) if k == "energy_multiplier"
                else round(v, 4) if k.endswith("_multiplier") else v)
            for k, v in out.items()}


def grant_badge(user, key, by=None):
    """Give a badge. Returns (badge, created)."""
    badge, created = Badge.objects.get_or_create(
        user=user, key=key, defaults={"awarded_by": by})
    if created:
        spec = BADGES.get(key, {})
        # A badge granting a tier applies it immediately — a tier that only
        # takes effect on the next unrelated save is a promise with a delay
        # nobody explained.
        tier = spec.get("effects", {}).get("tier")
        if tier:
            m = membership_for(user)
            if m.tier != tier:
                m.tier = tier
                m.save(update_fields=["tier", "updated_at"])
        notify(user, "badge",
               f"{spec.get('emoji', '🏅')} You earned {spec.get('name', key)} — "
               f"{spec.get('effect_note', '')}".strip(), actor=by)
    return badge, created


def revoke_badge(user, key):
    """Take a temporary badge back, and say so.

    Losing a badge in silence is worse than never holding one: the member's
    Energy rate changes and nothing explains why. So the notification is part
    of the revocation, not an afterthought.
    """
    n, _ = Badge.objects.filter(user=user, key=key).delete()
    if not n:
        return False
    spec = BADGES.get(key, {})
    # The title goes with it — wearing a title for a badge you no longer hold
    # would be the badge outliving its own condition.
    p = getattr(user, "mcz_profile", None) or profile_for(user)
    if p.badge_title and p.badge_title == spec.get("title"):
        p.badge_title = ""
        p.save(update_fields=["badge_title", "updated_at"])
    notify(user, "badge",
           f"{spec.get('emoji', '🏅')} {spec.get('name', key)} has lapsed — "
           f"{spec.get('how', '')} Earn it back and it returns by itself.".strip())
    return True


def recheck_badges(user):
    """Grant what's now earned, take back what's no longer true.

    TEMPORARY badges track a live median (Gifted on work ratings, Sexy on
    attractiveness) rather than marking a milestone. A median can fall, so the
    badge has to be able to fall with it — otherwise the first member to touch
    8 keeps the effect forever and the number stops meaning anything.

    Permanent badges are never revoked here. A shipped collab or a founding
    seat is a thing that HAPPENED; no later state undoes it.
    """
    have = {b.key for b in Badge.objects.filter(user=user)}
    won, lost = [], []
    for key, spec in BADGES.items():
        check = spec.get("check")
        if not check:
            continue
        try:
            passes = bool(check(user))
        except Exception:      # a broken check must never block a page load
            continue
        if passes and key not in have:
            grant_badge(user, key)
            won.append(key)
        elif not passes and key in have and spec.get("temporary"):
            if revoke_badge(user, key):
                lost.append(key)
    return won


class SocialReview(models.Model):
    """A social account the AI could not confirm belongs to this member.

    Corey's rule: match the name or the email and it's the same person; if it
    isn't, flag it for manual verification rather than refusing. A refusal
    strands anyone whose stage name differs from their legal name — which is
    most artists — while an auto-approve would let anyone paste a stranger's
    big account and mint Energy off their reach.

    So a `no`/`unsure` becomes a QUEUE, not a wall. The member is told it's
    being looked at and offered the code-in-bio route, which settles it in a
    minute without waiting for anyone.
    """
    STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED = "pending", "approved", "rejected"
    STATUS_CHOICES = [(STATUS_PENDING, "Pending"), (STATUS_APPROVED, "Approved"),
                      (STATUS_REJECTED, "Rejected")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="social_reviews")
    url = models.CharField(max_length=500)
    handle = models.CharField(max_length=120, blank=True, default="")
    claimed_followers = models.PositiveIntegerField(default=0)
    # What the model thought and WHY, kept so a human reviewing it is reading a
    # judgement with its reasoning rather than a verdict with none.
    ai_verdict = models.CharField(max_length=12, blank=True, default="")   # yes|no|unsure
    ai_reason = models.TextField(blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES,
                              default=STATUS_PENDING, db_index=True)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="social_reviews_done")
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        unique_together = ("user", "url")


class QuestClaim(models.Model):
    """One quest, claimed once, for one period.

    The unique constraint IS the reset: a daily quest's period key rolls over at
    midnight, so yesterday's claim can never block today's and nothing has to be
    cleared on a schedule. It is also the only thing standing between a member
    and claiming the same reward twice by pressing the button twice, so it is a
    database constraint rather than a check in a view.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="quest_claims")
    quest_id = models.CharField(max_length=40, db_index=True)
    # "2026-08-23", "2026-W34", or "once" — see questz.period_key.
    period = models.CharField(max_length=16)
    # What was actually paid, streak bonus included. Stored rather than
    # recomputed: the reward table can change, and a member's history should say
    # what they got, not what they would get today.
    energy = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "quest_id", "period")
        indexes = [models.Index(fields=["user", "created_at"])]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.quest_id}@{self.period} +{self.energy} <{self.user}>"


class PostContributor(models.Model):
    """A real row per person on a collab post.

    `Post.contributors` is the JSON the client renders; this is the same fact
    as an indexed foreign key so it can be QUERIED. The feed has to find the
    private posts a member is credited on, and doing that by scanning the deal
    table cost two extra queries per page load — a regression the feed's own
    query-count test caught. JSON for display, a table for lookups.
    """
    post = models.ForeignKey("Post", on_delete=models.CASCADE, related_name="contributor_rows")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="post_contributions")
    slot = models.CharField(max_length=16, blank=True, default="")

    class Meta:
        unique_together = ("post", "user")
        indexes = [models.Index(fields=["user"])]


class SkillRating(models.Model):
    """A post rating, landed on the skills that made the post.

    Corey's rule: every rating affects the skill used AND the post's overall
    rating. Before this a rating went to the post and stopped there, so a mix
    engineer with forty well-rated posts had no rated skill to show for it, and
    the skill price they charge was backed by nothing.

    Nothing is rated directly here — a row exists only because somebody rated a
    piece of work that used the skill. That is what stops a skill rating from
    being an opinion about a person: it is the median of what their work scored.

    On a collab post each contributor is credited for the skill their SLOT
    implies (cover art → Designer, video → Videographer), so a rating of the
    whole work does not credit the designer for the mixing.
    """
    rater = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="skill_ratings_given")
    subject = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="skill_ratings_received")
    skill = models.CharField(max_length=60)
    # Where it came from, so a skill rating can always be traced to the work
    # that earned it and recomputed if that work is edited or removed.
    item_id = models.CharField(max_length=160, db_index=True)
    score = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("rater", "subject", "skill", "item_id")
        indexes = [models.Index(fields=["subject", "skill"])]


def skill_rating_median(user, skill):
    """What this member's work scored when they used this skill."""
    scores = list(SkillRating.objects.filter(subject=user, skill=skill)
                  .values_list("score", flat=True))
    if not scores:
        return None
    scores.sort()
    n = len(scores)
    return scores[n // 2] if n % 2 else round((scores[n // 2 - 1] + scores[n // 2]) / 2, 1)


def skills_for_post(post):
    """[(user, skill)] — who gets rated for what when this post is rated.

    A solo post credits its author with every skill it declares. A collab post
    credits each contributor with the skill their slot implies, because rating
    the whole work is not a rating of everyone for everything.
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    pairs = []
    contributors = post.contributors or []
    if contributors:
        slot_skill = {"audio": "Independent Artist", "image": "Designer",
                      "video": "Videographer", "text": "Ghost Writer"}
        for c in contributors:
            u = User.objects.filter(username=c.get("username")).first()
            skill = slot_skill.get(c.get("slot") or "")
            if u and skill:
                pairs.append((u, skill))
        return pairs
    for skill in (post.skills_used or [])[:40]:
        if isinstance(skill, str) and skill.strip():
            pairs.append((post.author, skill.strip()[:60]))
    return pairs


def apply_post_rating(rater, post, score):
    """Land a post rating on every skill that earned it. Returns what was set.

    Self-rating is excluded: a skill rating you gave yourself would make the
    number meaningless, and the post rating already refuses it elsewhere.
    """
    out = []
    for user, skill in skills_for_post(post):
        if user.id == rater.id:
            continue
        SkillRating.objects.update_or_create(
            rater=rater, subject=user, skill=skill, item_id=f"post:{post.id}",
            defaults={"score": score},
        )
        out.append({"username": user.username, "skill": skill,
                    "rating": skill_rating_median(user, skill)})
    return out


class CollabFile(models.Model):
    """A version of the work passing between the people on a deal.

    A collab is a file going back and forth. The starter puts up v1; the
    collaborator downloads it, does their part, and puts up v2. Before this,
    a deal carried exactly one `media_url` and no way to hand anything back —
    so the actual work happened in DMs and the deal only held the money.

    Versions are never overwritten. The whole point of an escrowed collab is
    being able to show what was delivered and when, and a v2 that replaced v1
    in place would destroy the only record of that.
    """
    deal = models.ForeignKey("CollabDeal", on_delete=models.CASCADE, related_name="files")
    uploader = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name="collab_files")
    version = models.PositiveIntegerField(default=1)
    url = models.CharField(max_length=500)
    name = models.CharField(max_length=255, blank=True, default="")
    media_type = models.CharField(max_length=24, blank=True, default="")
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("version", "id")
        unique_together = ("deal", "version")


class Release(models.Model):
    """A post, ready to distribute.

    The four things a post carries — the song, the music video, the cover art
    and the lyrics — are exactly the four assets a distributor asks for. So a
    release is not a form to retype: it is populated FROM the post, and the only
    fields left are the ones a post genuinely doesn't know (the release date,
    the ISRC, whether it's explicit).

    `missing()` is the honest half. A release says what it still needs BEFORE
    anyone tries to send it, rather than being refused at the far end by a
    distributor's validator with a message nobody here wrote.
    """
    STATUS_DRAFT, STATUS_READY, STATUS_SUBMITTED = "draft", "ready", "submitted"
    STATUS_CHOICES = [(STATUS_DRAFT, "Draft"), (STATUS_READY, "Ready"),
                      (STATUS_SUBMITTED, "Submitted")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="releases")
    # One release per post. Pressing Distribute twice returns the release you
    # already started rather than quietly making a second one.
    source_post = models.OneToOneField("Post", on_delete=models.SET_NULL, null=True,
                                       blank=True, related_name="release")
    # A collab is the other thing that becomes a release — more often, in fact,
    # since a deal is where the finished master usually lands.
    source_deal = models.OneToOneField("CollabDeal", on_delete=models.SET_NULL, null=True,
                                       blank=True, related_name="release")

    title = models.CharField(max_length=160, blank=True, default="")
    artist_name = models.CharField(max_length=120, blank=True, default="")
    genre = models.CharField(max_length=40, blank=True, default="")

    # The four assets, in the post's own slot names so the copy is a copy.
    audio_url = models.CharField(max_length=500, blank=True, default="")     # the song
    video_url = models.CharField(max_length=500, blank=True, default="")     # music video
    artwork_url = models.CharField(max_length=500, blank=True, default="")   # cover image
    lyrics = models.TextField(blank=True, default="")                        # txt lyrics

    # What a post can't know.
    release_date = models.DateField(null=True, blank=True)
    isrc = models.CharField(max_length=15, blank=True, default="")
    explicit = models.BooleanField(default=False)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    # What a distributor will not take a release without. Artwork is on this
    # list because every store rejects a release that has none, and finding
    # that out after submitting is the worst place to learn it.
    REQUIRED = (("title", "a title"), ("artist_name", "an artist name"),
                ("audio_url", "the song itself"), ("artwork_url", "cover art"))

    # Editable after it has gone out — which is most of it. Stores take an
    # updated cover, a new video, corrected lyrics and a fixed explicit flag
    # long after release, so refusing every edit would be stricter than the
    # shops we're sending to.
    #
    # The two that are NOT here identify the recording itself: swapping the
    # master or the ISRC under a live release makes it a different record
    # wearing the same name. Those need a new release, and the refusal says so.
    LOCKED_ONCE_SUBMITTED = {"audio_url": "the master audio", "isrc": "the ISRC"}

    def missing(self):
        return [label for field, label in self.REQUIRED if not getattr(self, field)]

    def refresh_status(self):
        """Draft until it's complete, ready once it is. Never downgrades a
        release that has already gone out."""
        if self.status == self.STATUS_SUBMITTED:
            return self.status
        self.status = self.STATUS_DRAFT if self.missing() else self.STATUS_READY
        return self.status


class OccOutput(models.Model):
    """A piece of work OCC took in and handed back — in the PostZ format.

    Two halves, deliberately kept apart:

    * **What went in** — `input_text` and `input_items`, the prompt and the
      attachments the member gave OCC. Kept because "what did I ask for" is the
      first question anyone has when they look at an output a week later.
    * **What came out** — the PostZ field names exactly: title, description,
      media_type/media_url, image_url, lyrics, items. Same names as `Post` and
      `CollabDeal` so a share is a copy, not a translation. Three composers
      accepting three shapes is how they drift.

    An output is the member's private working material until they share it.
    Sharing creates a real `Post`, and from then on the output's `item_key` IS
    that post's key — ratings, likes and comments land on the one surface other
    members can actually see. A second rateable item space that nothing renders
    would be exactly the kind of number-with-no-data-behind-it this app keeps
    having to fix.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="occ_outputs")
    # Which task produced it, when one did. SET_NULL because deleting the task
    # log shouldn't take the work with it.
    task = models.ForeignKey("OccTask", on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="outputs")
    tab = models.CharField(max_length=32, blank=True, default="")   # the OCC tab it came from

    # ---- what went in
    input_text = models.TextField(blank=True, default="")
    input_items = models.JSONField(default=list, blank=True)   # [{url, type, title, lyrics}]

    # ---- what came out, in the PostZ format
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    media_type = models.CharField(max_length=24, blank=True, default="")
    media_url = models.CharField(max_length=500, blank=True, default="")
    image_url = models.CharField(max_length=500, blank=True, default="")
    lyrics = models.TextField(blank=True, default="")
    items = models.JSONField(default=list, blank=True)
    genre = models.CharField(max_length=40, blank=True, default="")
    skills_used = models.JSONField(default=list, blank=True)
    # Posting charges energy equal to the combined skill price, so the output
    # carries it and the share button can state the cost BEFORE it's pressed.
    skill_cost_cents = models.PositiveIntegerField(default=0)

    shared_post = models.ForeignKey("Post", on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="occ_outputs")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    @property
    def item_key(self):
        """Where this work is rated, liked and commented — or None.

        Not `occ:<id>`: until it's shared there is no screen another member
        could open, and an item key nobody can reach collects nothing.
        """
        return f"post:{self.shared_post_id}" if self.shared_post_id else None


# ---------------------------------------------------------------------------
# FileZ — the filesystem OCC can hold between turns
# ---------------------------------------------------------------------------

def normalize_occ_path(raw):
    """A member- or model-supplied path, reduced to a safe relative one — or None.

    This is the single gate every file operation goes through, and it returns
    None rather than raising so a bad path from the MODEL is an error the model
    reads and retries, not a 500 the member sees.

    What it refuses, and why each one is here rather than assumed:

    * ``..`` anywhere — the whole point. These paths become real files inside a
      sandbox in Phase 1, so a stored ``../../etc/passwd`` is a traversal that
      was written to the database weeks earlier and fired later.
    * Absolute paths and Windows drive letters — they escape the project root
      the moment they are joined to it.
    * Backslashes — normalised to ``/`` rather than rejected, because a member
      pasting a Windows path means the same file, but a separator we don't
      understand is a segment check we didn't really do.
    * NUL bytes — they truncate paths in C-level filesystem calls, so a name
      that looks safe in Python can be a different name on disk.
    * ``.`` and empty segments — harmless individually, but they mean two rows
      can name one file, and a uniqueness constraint that can be sidestepped by
      writing ``src//main.py`` is not a constraint.
    """
    from .catalog import OCC_MAX_PATH_CHARS

    text = str(raw or "").strip().replace("\\", "/")
    if not text or "\x00" in text:
        return None
    # Drive letters escape before any segment logic gets a chance.
    if len(text) > 1 and text[1] == ":":
        return None
    segments = []
    for segment in text.split("/"):
        if segment in ("", "."):
            continue            # collapse, don't reject — "src//main.py" is one file
        if segment == "..":
            return None         # never resolvable to something inside the root
        segments.append(segment)
    if not segments:
        return None
    path = "/".join(segments)
    return path if len(path) <= OCC_MAX_PATH_CHARS else None


class OccFile(models.Model):
    """One file in one of a member's OCC projects.

    Rows rather than real files on purpose. The sandbox is created and destroyed
    per session, Render's disk is ephemeral, and the frontend deploys itself —
    so the only place a project can actually live between turns is the database
    the rest of the app already trusts.

    `path` is always relative and always normalised (see `normalize_occ_path`);
    it is the join key the sandbox materialises from, so an unchecked one here
    is a traversal there.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="occ_files")
    # A plain name, not a foreign key. A project is a namespace, not a thing
    # with its own settings — and a table whose only column is a name is a table
    # that has to be kept in step with this one for no gain.
    project = models.CharField(max_length=80, default="main")
    path = models.CharField(max_length=200)
    content = models.TextField(blank=True, default="")
    # Which task last wrote it, when one did. SET_NULL so pruning the task log
    # never deletes a member's source.
    task = models.ForeignKey("OccTask", on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="files")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("project", "path")
        constraints = [
            # One row per file. Without this, two writes racing on the same path
            # leave two rows and `read` returns whichever the ordering happens
            # to pick — a file that changes when nobody wrote to it.
            models.UniqueConstraint(fields=["user", "project", "path"],
                                    name="occ_file_unique_path"),
        ]
        indexes = [models.Index(fields=["user", "project"])]

    def __str__(self):
        return f"{self.project}/{self.path}"


# ---------------------------------------------------------------------------
# GameZ — games built here, playable here
# ---------------------------------------------------------------------------

def game_bundle_path(instance, filename):
    """Built games are namespaced per member, like every other upload."""
    return f"games/{instance.user_id}/{instance.id or 'new'}/{filename}"


class Game(models.Model):
    """A game a member built in OCC, and the bundle you can actually play.

    GameZ has been a tab in `occ_spec.py` and a routing-table entry
    (`EXPORT_ROUTES["game"] -> gamez:mine`) with nothing behind either of them.
    This is the thing they were pointing at.

    Web games, deliberately — the code lives in an `OccFile` project, the build
    runs in the sandbox, and the output is static files served in a sandboxed
    frame. Unity and Unreal need licence seats and toolchains measured in tens of
    gigabytes, which is a different product; a game nobody can play without
    leaving the app is the dead end this codebase keeps closing.

    Assets are `Upload` rows via `GameAsset` rather than a second file system,
    so a member's sprites and audio count against the storage quota they already
    have and `storage_used_bytes` keeps telling the truth.
    """
    STATUS_DRAFT = "draft"          # code exists, never built
    STATUS_BUILDING = "building"
    STATUS_PLAYABLE = "playable"    # a bundle exists and can be served
    STATUS_FAILED = "failed"        # the build ran and didn't produce one
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"), (STATUS_BUILDING, "Building"),
        (STATUS_PLAYABLE, "Playable"), (STATUS_FAILED, "Failed"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="games")
    title = models.CharField(max_length=160)
    # Validated against occ_spec.GAME_GENRES rather than a choices= list, so the
    # taxonomy stays in the one file that already defines it. A second copy here
    # is how 17 advertised languages ended up with 12 runners.
    genre = models.CharField(max_length=40, blank=True, default="")
    subgenre = models.CharField(max_length=80, blank=True, default="")
    description = models.TextField(blank=True, default="")

    # Which OCC project holds the source. A name, matching OccFile.project —
    # the code is those rows, and the game is what a build turns them into.
    project = models.CharField(max_length=80, default="main")

    # Blank means "there is nothing to build" — the project's files ARE the
    # game, which is true of most small web games (an index.html, a main.js and
    # some sprites). That case is zipped directly and costs nothing. A command
    # here means a real build, which needs the sandbox and is charged for it.
    build_command = models.CharField(max_length=200, blank=True, default="")

    status = models.CharField(max_length=10, choices=STATUS_CHOICES,
                              default=STATUS_DRAFT)
    # The built bundle: a zip of static files. Stored rather than rebuilt on
    # demand because a build costs sandbox seconds and a play should not.
    bundle = models.FileField(upload_to=game_bundle_path, blank=True, null=True)
    bundle_bytes = models.PositiveBigIntegerField(default=0)
    entry = models.CharField(max_length=200, default="index.html")
    build_detail = models.TextField(blank=True, default="")
    built_at = models.DateTimeField(null=True, blank=True)

    plays = models.PositiveIntegerField(default=0)
    # Private until the member says otherwise — the same rule OccOutput follows.
    shared_post = models.ForeignKey("Post", on_delete=models.SET_NULL, null=True,
                                    blank=True, related_name="games")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = [models.Index(fields=["user", "status"])]

    def __str__(self):
        return f"{self.title} <{self.user}>"

    @property
    def playable(self):
        """Whether there is actually something to play.

        Computed from the bundle, never from `status` alone — a status that says
        playable with no file behind it is a Play button that lies, which is the
        failure this whole tab is being built to stop repeating.
        """
        return bool(self.status == self.STATUS_PLAYABLE and self.bundle)

    @property
    def item_key(self):
        """Where the game is rated and commented — or None until it's shared."""
        return f"post:{self.shared_post_id}" if self.shared_post_id else None


class GameAsset(models.Model):
    """One binary asset belonging to a game — a sprite, a sound, a font.

    A join rather than a second file model. `Upload` already has the FileField,
    the size accounting and the per-member namespacing, and `storage_used_bytes`
    already sums it; a parallel table would mean a member's game assets did not
    count against the quota their tier actually sells them.
    """
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="assets")
    upload = models.ForeignKey(Upload, on_delete=models.CASCADE,
                               related_name="game_assets")
    # Where it lands in the built game, relative to the bundle root. Normalised
    # through the same gate as OccFile — this becomes a real path at build time.
    path = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("path",)
        constraints = [
            models.UniqueConstraint(fields=["game", "path"],
                                    name="game_asset_unique_path"),
        ]

    def __str__(self):
        return f"{self.game_id}:{self.path}"
