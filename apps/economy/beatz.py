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


# What a beat may be priced at, in cents of real money (💵). The price is a
# dollar figure on the screen, so it is charged in dollars — it used to take
# SpinaZ for a number displayed as cents, which made a "$5" beat cost 500 🍥.
BEAT_PRICE_MIN_CENTS = 100
BEAT_PRICE_MAX_CENTS = 50000


def _clean_price(value):
    try:
        cents = int(value)
    except (TypeError, ValueError):
        raise ValueError("Price must be a whole number of cents.")
    if not BEAT_PRICE_MIN_CENTS <= cents <= BEAT_PRICE_MAX_CENTS:
        raise ValueError(f"Price must be between ${BEAT_PRICE_MIN_CENTS/100:.2f} "
                         f"and ${BEAT_PRICE_MAX_CENTS/100:.2f}.")
    return cents


def _audio_for(user, upload_id):
    """One of the member's own uploads, or None. Raises ValueError otherwise."""
    if upload_id in (None, ""):
        return None
    up = Upload.objects.filter(pk=upload_id, user=user).first()
    if not up:
        raise ValueError("That audio isn't one of your uploads.")
    return up


def _split(beat):
    """(platform fee, producer payout). The fee is the PRODUCER'S tier, the
    same as a post sale — what a seller keeps is their plan, not the buyer's."""
    from .models import DEV_TAX, membership_for
    return split_cents(beat.price_cents, DEV_TAX[membership_for(beat.producer).tier])


def _beat_dict(beat, request=None, owned=None, sold=None):
    """A beat for the screen. `owned` (purchase id or None) and `sold` are
    batched by the list views; left as None they are looked up per beat."""
    from .media import stable_media_url
    user = getattr(request, "user", None)
    if owned is None and user is not None and user.is_authenticated:
        owned = BeatPurchase.objects.filter(beat=beat, buyer=user).values_list("id", flat=True).first()
    if sold is None:
        sold = beat.purchases.count()
    exclusive = beat.license_type == BeatZ.LICENSE_EXCLUSIVE
    left = max(0, (beat.quantity_available or 0) - (sold if exclusive else 0))
    audio = stable_media_url(beat.audio_upload, request) if beat.audio_upload_id else ""
    mine = bool(user is not None and beat.producer_id == getattr(user, "id", None))
    if mine:
        why_not = "It's your beat."
    elif owned:
        why_not = "You already hold a license."
    elif not audio:
        why_not = "No audio attached yet — nobody can buy what they can't hear."
    elif exclusive and sold:
        why_not = "The exclusive license has been sold."
    else:
        why_not = ""
    return {
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
        "left": left,
        "sold": sold,
        "audio_url": audio or None,
        "mine": mine,
        "owned_by_me": bool(owned),
        "purchase_id": owned or None,
        "can_buy": not why_not,
        "why_not": why_not,
        "created_at": beat.created_at,
    }


def _batch(beats, request):
    from django.db.models import Count
    ids = [b.id for b in beats]
    sold = dict(BeatPurchase.objects.filter(beat_id__in=ids).values_list("beat_id")
                .annotate(n=Count("id")))
    owned = dict(BeatPurchase.objects.filter(beat_id__in=ids, buyer=request.user)
                 .values_list("beat_id", "id"))
    return [_beat_dict(b, request, owned=owned.get(b.id, 0), sold=sold.get(b.id, 0))
            for b in beats]


