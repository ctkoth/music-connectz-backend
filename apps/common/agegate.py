"""Age-tier gating for Music ConnectZ.

The youth market is real, but it can only touch *youth-safe* surfaces. Adult-only
surfaces (real-money gambling, dating/romance, paid stranger calls, cash payouts,
KYC) are NEVER opened to minors — parental consent does not waive those, so the
gate fails CLOSED: anything not proven to be a verified adult is treated as not
allowed for adult-only features.

Wire-up: add an `age_status` field to your user (or profile) model with values
"unknown" | "youth" | "adult". Set it during onboarding/age-verification:
    age_status = models.CharField(max_length=8, default="unknown")
"""
from rest_framework.permissions import BasePermission

AGE_UNKNOWN = "unknown"
AGE_YOUTH = "youth"      # under 18, with verified parental consent
AGE_ADULT = "adult"      # 18+, age-verified

AGE_CHOICES = [
    (AGE_UNKNOWN, "Unknown / unverified"),
    (AGE_YOUTH, "Youth (under 18, parental consent)"),
    (AGE_ADULT, "Adult (18+, verified)"),
]

# Surfaces that are NEVER available to minors, under any consent. Used for docs
# and for any view that wants to assert adult-only access.
ADULT_ONLY_FEATURES = {
    "battle_money_stakes",   # real-money BattleZ wagers
    "social_dating",         # Social ConnectZ romance/matching
    "paid_user_calls",       # CallZ to other users (paid)
    "cash_payout",           # Stripe Connect payouts / cash out
    "distribution_licensing",
    "kyc",
}

# Creator/creative apps that ARE safe for youth accounts.
YOUTH_SAFE_APPS = {
    "designz", "shotz", "writez", "producez", "mixez", "developz",
    "toolz", "filez", "ratez", "profile", "settingz",
    # NOTE: managez is adult-leaning (contracts/payouts) — leave it gated.
}


def age_status(user):
    """Read the account's age tier, defaulting to 'unknown' (fail closed)."""
    if not user or not getattr(user, "is_authenticated", False):
        return AGE_UNKNOWN
    val = getattr(user, "age_status", None)
    if val:
        return val
    profile = getattr(user, "profile", None)
    if profile is not None:
        val = getattr(profile, "age_status", None)
        if val:
            return val
    # Our own non-invasive store (apps.common.UserFlags), set at verified onboarding.
    try:
        from .models import UserFlags
        flags = UserFlags.objects.filter(user=user).only("age_status").first()
        if flags and flags.age_status:
            return flags.age_status
    except Exception:
        pass
    return AGE_UNKNOWN


def is_adult(user):
    return age_status(user) == AGE_ADULT


class AdultOnly(BasePermission):
    """Require a verified adult. Fails closed for unknown/youth."""

    message = "This feature is restricted to age-verified adults (18+)."

    def has_permission(self, request, view):
        return is_adult(request.user)


class YouthSafe(BasePermission):
    """Any authenticated account, regardless of tier. For creative/safe tools."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)
