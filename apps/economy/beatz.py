"""Path 4: Beat/Stem Licensing — producers sell beats, buyers license them.

The beat licensing system creates a revenue path for producers while giving buyers
access to professional instrumentals. Key affordances:

  * Producers upload beats with metadata (genre, tempo, license type).
  * Buyers browse beats, purchase licenses (exclusive or non-exclusive).
  * License type determines usage rights: exclusive gives one buyer, non-exclusive
    allows many buyers at the same price. Exclusive is higher value.
  * Buyers report where they use purchased beats (YouTube, streaming, commercial).
  * Revenue splits between platform (developer tax) and producer payout.
  * Cross-pollination: purchases link back to posts/uploads, beats appear in feed.
"""
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Q, F
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.economy.models import (
    BeatZ, BeatPurchase, BeatUsage, Upload, Post, Wallet, split_cents
)

User = get_user_model()


def _beat_dict(beat, buyer=None):
    """Format a beat for API response."""
    data = {
        "id": beat.id,
        "producer_id": beat.producer_id,
        "producer": beat.producer.username,
        "title": beat.title,
        "description": beat.description,
        "genre": beat.genre,
        "tempo_bpm": beat.tempo_bpm,
        "price_cents": beat.price_cents,
        "license_type": beat.license_type,
        "quantity_available": beat.quantity_available,
        "created_at": beat.created_at,
    }
    if buyer:
        purchase = BeatPurchase.objects.filter(
            beat=beat, buyer=buyer
        ).first()
        data["owned_by_me"] = purchase is not None
        data["purchase_id"] = purchase.id if purchase else None
    return data


