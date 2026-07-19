"""
Economy layer: membership tier, wallet (money/energy/spinaz), and a
transaction ledger. The developer tax (platform's cut on every money
transaction) is enforced here, server-side, so the client can't bypass it.

Rates match the frontend: Free 10% · Premium 5% · StatZ 2%.
"""
from django.conf import settings
from django.db import models

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


# ---- Social graph: follow / friends / fans ----
class Follow(models.Model):
    """follower → following. Mutual follows are friends; a one-way follower is
    a fan of the followed user."""
    follower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="following_set")
    following = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="follower_set")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("follower", "following")


def follow_counts(user):
    """followers / following / friends(mutual) / fans(one-way) for a user, plus
    any external-account followers they've declared on their profile."""
    following_ids = set(Follow.objects.filter(follower=user).values_list("following_id", flat=True))
    follower_ids = set(Follow.objects.filter(following=user).values_list("follower_id", flat=True))
    friends = following_ids & follower_ids           # mutual
    fans = follower_ids - following_ids              # follow you, you don't follow back
    p = getattr(user, "mcz_profile", None)
    external = int(getattr(p, "external_followers", 0) or 0) if p else 0
    return {
        "followers": len(follower_ids),
        "following": len(following_ids),
        "friends": len(friends),
        "fans": len(fans),
        "external_followers": external,
        "total_followers": len(follower_ids) + external,
    }


def energy_rate_per_hour(user):
    """Hourly passive energy by tier, from follower reach (MCZ + external):
    Free = reach/10, Premium = reach/5, StatZ = reach/1."""
    reach = follow_counts(user)["total_followers"]
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
