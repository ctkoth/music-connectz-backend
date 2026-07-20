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
    KIND_CHOICES = [
        (KIND_ADD, "Add funds"),
        (KIND_PURCHASE, "Purchase"),
        (KIND_ROYALTY, "Royalty"),
        (KIND_REWARD, "Reward"),
        (KIND_SPEND, "Spend"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transactions"
    )
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
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


def charge_ai_usage(user, cost_cents, note="AI usage"):
    """Debit the wallet the *minimum* cost to cover an AI model run — pure
    pass-through, no developer tax (the platform isn't marking AI up, just
    covering the model). Returns the remaining money_cents, or None if the
    member can't afford it (caller returns 402)."""
    cost_cents = int(cost_cents or 0)
    w = wallet_for(user)
    if cost_cents <= 0:
        return w.money_cents
    if w.money_cents < cost_cents:
        return None
    w.money_cents -= cost_cents
    w.save(update_fields=["money_cents", "updated_at"])
    Transaction.objects.create(
        user=user, kind=Transaction.KIND_SPEND, amount_cents=-cost_cents,
        dev_tax_cents=0, note=note[:200],
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
    min_attract = models.PositiveSmallIntegerField(default=0)  # 0-10
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
    bio = models.CharField(max_length=500, blank=True, default="")
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
    # Optional scored-take payload (e.g. RapZ/SingZ lab result) for context on the post.
    score = models.JSONField(default=dict, blank=True)
    visibility = models.CharField(max_length=12, choices=VIS_CHOICES, default="public")
    skill_cost_cents = models.PositiveIntegerField(default=0)  # combined skill price of what's used
    created_at = models.DateTimeField(auto_now_add=True)

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
    """Credit SpinAZ to a user's wallet (best-effort, idempotent per caller)."""
    w = wallet_for(user)
    w.spinaz = (w.spinaz or 0) + int(amount)
    w.save(update_fields=["spinaz", "updated_at"])
    return w.spinaz


def can_view_post(post, user):
    if post.visibility == "public":
        return True
    if post.author_id == getattr(user, "id", None):
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
    return reach // divisor


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
    mood = models.CharField(max_length=32, blank=True, default="")
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    duration_sec = models.PositiveIntegerField(default=0)
    contributors = models.JSONField(default=list, blank=True)  # [{name, tier, skills:[{name, price}]}]
    ai_rating = models.FloatField(default=0)                    # 0-10 AI seed
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


def directz_ai_rating(work):
    """A deterministic AI craft estimate (0-10) from how complete & staffed the
    work is: contributor breadth, skills brought, description, and duration fit."""
    contribs = work.get("contributors") if isinstance(work, dict) else work.contributors
    desc = work.get("description") if isinstance(work, dict) else work.description
    dur = work.get("duration_sec") if isinstance(work, dict) else work.duration_sec
    fmt = work.get("fmt") if isinstance(work, dict) else work.fmt
    contribs = contribs or []
    n_people = len(contribs)
    n_skills = sum(len(c.get("skills") or []) for c in contribs)
    worth = sum((float(s.get("price") or 0) for c in contribs for s in (c.get("skills") or [])))
    # Duration-fit: does the length match the format band?
    bands = {"reelz": (30, 1800), "episodez": (1800, 3600), "moviez": (3600, 10800)}
    lo, hi = bands.get(fmt, (0, 10 ** 9))
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
    """Real-user median once >=3 rate; otherwise the AI seed. Returns
    {rating, source, ai_rating, user_median, count}."""
    scores = list(work.ratings.values_list("score", flat=True))
    user_median = _median(scores)
    if len(scores) >= DIRECTZ_MIN_RATERS:
        return {"rating": user_median, "source": "users", "ai_rating": round(work.ai_rating, 1), "user_median": user_median, "count": len(scores)}
    return {"rating": round(work.ai_rating, 1), "source": "ai", "ai_rating": round(work.ai_rating, 1), "user_median": user_median, "count": len(scores)}


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
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "item_id")


def item_rating_median(item_id):
    return _median(ItemRating.objects.filter(item_id=item_id).values_list("score", flat=True))


class SocialComment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_comments")
    item_id = models.CharField(max_length=160, db_index=True)
    body = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

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
