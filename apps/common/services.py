"""Server-side age-status setters. The ONLY sanctioned way to mark a user 'adult'.

Call these from your verified flows — never trust a client to declare adulthood.
"""
from .agegate import AGE_ADULT, AGE_YOUTH, AGE_UNKNOWN
from .models import UserFlags


def _set(user, status):
    flags, _ = UserFlags.objects.update_or_create(user=user, defaults={"age_status": status})
    return flags


def mark_adult_verified(user):
    """Call AFTER a real age/ID check passes (KYC, Stripe Identity, Yoti, etc.)."""
    return _set(user, AGE_ADULT)


def mark_youth_with_consent(user):
    """Call AFTER verified parental/guardian consent for an under-18 account."""
    return _set(user, AGE_YOUTH)


def reset_age_status(user):
    return _set(user, AGE_UNKNOWN)
