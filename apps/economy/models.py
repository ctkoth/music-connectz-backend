"""
Economy layer: membership tier, wallet (money/energy/spinaz), and a
transaction ledger. The developer tax (platform's cut on every money
transaction) is enforced here, server-side, so the client can't bypass it.

Rates match the frontend: Free 5% · Premium 3% · StatZ 2%.
"""
from django.conf import settings
from django.db import models

TIER_FREE = "free"
TIER_PREMIUM = "premium"
TIER_STATZ = "statz"
TIER_CHOICES = [(TIER_FREE, "Free"), (TIER_PREMIUM, "Premium"), (TIER_STATZ, "StatZ")]

# Developer tax (platform cut) per tier, as a fraction of the transaction.
DEV_TAX = {TIER_FREE: 0.05, TIER_PREMIUM: 0.03, TIER_STATZ: 0.02}


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
    since = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
    return Membership.objects.get_or_create(user=user)[0]


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
