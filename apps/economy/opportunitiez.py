"""OpportunitieZ — feed of what musicians are seeking, for collaborators to find."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Profile

MAX_LIMIT = 100


def seeking_profiles():
    """Profiles with an ACTIVE seeking note that says what they need, newest first.

    One queryset for the page and the total. The page used to slice every profile with
    any `seeking` value and filter in Python afterwards, so a page of 50 could show 3 —
    or none while active entries sat further down — and the total counted a set the
    page never drew from.
    """
    return (Profile.objects
            .filter(seeking__active=True, seeking__help_needed__isnull=False)
            .exclude(seeking__help_needed="")
            .select_related("user__membership")
            .order_by("-updated_at", "-pk"))


def _int(v, default, lo, hi):
    """A query number, clamped. Junk is the default, never a 500."""
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


class OpportunitieZView(APIView):
    """GET /api/economy/opportunitiez/ — members seeking collaboration."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        limit = _int(request.GET.get("limit"), 50, 1, MAX_LIMIT)
        offset = _int(request.GET.get("offset"), 0, 0, 10 ** 6)
        qs = seeking_profiles()
        opportunities = []
        for p in qs[offset:offset + limit]:
            seeking = p.seeking or {}
            # A member whose membership row was never made is a Free member, not a
            # missing one — the old inner join on tier hid them from the board.
            membership = getattr(p.user, "membership", None)
            opportunities.append({
                "id": p.user_id,
                "username": p.user.username,
                "avatar": p.avatar.url if p.avatar else None,
                "help_needed": seeking.get("help_needed", ""),
                "status": seeking.get("status", ""),
                "current_reach": seeking.get("current_reach", ""),
                "rate": seeking.get("rate", ""),
                "tier": membership.tier if membership else "free",
                "updated_at": p.updated_at.isoformat(),
            })
        return Response({"results": opportunities, "total": qs.count()})
