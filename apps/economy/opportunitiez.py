"""OpportunitieZ — feed of what musicians are seeking, for collaborators to find."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q
from .models import Profile, Membership

class OpportunitieZView(APIView):
    """GET /api/economy/opportunitiez/ — members seeking collaboration."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        limit = int(request.GET.get("limit", 50))
        offset = int(request.GET.get("offset", 0))

        # Active seeking profiles with at least help_needed filled
        profiles = Profile.objects.filter(
            seeking__isnull=False,
            user__membership__tier__in=["free", "premium", "statz", "debug"]
        ).select_related("user__membership").order_by("-updated_at")

        # Filter to only those with active seeking
        opportunities = []
        for p in profiles[offset:offset+limit]:
            seeking = p.seeking or {}
            if seeking.get("active") and seeking.get("help_needed"):
                opportunities.append({
                    "id": p.user_id,
                    "username": p.user.username,
                    "avatar": p.avatar.url if p.avatar else None,
                    "help_needed": seeking.get("help_needed", ""),
                    "status": seeking.get("status", ""),
                    "current_reach": seeking.get("current_reach", ""),
                    "rate": seeking.get("rate", ""),
                    "tier": p.user.membership.tier,
                    "updated_at": p.updated_at.isoformat(),
                })

        return Response({
            "results": opportunities,
            "total": Profile.objects.filter(
                seeking__active=True,
                seeking__help_needed__isnull=False
            ).exclude(seeking__help_needed="").count(),
        })
