"""AdZ — Watch & Earn. The owner posts commercials with a per-view payout (the
cents a sponsor/network pays them); a member watches one and earns that many
SpinAZ. SpinAZ is pegged to cents, so the viewer's reward equals the owner's
per-view revenue. Real money to the owner comes from the sponsor/ad network
off-platform (or via a network's server-to-server callback later); SpinAZ is the
in-app reward minted here. Anti-fraud: genuine watch time, one reward per ad per
viewer per day (up to the ad's cap), and a per-viewer daily cap across all ads.
"""
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Commercial,
    AdView,
    AD_REWARD_DAILY_CAP_PER_USER,
    award_spinaz,
    wallet_for,
)
from .views import is_owner


def _client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _ad_dict(c, request):
    return {
        "id": c.id,
        "title": c.title,
        "sponsor": c.sponsor,
        "media_url": c.media_url,
        "media_type": c.media_type,
        "link_url": c.link_url,
        "payout_cents": c.payout_cents,
        "reward_spinaz": c.payout_cents,           # SpinAZ pegged to cents
        "min_watch_seconds": c.min_watch_seconds,
        "daily_cap_per_user": c.daily_cap_per_user,
        "active": c.active,
        "mine": c.owner_id == request.user.id,
    }


class AdzView(APIView):
    """GET active commercials to watch (+ owner earnings summary). POST creates a
    commercial (owner only)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        ads = [_ad_dict(c, request) for c in Commercial.objects.filter(active=True).select_related("owner")[:100]]
        out = {"ads": ads}
        if is_owner(request.user):
            rewarded = AdView.objects.filter(rewarded=True)
            out["owner"] = {
                "total_views": rewarded.count(),
                "total_cents": sum(v.reward_spinaz for v in rewarded.only("reward_spinaz")),
                "mine": [_ad_dict(c, request) for c in Commercial.objects.filter(owner=request.user)[:100]],
            }
        return Response(out)

    def post(self, request):
        if not is_owner(request.user):
            return Response({"detail": "Only the owner can post commercials."}, status=status.HTTP_403_FORBIDDEN)
        d = request.data or {}
        title = str(d.get("title", "")).strip()[:160]
        media_url = str(d.get("media_url", "")).strip()[:500]
        if not title or not media_url:
            return Response({"detail": "title and media_url required"}, status=status.HTTP_400_BAD_REQUEST)
        c = Commercial.objects.create(
            owner=request.user, title=title,
            sponsor=str(d.get("sponsor", "")).strip()[:120],
            media_url=media_url, media_type=str(d.get("media_type", "video")).strip()[:24],
            link_url=str(d.get("link_url", "")).strip()[:600],
            payout_cents=max(0, int(d.get("payout_cents") or 1)),
            min_watch_seconds=max(1, int(d.get("min_watch_seconds") or 15)),
            daily_cap_per_user=max(1, int(d.get("daily_cap_per_user") or 3)),
            active=True,
        )
        return Response(_ad_dict(c, request), status=status.HTTP_201_CREATED)


class AdDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        c = Commercial.objects.filter(pk=pk, owner=request.user).first()
        if not c:
            return Response({"detail": "not found"}, status=status.HTTP_404_NOT_FOUND)
        c.delete()
        return Response({"deleted": pk})


class AdRewardView(APIView):
    """POST /economy/adz/<id>/reward/ {watched_seconds} — reward the viewer
    SpinAZ = the ad's payout_cents once they've genuinely watched it."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        c = Commercial.objects.filter(pk=pk, active=True).select_related("owner").first()
        if not c:
            return Response({"detail": "ad not found"}, status=status.HTTP_404_NOT_FOUND)
        watched = max(0, int((request.data or {}).get("watched_seconds") or 0))
        today = timezone.localdate()

        # Record the view.
        view = AdView.objects.create(
            commercial=c, user=request.user, ip=_client_ip(request),
            watched_seconds=watched, day=today,
        )

        # Must have watched enough.
        if watched < c.min_watch_seconds:
            return Response({"rewarded": False, "reason": "watch_more",
                             "need_seconds": c.min_watch_seconds, "watched": watched})
        # Per-ad daily cap for this viewer.
        rewarded_today = AdView.objects.filter(commercial=c, user=request.user, day=today, rewarded=True).count()
        if rewarded_today >= c.daily_cap_per_user:
            return Response({"rewarded": False, "reason": "ad_daily_cap", "cap": c.daily_cap_per_user})
        # Global per-viewer daily cap across all ads.
        if AdView.objects.filter(user=request.user, day=today, rewarded=True).count() >= AD_REWARD_DAILY_CAP_PER_USER:
            return Response({"rewarded": False, "reason": "daily_cap", "cap": AD_REWARD_DAILY_CAP_PER_USER})
        # Can't farm your own ad.
        if c.owner_id == request.user.id:
            return Response({"rewarded": False, "reason": "own_ad"})

        reward = c.payout_cents
        award_spinaz(request.user, reward, note=f"Watched '{c.title}'")
        view.rewarded = True
        view.reward_spinaz = reward
        view.save(update_fields=["rewarded", "reward_spinaz"])
        w = wallet_for(request.user)
        return Response({"rewarded": True, "reward_spinaz": reward, "spinaz": w.spinaz})
