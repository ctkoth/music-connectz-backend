"""SoundCloud engagement rewards: likes, reposts, comments on tracks."""
from django.utils import timezone
from django.db.models import Count
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import SoundCloudEngagement, Transaction, membership_for
from .catalog import limits_for

# Daily engagement reward caps
ENGAGEMENT_DAILY_CAPS = {
    SoundCloudEngagement.KIND_LIKE: 20,
    SoundCloudEngagement.KIND_REPOST: 2,
    SoundCloudEngagement.KIND_COMMENT: 5,
}

# Reward amounts (energy, spinaz)
ENGAGEMENT_REWARDS = {
    SoundCloudEngagement.KIND_LIKE: {"energy": 1, "spinaz": 10},
    SoundCloudEngagement.KIND_REPOST: {"energy": 3, "spinaz": 25},
    SoundCloudEngagement.KIND_COMMENT: {"energy": 5, "spinaz": 50},
}

ENGAGEMENT_LABELS = {
    SoundCloudEngagement.KIND_LIKE: "SoundCloud like",
    SoundCloudEngagement.KIND_REPOST: "SoundCloud repost",
    SoundCloudEngagement.KIND_COMMENT: "SoundCloud comment",
}


def engagements_today_for(user, kind):
    """Count engagements of a given kind created today."""
    today = timezone.localdate()
    return (
        SoundCloudEngagement.objects.filter(
            user=user,
            kind=kind,
            created_at__date=today,
            rewarded=True,
        )
        .count()
    )


def can_reward_engagement(user, kind):
    """Check if user has reward capacity left today for this engagement kind."""
    today_count = engagements_today_for(user, kind)
    cap = ENGAGEMENT_DAILY_CAPS.get(kind, 0)
    return today_count < cap


class SoundCloudEngagementView(APIView):
    """POST to record and reward a SoundCloud engagement event (like, repost, comment).

    The member reports engagement on their own SoundCloud track and we:
    1. Verify the track URL is valid SoundCloud
    2. Check daily caps aren't exceeded
    3. Award energy + spinaz if first time for this track
    4. Log the transaction
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        kind = (request.data.get("kind") or "").lower()
        track_url = (request.data.get("track_url") or "").strip()
        track_title = (request.data.get("track_title") or "").strip()[:500]
        track_id = (request.data.get("track_id") or "").strip()

        # Validate inputs
        if kind not in dict(SoundCloudEngagement.KIND_CHOICES):
            return Response(
                {"detail": f"kind must be one of: {', '.join(dict(SoundCloudEngagement.KIND_CHOICES).keys())}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not track_url or "soundcloud.com" not in track_url.lower():
            return Response(
                {"detail": "valid SoundCloud track URL required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not track_id:
            return Response(
                {"detail": "track_id required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check daily cap
        if not can_reward_engagement(request.user, kind):
            cap = ENGAGEMENT_DAILY_CAPS.get(kind, 0)
            return Response(
                {
                    "detail": f"daily {kind} reward limit ({cap}) reached",
                    "cap": cap,
                    "used_today": engagements_today_for(request.user, kind),
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # Check if already rewarded for this track
        engagement, created = SoundCloudEngagement.objects.get_or_create(
            user=request.user,
            track_id=track_id,
            kind=kind,
            defaults={
                "track_url": track_url,
                "track_title": track_title,
                "rewarded": False,
            },
        )

        if not created and engagement.rewarded:
            # Already rewarded, don't double-dip
            return Response(
                {"detail": f"already rewarded for {kind} on this track"},
                status=status.HTTP_409_CONFLICT,
            )

        # Award the reward
        reward = ENGAGEMENT_REWARDS.get(kind, {})
        energy = reward.get("energy", 0)
        spinaz = reward.get("spinaz", 0)

        # Create transaction for energy
        if energy:
            Transaction.objects.create(
                user=request.user,
                kind=Transaction.KIND_EARN,
                resource=Transaction.RES_ENERGY,
                amount=energy,
                note=f"{ENGAGEMENT_LABELS.get(kind, kind)}: {track_title or track_url}",
            )

        # Create transaction for spinaz
        if spinaz:
            Transaction.objects.create(
                user=request.user,
                kind=Transaction.KIND_EARN,
                resource=Transaction.RES_SPINAZ,
                amount=spinaz,
                note=f"{ENGAGEMENT_LABELS.get(kind, kind)}: {track_title or track_url}",
            )

        # Mark as rewarded
        engagement.rewarded = True
        engagement.save(update_fields=["rewarded"])

        # Return current state
        return Response(
            {
                "engagement": {
                    "kind": engagement.kind,
                    "track_url": engagement.track_url,
                    "track_title": engagement.track_title,
                    "rewarded": True,
                    "created_at": engagement.created_at.isoformat(),
                },
                "reward": {
                    "energy": energy,
                    "spinaz": spinaz,
                },
                "caps_remaining": {
                    kind: ENGAGEMENT_DAILY_CAPS.get(kind, 0) - engagements_today_for(request.user, kind) - 1
                },
            },
            status=status.HTTP_201_CREATED,
        )

    def get(self, request):
        """GET /api/economy/soundcloud/engagement/ → user's engagement history + today's counts."""
        today = timezone.localdate()

        # Get today's engagement counts by kind
        today_counts = (
            SoundCloudEngagement.objects.filter(
                user=request.user,
                created_at__date=today,
                rewarded=True,
            )
            .values("kind")
            .annotate(count=Count("id"))
        )

        today_by_kind = {row["kind"]: row["count"] for row in today_counts}

        # Calculate remaining caps
        caps_remaining = {
            kind: ENGAGEMENT_DAILY_CAPS.get(kind, 0) - today_by_kind.get(kind, 0)
            for kind in dict(SoundCloudEngagement.KIND_CHOICES).keys()
        }

        # Get recent engagements
        recent = (
            SoundCloudEngagement.objects.filter(user=request.user, rewarded=True)
            .order_by("-created_at")[:50]
            .values(
                "id", "kind", "track_id", "track_url", "track_title", "created_at"
            )
        )

        return Response(
            {
                "caps_remaining": caps_remaining,
                "today_counts": today_by_kind,
                "caps": ENGAGEMENT_DAILY_CAPS,
                "rewards": ENGAGEMENT_REWARDS,
                "recent_engagements": list(recent),
            }
        )
