"""Membership-tier gating for Music ConnectZ.

Tiers: free < premium < statz.
  - Suggestions  : Premium+ (run them MANUALLY). StatZ can run them on AUTO.
  - Automations  : StatZ only.
Applies everywhere, including OCC (the in-app code tool).

Reads the tier from the user's membership/profile. Honors explicit limit flags
(`can_use_suggestions`, `can_use_automations`) if your membership exposes them,
otherwise falls back to tier rank. Fails closed (defaults to 'free').
"""
from rest_framework.permissions import BasePermission

TIER_FREE, TIER_PREMIUM, TIER_STATZ = "free", "premium", "statz"
TIER_RANK = {TIER_FREE: 0, TIER_PREMIUM: 1, TIER_STATZ: 2}


def _membership(user):
    """Find the user's membership object across common relation names."""
    prof = getattr(user, "profile", None)
    for src in (user, prof):
        if src is None:
            continue
        for attr in ("membership", "memberships", "membership_set"):
            m = getattr(src, attr, None)
            if m is None:
                continue
            # reverse manager -> take the latest row
            if hasattr(m, "all") and not hasattr(m, "tier"):
                m = m.all().order_by("-id").first() if hasattr(m, "all") else None
            if m is not None and hasattr(m, "tier"):
                return m
    return None


def tier_of(user):
    if not user or not getattr(user, "is_authenticated", False):
        return TIER_FREE
    # Platform owner (staff/superuser) gets the top tier.
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return TIER_STATZ
    m = _membership(user)
    return getattr(m, "tier", None) or TIER_FREE


def _limit(user, name):
    m = _membership(user)
    limits = getattr(m, "limits", None) if m else None
    if isinstance(limits, dict):
        return limits.get(name)
    return getattr(limits, name, None) if limits is not None else None


def at_least(user, tier):
    return TIER_RANK.get(tier_of(user), 0) >= TIER_RANK.get(tier, 99)


def can_suggest(user):
    flag = _limit(user, "can_use_suggestions")
    return bool(flag) if flag is not None else at_least(user, TIER_PREMIUM)


def can_automate(user):
    flag = _limit(user, "can_use_automations")
    return bool(flag) if flag is not None else at_least(user, TIER_STATZ)


def can_auto_suggest(user):
    # Auto-running of suggestions is a StatZ automation.
    return can_automate(user)


class PremiumOnly(BasePermission):
    message = "This feature requires Premium or StatZ."
    def has_permission(self, request, view):
        return at_least(request.user, TIER_PREMIUM)


class StatzOnly(BasePermission):
    message = "This feature requires StatZ."
    def has_permission(self, request, view):
        return at_least(request.user, TIER_STATZ)


class SuggestionsPermission(BasePermission):
    """Allow suggestions for Premium+. If the request asks for mode=auto,
    require StatZ (auto-run is an automation)."""
    message = "Suggestions require Premium (manual) or StatZ (auto)."
    def has_permission(self, request, view):
        if not can_suggest(request.user):
            return False
        mode = (request.data.get("mode") if hasattr(request, "data") else None) or request.query_params.get("mode", "manual")
        if mode == "auto":
            return can_auto_suggest(request.user)
        return True