class BeatListView(APIView):
    """GET /api/economy/beatz/ — browse all beats.
    POST /api/economy/beatz/ — producer uploads a new beat.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List all beats available for purchase, optionally filtered by genre or producer."""
        genre = request.query_params.get("genre")
        producer_id = request.query_params.get("producer_id")

        beats = BeatZ.objects.all().order_by("-created_at")

        if genre:
            beats = beats.filter(genre=genre)
        if producer_id:
            beats = beats.filter(producer_id=producer_id)

        return Response({
            "beats": [_beat_dict(b, buyer=request.user) for b in beats]
        })

    def post(self, request):
        """Producer uploads a new beat."""
        title = request.data.get("title")
        description = request.data.get("description", "")
        genre = request.data.get("genre")
        tempo_bpm = request.data.get("tempo_bpm")
        price_cents = request.data.get("price_cents")
        license_type = request.data.get("license_type", BeatZ.LICENSE_NONEXCLUSIVE)
        quantity_available = request.data.get("quantity_available")

        if not title:
            return Response(
                {"title": "Required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not genre:
            return Response(
                {"genre": "Required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not tempo_bpm:
            return Response(
                {"tempo_bpm": "Required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        if price_cents is None:
            return Response(
                {"price_cents": "Required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        if license_type not in [BeatZ.LICENSE_EXCLUSIVE, BeatZ.LICENSE_NONEXCLUSIVE]:
            return Response(
                {"license_type": "Must be 'exclusive' or 'nonexclusive'"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if license_type == BeatZ.LICENSE_EXCLUSIVE:
            quantity_available = quantity_available or 1
        else:
            quantity_available = quantity_available or 1000

        beat = BeatZ.objects.create(
            producer=request.user,
            title=title,
            description=description,
            genre=genre,
            tempo_bpm=tempo_bpm,
            price_cents=int(price_cents),
            license_type=license_type,
            quantity_available=quantity_available
        )

        return Response(_beat_dict(beat, buyer=request.user), status=status.HTTP_201_CREATED)


class BeatDetailView(APIView):
    """GET /api/economy/beatz/<beat_id>/ — get beat details.
    PATCH /api/economy/beatz/<beat_id>/ — producer updates beat.
    """
    permission_classes = [IsAuthenticated]

    def get_beat(self, beat_id, user):
        """Get beat, checking ownership only for edit operations."""
        try:
            beat = BeatZ.objects.get(id=beat_id)
        except BeatZ.DoesNotExist:
            return None
        return beat

    def get(self, request, beat_id):
        """Get beat details."""
        beat = self.get_beat(beat_id, request.user)
        if not beat:
            return Response(
                {"detail": "Beat not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(_beat_dict(beat, buyer=request.user))

    def patch(self, request, beat_id):
        """Producer updates beat details."""
        beat = self.get_beat(beat_id, request.user)
        if not beat:
            return Response(
                {"detail": "Beat not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if beat.producer != request.user:
            return Response(
                {"detail": "Only the producer can update this beat"},
                status=status.HTTP_403_FORBIDDEN
            )

        if "title" in request.data:
            beat.title = request.data["title"]
        if "description" in request.data:
            beat.description = request.data["description"]
        if "genre" in request.data:
            beat.genre = request.data["genre"]
        if "tempo_bpm" in request.data:
            beat.tempo_bpm = int(request.data["tempo_bpm"])
        if "price_cents" in request.data:
            beat.price_cents = int(request.data["price_cents"])
        if "quantity_available" in request.data and beat.license_type == BeatZ.LICENSE_EXCLUSIVE:
            beat.quantity_available = request.data["quantity_available"]

        beat.save()

        return Response(_beat_dict(beat, buyer=request.user))


class BeatPurchaseView(APIView):
    """POST /api/economy/beatz/<beat_id>/purchase/ — buyer purchases a license."""
    permission_classes = [IsAuthenticated]

    def post(self, request, beat_id):
        """Purchase a license to a beat."""
        try:
            beat = BeatZ.objects.get(id=beat_id)
        except BeatZ.DoesNotExist:
            return Response(
                {"detail": "Beat not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if beat.producer == request.user:
            return Response(
                {"detail": "Cannot purchase your own beat"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if beat.license_type == BeatZ.LICENSE_EXCLUSIVE:
            existing = BeatPurchase.objects.filter(beat=beat).exists()
            if existing:
                return Response(
                    {"detail": "This exclusive beat is already owned"},
                    status=status.HTTP_400_BAD_REQUEST
                )

        already_owns = BeatPurchase.objects.filter(
            beat=beat, buyer=request.user
        ).exists()
        if already_owns:
            return Response(
                {"detail": "You already own a license to this beat"},
                status=status.HTTP_400_BAD_REQUEST
            )

        wallet = Wallet.objects.get(user=request.user)
        if wallet.spinaz < beat.price_cents:
            return Response(
                {"detail": f"Insufficient SpinaZ. Need {beat.price_cents}, have {wallet.spinaz}"},
                status=status.HTTP_402_PAYMENT_REQUIRED
            )

        wallet.spinaz = F("spinaz") - beat.price_cents
        wallet.save(update_fields=["spinaz"])

        buyer_membership = request.user.membership
        developer_cut, producer_payout = split_cents(beat.price_cents, buyer_membership.dev_tax_rate)

        purchase = BeatPurchase.objects.create(
            buyer=request.user,
            beat=beat,
            license_type=beat.license_type,
            price_cents=beat.price_cents,
            developer_cut_cents=developer_cut,
            producer_payout_cents=producer_payout
        )

        producer_wallet = Wallet.objects.get(user=beat.producer)
        producer_wallet.spinaz = F("spinaz") + producer_payout
        producer_wallet.save(update_fields=["spinaz"])

        return Response({
            "id": purchase.id,
            "beat_id": beat.id,
            "license_type": purchase.license_type,
            "price_cents": purchase.price_cents,
            "producer_payout_cents": producer_payout,
            "purchased_at": purchase.purchased_at,
        }, status=status.HTTP_201_CREATED)


class BeatUsageReportView(APIView):
    """POST /api/economy/beatz/purchases/<purchase_id>/report-usage/ — report where a beat is used."""
    permission_classes = [IsAuthenticated]

    def post(self, request, purchase_id):
        """Report usage of a purchased beat."""
        try:
            purchase = BeatPurchase.objects.get(id=purchase_id, buyer=request.user)
        except BeatPurchase.DoesNotExist:
            return Response(
                {"detail": "Purchase not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        usage_kind = request.data.get("usage_kind")
        if usage_kind not in [BeatUsage.USAGE_PERSONAL, BeatUsage.USAGE_YOUTUBE,
                              BeatUsage.USAGE_STREAMING, BeatUsage.USAGE_COMMERCIAL]:
            return Response(
                {"usage_kind": "Must be one of: personal, youtube, streaming, commercial"},
                status=status.HTTP_400_BAD_REQUEST
            )

        post_id = request.data.get("post_id")
        upload_id = request.data.get("upload_id")

        post = None
        upload = None

        if post_id:
            try:
                post = Post.objects.get(id=post_id, creator=request.user)
            except Post.DoesNotExist:
                return Response(
                    {"detail": "Post not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

        if upload_id:
            try:
                upload = Upload.objects.get(id=upload_id, uploader=request.user)
            except Upload.DoesNotExist:
                return Response(
                    {"detail": "Upload not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

        usage = BeatUsage.objects.create(
            purchase=purchase,
            post=post,
            upload=upload,
            usage_kind=usage_kind,
            details=request.data.get("details", "")
        )

        return Response({
            "id": usage.id,
            "usage_kind": usage.usage_kind,
            "reported_at": usage.reported_at,
        }, status=status.HTTP_201_CREATED)


class BeatEarningsView(APIView):
    """GET /api/economy/beatz/earnings/ — get producer earnings from beat sales."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get total earnings and breakdown by beat."""
        purchases = BeatPurchase.objects.filter(beat__producer=request.user)

        total_earnings = sum(p.producer_payout_cents for p in purchases)

        by_beat = {}
        for purchase in purchases:
            beat_id = purchase.beat_id
            if beat_id not in by_beat:
                by_beat[beat_id] = {
                    "beat_id": beat_id,
                    "beat_title": purchase.beat.title,
                    "sales": 0,
                    "earnings_cents": 0,
                }
            by_beat[beat_id]["sales"] += 1
            by_beat[beat_id]["earnings_cents"] += purchase.producer_payout_cents

        return Response({
            "total_earnings_cents": total_earnings,
            "total_sales": purchases.count(),
            "by_beat": list(by_beat.values()),
        })


class ProducerBeatsView(APIView):
    """GET /api/economy/beatz/my-beats/ — get producer's own beats."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List all beats uploaded by the requesting producer."""
        beats = BeatZ.objects.filter(producer=request.user).order_by("-created_at")

        return Response({
            "beats": [
                {
                    **_beat_dict(b),
                    "sales": BeatPurchase.objects.filter(beat=b).count(),
                }
                for b in beats
            ]
        })