class BeatListView(APIView):
    """GET /api/economy/beatz/ — browse all beats.
    POST /api/economy/beatz/ — producer lists a new beat.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        genre = request.query_params.get("genre")
        producer_id = request.query_params.get("producer_id")
        beats = BeatZ.objects.select_related("producer", "audio_upload").order_by("-created_at")
        if genre:
            beats = beats.filter(genre=genre)
        if producer_id:
            beats = beats.filter(producer_id=producer_id)
        return Response({
            "beats": _batch(list(beats[:200]), request),
            "min_cents": BEAT_PRICE_MIN_CENTS, "max_cents": BEAT_PRICE_MAX_CENTS,
        })

    def post(self, request):
        d = request.data
        title = str(d.get("title") or "").strip()[:200]
        genre = str(d.get("genre") or "").strip()[:50]
        license_type = d.get("license_type", BeatZ.LICENSE_NONEXCLUSIVE)
        if not title:
            return Response({"title": "Required"}, status=status.HTTP_400_BAD_REQUEST)
        if not genre:
            return Response({"genre": "Required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            tempo = int(d.get("tempo_bpm") or 0)
        except (TypeError, ValueError):
            tempo = 0
        if not 20 <= tempo <= 400:
            return Response({"tempo_bpm": "Required, 20-400 BPM"}, status=status.HTTP_400_BAD_REQUEST)
        if d.get("price_cents") is None:
            return Response({"price_cents": "Required"}, status=status.HTTP_400_BAD_REQUEST)
        if license_type not in [BeatZ.LICENSE_EXCLUSIVE, BeatZ.LICENSE_NONEXCLUSIVE]:
            return Response({"license_type": "Must be 'exclusive' or 'nonexclusive'"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            price = _clean_price(d.get("price_cents"))
            audio = _audio_for(request.user, d.get("audio_upload_id"))
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        # Exclusive is one buyer, always — a stock count above one would make
        # the word mean nothing.
        qty = 1 if license_type == BeatZ.LICENSE_EXCLUSIVE else 1000
        beat = BeatZ.objects.create(
            producer=request.user, title=title,
            description=str(d.get("description") or "")[:2000], genre=genre,
            tempo_bpm=tempo, price_cents=price, license_type=license_type,
            quantity_available=qty, audio_upload=audio)
        return Response(_beat_dict(beat, request), status=status.HTTP_201_CREATED)


class BeatDetailView(APIView):
    """GET /api/economy/beatz/<beat_id>/ — beat details.
    PATCH /api/economy/beatz/<beat_id>/ — producer updates the beat.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, beat_id):
        beat = BeatZ.objects.filter(id=beat_id).select_related("producer", "audio_upload").first()
        if not beat:
            return Response({"detail": "Beat not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(_beat_dict(beat, request))

    def patch(self, request, beat_id):
        beat = BeatZ.objects.filter(id=beat_id).first()
        if not beat:
            return Response({"detail": "Beat not found"}, status=status.HTTP_404_NOT_FOUND)
        if beat.producer_id != request.user.id:
            return Response({"detail": "Only the producer can update this beat"},
                            status=status.HTTP_403_FORBIDDEN)
        d = request.data
        try:
            if "title" in d:
                beat.title = str(d["title"]).strip()[:200] or beat.title
            if "description" in d:
                beat.description = str(d["description"])[:2000]
            if "genre" in d:
                beat.genre = str(d["genre"]).strip()[:50]
            if "tempo_bpm" in d:
                beat.tempo_bpm = int(d["tempo_bpm"])
            if "price_cents" in d:
                beat.price_cents = _clean_price(d["price_cents"])
            if "audio_upload_id" in d:
                beat.audio_upload = _audio_for(request.user, d["audio_upload_id"])
        except (TypeError, ValueError) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        beat.save()
        return Response(_beat_dict(beat, request))


class BeatPurchaseView(APIView):
    """GET  — the quote: price, your balance, the fee and the producer's cut.
    POST — buy a license, in real money, atomically."""
    permission_classes = [IsAuthenticated]

    def get(self, request, beat_id):
        from .models import wallet_for
        beat = BeatZ.objects.filter(id=beat_id).select_related("producer", "audio_upload").first()
        if not beat:
            return Response({"detail": "Beat not found"}, status=status.HTTP_404_NOT_FOUND)
        fee, payout = _split(beat)
        return Response({
            **_beat_dict(beat, request),
            "balance_cents": wallet_for(request.user).money_cents or 0,
            "fee_cents": fee, "producer_cents": payout,
        })

    def post(self, request, beat_id):
        from django.db import IntegrityError, transaction
        from .models import Transaction, log_resource, wallet_for
        from .views import credit_owner

        wallet_for(request.user)
        try:
            with transaction.atomic():
                # Locked, so two buyers racing for an exclusive can't both win.
                beat = (BeatZ.objects.select_for_update()
                        .select_related("producer", "audio_upload").filter(id=beat_id).first())
                if not beat:
                    return Response({"detail": "Beat not found"}, status=status.HTTP_404_NOT_FOUND)
                if beat.producer_id == request.user.id:
                    return Response({"detail": "Cannot purchase your own beat"},
                                    status=status.HTTP_400_BAD_REQUEST)
                if BeatPurchase.objects.filter(beat=beat, buyer=request.user).exists():
                    return Response({"detail": "You already own a license to this beat"},
                                    status=status.HTTP_400_BAD_REQUEST)
                if not beat.audio_upload_id:
                    return Response({"detail": "This beat has no audio attached yet, so it "
                                               "can't be sold. Nothing was charged."},
                                    status=status.HTTP_400_BAD_REQUEST)
                exclusive = beat.license_type == BeatZ.LICENSE_EXCLUSIVE
                if exclusive and BeatPurchase.objects.filter(beat=beat).exists():
                    return Response({"detail": "This exclusive beat is already owned"},
                                    status=status.HTTP_400_BAD_REQUEST)
                price = beat.price_cents
                moved = Wallet.objects.filter(user=request.user, money_cents__gte=price).update(
                    money_cents=F("money_cents") - price, updated_at=timezone.now())
                if not moved:
                    have = wallet_for(request.user).money_cents or 0
                    return Response(
                        {"detail": f"Insufficient balance. You need ${price/100:.2f} and have "
                                   f"${have/100:.2f}. Nothing was charged.",
                         "price_cents": price, "balance_cents": have},
                        status=status.HTTP_402_PAYMENT_REQUIRED)
                fee, payout = _split(beat)
                purchase = BeatPurchase.objects.create(
                    buyer=request.user, beat=beat, license_type=beat.license_type,
                    price_cents=price, developer_cut_cents=fee, producer_payout_cents=payout)
                wallet_for(beat.producer)
                Wallet.objects.filter(user=beat.producer).update(
                    money_cents=F("money_cents") + payout, updated_at=timezone.now())
                log_resource(beat.producer, Transaction.RES_MONEY, payout,
                             note=f"BeatZ sale — {beat.title} ({beat.license_type})")
                log_resource(request.user, Transaction.RES_MONEY, -price,
                             note=f"BeatZ license — {beat.title} ({beat.license_type})")
                credit_owner(request.user, fee, f"BeatZ platform fee (beat #{beat.id})")
        except IntegrityError:
            return Response({"detail": "You already own a license to this beat. Nothing was charged twice."},
                            status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "id": purchase.id,
            "beat_id": beat.id,
            "license_type": purchase.license_type,
            "price_cents": purchase.price_cents,
            "producer_payout_cents": payout,
            "purchased_at": purchase.purchased_at,
            "balance_after": wallet_for(request.user).money_cents,
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
                post = Post.objects.get(id=post_id, author=request.user)
            except Post.DoesNotExist:
                return Response(
                    {"detail": "Post not found"},
                    status=status.HTTP_404_NOT_FOUND
                )

        if upload_id:
            try:
                upload = Upload.objects.get(id=upload_id, user=request.user)
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
        purchases = BeatPurchase.objects.filter(beat__producer=request.user).select_related("beat")

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

        rows = _batch(list(beats.select_related("producer", "audio_upload")), request)
        for r in rows:
            r["sales"] = r["sold"]
        return Response({"beats": rows})
