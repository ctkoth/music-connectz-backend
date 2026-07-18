"""Cross-user VenueZ (host/join events) and RateZ attractiveness.

Money moves between real users' wallets with the developer tax enforced
server-side (via pay_between). Attractiveness is a community-aggregated median
that gates venues, mirroring the collab/battle filter.
"""
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    AttractivenessRating,
    Venue,
    VenueAttendance,
    attractiveness_median,
    membership_for,
    pay_between,
    wallet_for,
)
from .serializers import WalletSerializer

User = get_user_model()
VALID_TYPES = {"party", "openmic", "theater", "show", "custom"}


def _venue_dict(v, request):
    return {
        "id": v.id,
        "title": v.title,
        "mode": v.mode,
        "vtype": v.vtype,
        "custom_name": v.custom_name,
        "host": v.host.username,
        "mine": v.host_id == request.user.id,
        "host_price_cents": v.host_price_cents,
        "visitor_pay_cents": v.visitor_pay_cents,
        "min_attract": v.min_attract,
        "attending": v.attendances.filter(visitor=request.user).exists(),
        "created_at": v.created_at,
    }


class VenuesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        venues = Venue.objects.select_related("host").all()[:200]
        return Response({"venues": [_venue_dict(v, request) for v in venues]})

    def post(self, request):
        d = request.data
        title = str(d.get("title", "")).strip()
        if not title:
            return Response({"detail": "title required"}, status=status.HTTP_400_BAD_REQUEST)
        mode = d.get("mode") if d.get("mode") in (Venue.MODE_COLLAB, Venue.MODE_PERF) else Venue.MODE_COLLAB
        vtype = d.get("vtype") if d.get("vtype") in VALID_TYPES else "party"

        def cents(key):
            try:
                return max(0, int(d.get(key) or 0))
            except (TypeError, ValueError):
                return 0

        v = Venue.objects.create(
            host=request.user, title=title[:120], mode=mode, vtype=vtype,
            custom_name=str(d.get("custom_name", ""))[:60],
            host_price_cents=cents("host_price_cents"),
            visitor_pay_cents=cents("visitor_pay_cents") if mode == Venue.MODE_COLLAB else 0,
            min_attract=min(10, max(0, cents("min_attract"))),
        )
        return Response({"venue": _venue_dict(v, request)}, status=status.HTTP_201_CREATED)


class VenueJoinView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        venue = Venue.objects.select_related("host").filter(pk=pk).first()
        if not venue:
            return Response({"detail": "venue not found"}, status=status.HTTP_404_NOT_FOUND)
        if venue.host_id == request.user.id:
            return Response({"detail": "you can't attend your own venue"}, status=status.HTTP_400_BAD_REQUEST)

        # Scalable attractiveness gate — rated visitors below the bar are blocked.
        if venue.min_attract > 0:
            med = attractiveness_median(request.user)
            if med is not None and med < venue.min_attract:
                return Response(
                    {"detail": f"needs attractiveness {venue.min_attract}+, yours is {med}"},
                    status=status.HTTP_403_FORBIDDEN,
                )

        vw = wallet_for(request.user)
        if vw.money_cents < venue.host_price_cents:
            return Response({"detail": "insufficient balance to attend"}, status=status.HTTP_402_PAYMENT_REQUIRED)

        with transaction.atomic():
            # Visitor pays the host (developer tax enforced).
            pay_between(request.user, venue.host, venue.host_price_cents, note=f"VenueZ: {venue.title} (attend)")
            earned_net = 0
            # Collaborative: host also pays the visitor their skill price, if the host can cover it.
            if venue.mode == Venue.MODE_COLLAB and venue.visitor_pay_cents > 0:
                hw = wallet_for(venue.host)
                if hw.money_cents >= venue.visitor_pay_cents:
                    _dev, earned_net = pay_between(venue.host, request.user, venue.visitor_pay_cents, note=f"VenueZ: {venue.title} (skill payout)")
            VenueAttendance.objects.update_or_create(
                venue=venue, visitor=request.user,
                defaults={"paid_cents": venue.host_price_cents, "earned_cents": earned_net},
            )

        return Response({
            "wallet": WalletSerializer(wallet_for(request.user)).data,
            "paid_cents": venue.host_price_cents,
            "earned_cents": earned_net,
        })


class AttractivenessView(APIView):
    """GET my attractiveness median + opt-in; POST toggles the opt-in."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        m = membership_for(request.user)
        return Response({
            "median": attractiveness_median(request.user),
            "count": AttractivenessRating.objects.filter(target=request.user).count(),
            "public": m.attractiveness_public,
        })

    def post(self, request):
        m = membership_for(request.user)
        m.attractiveness_public = bool(request.data.get("public", True))
        m.save(update_fields=["attractiveness_public", "updated_at"])
        return Response({"public": m.attractiveness_public})


class AttractivenessRateView(APIView):
    """Rate another user's attractiveness (1-10). Upserts one rating per rater."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        username = str(request.data.get("target_username", "")).strip()
        try:
            score = int(request.data.get("score"))
        except (TypeError, ValueError):
            return Response({"detail": "score (1-10) required"}, status=status.HTTP_400_BAD_REQUEST)
        if not (1 <= score <= 10):
            return Response({"detail": "score must be 1-10"}, status=status.HTTP_400_BAD_REQUEST)
        target = User.objects.filter(username=username).first()
        if not target:
            return Response({"detail": "unknown user"}, status=status.HTTP_404_NOT_FOUND)
        if target.id == request.user.id:
            return Response({"detail": "can't rate yourself"}, status=status.HTTP_400_BAD_REQUEST)

        AttractivenessRating.objects.update_or_create(
            rater=request.user, target=target, defaults={"score": score}
        )
        m = membership_for(target)
        return Response({
            "target": target.username,
            "median": attractiveness_median(target) if m.attractiveness_public else None,
            "public": m.attractiveness_public,
        })
