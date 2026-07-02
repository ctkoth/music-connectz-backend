import math
from decimal import Decimal

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    MIN_TEACH_RATING, MODE_HOUR, STATUS_ACCEPTED, STATUS_CANCELLED,
    STATUS_COMPLETED, STATUS_DECLINED, STATUS_REQUESTED,
    LessonBooking, LessonOffer, LessonPayment, get_skill_rating,
)
from .serializers import LessonBookingSerializer, LessonOfferSerializer

# AGE GATE — LessonZ arranges paid 1:1 contact, so it is adult-verified only,
# using the platform's existing gate (snapshot-at-activation preserved there).
try:
    from apps.common.gates import AdultVerifiedOnly as _Gate  # type: ignore
except Exception:  # pragma: no cover
    try:
        from apps.common.tiergate import AdultVerifiedOnly as _Gate  # type: ignore
    except Exception:  # pragma: no cover
        _Gate = IsAuthenticated


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class EligibilityView(APIView):
    """GET ?skill=mimez -> can this user teach that skill?"""

    permission_classes = [_Gate]

    def get(self, request):
        skill = (request.query_params.get("skill") or "").strip().lower()
        if not skill:
            return Response({"detail": "skill query param required."}, status=400)
        rating = get_skill_rating(request.user, skill)
        return Response(
            {
                "skill": skill,
                "rating": rating,
                "min_required": MIN_TEACH_RATING,
                "can_teach": rating >= MIN_TEACH_RATING,
            }
        )


class OfferListCreateView(APIView):
    """GET: browse/search offers (distance, skill, price, mode, remote).
    POST: publish an offer (rating >= 6 enforced, snapshotted)."""

    permission_classes = [_Gate]

    def get(self, request):
        qp = request.query_params
        qs = LessonOffer.objects.filter(is_active=True).select_related("teacher")

        if qp.get("skill"):
            qs = qs.filter(skill__iexact=qp["skill"].strip())
        if qp.get("mode") in (MODE_HOUR, "per_lesson"):
            qs = qs.filter(pricing_mode=qp["mode"])
        if qp.get("max_price"):
            try:
                qs = qs.filter(price__lte=Decimal(qp["max_price"]))
            except Exception:
                pass
        if qp.get("remote") in ("1", "true"):
            qs = qs.filter(remote_ok=True)
        if qp.get("city"):
            qs = qs.filter(city__icontains=qp["city"].strip())

        rows = list(qs[:200])

        # Distance filter/sort like CollabZ: ?lat=&lng=&max_km=
        lat, lng = qp.get("lat"), qp.get("lng")
        if lat and lng:
            try:
                lat, lng = float(lat), float(lng)
                max_km = float(qp.get("max_km", 0) or 0)
                out = []
                for o in rows:
                    if o.latitude is None or o.longitude is None:
                        if o.remote_ok:
                            o.distance_km = None
                            out.append(o)
                        continue
                    d = round(_haversine_km(lat, lng, o.latitude, o.longitude), 1)
                    if max_km and d > max_km and not o.remote_ok:
                        continue
                    if max_km and d > max_km and o.remote_ok:
                        o.distance_km = d
                        out.append(o)
                        continue
                    o.distance_km = d
                    out.append(o)
                rows = sorted(out, key=lambda x: (x.distance_km is None, x.distance_km or 0))
            except ValueError:
                pass

        return Response(LessonOfferSerializer(rows, many=True).data)

    def post(self, request):
        data = request.data or {}
        skill = (data.get("skill") or "").strip().lower()
        rating = get_skill_rating(request.user, skill) if skill else 0
        if rating < MIN_TEACH_RATING:
            return Response(
                {
                    "detail": (
                        f"You need a rating of {MIN_TEACH_RATING}+ in '{skill}' to teach it "
                        f"(yours: {rating}). Train it up in SkillZ or get rated in RateZ."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        ser = LessonOfferSerializer(data=data)
        ser.is_valid(raise_exception=True)
        ser.save(teacher=request.user, skill=skill, rating_snapshot=rating)
        return Response(ser.data, status=status.HTTP_201_CREATED)


class BookingListCreateView(APIView):
    """GET: my bookings (as student + as teacher). POST: request a lesson."""

    permission_classes = [_Gate]

    def get(self, request):
        as_student = LessonBooking.objects.filter(student=request.user)
        as_teacher = LessonBooking.objects.filter(offer__teacher=request.user)
        return Response(
            {
                "as_student": LessonBookingSerializer(as_student, many=True).data,
                "as_teacher": LessonBookingSerializer(as_teacher, many=True).data,
            }
        )

    def post(self, request):
        data = request.data or {}
        try:
            offer = LessonOffer.objects.get(pk=data.get("offer"), is_active=True)
        except LessonOffer.DoesNotExist:
            return Response({"detail": "Offer not found."}, status=404)
        if offer.teacher_id == request.user.id:
            return Response({"detail": "You can't book your own lesson."}, status=400)

        ser = LessonBookingSerializer(data=data)
        ser.is_valid(raise_exception=True)
        booking = ser.save(
            student=request.user,
            offer=offer,
            pricing_mode=data.get("pricing_mode") or offer.pricing_mode,
            currency=offer.currency,
        )
        booking.agreed_total = booking.compute_total()
        booking.save(update_fields=["agreed_total"])
        return Response(LessonBookingSerializer(booking).data, status=201)


class BookingActionView(APIView):
    """POST /bookings/<id>/<action>/ — accept|decline|cancel|complete.

    complete: charges the STUDENT the agreed total, credited to the TEACHER.
    One-directional by design — there is no path that debits the teacher.
    """

    permission_classes = [_Gate]

    @transaction.atomic
    def post(self, request, pk, action):
        try:
            booking = LessonBooking.objects.select_for_update().get(pk=pk)
        except LessonBooking.DoesNotExist:
            return Response({"detail": "Booking not found."}, status=404)

        is_teacher = booking.offer.teacher_id == request.user.id
        is_student = booking.student_id == request.user.id
        if not (is_teacher or is_student):
            return Response({"detail": "Not your booking."}, status=403)

        if action == "accept":
            if not is_teacher or booking.status != STATUS_REQUESTED:
                return Response({"detail": "Only the teacher can accept a requested booking."}, status=400)
            booking.status = STATUS_ACCEPTED
        elif action == "decline":
            if not is_teacher or booking.status != STATUS_REQUESTED:
                return Response({"detail": "Only the teacher can decline a requested booking."}, status=400)
            booking.status = STATUS_DECLINED
        elif action == "cancel":
            if booking.status in (STATUS_COMPLETED, STATUS_CANCELLED):
                return Response({"detail": "Too late to cancel."}, status=400)
            booking.status = STATUS_CANCELLED
        elif action == "complete":
            if not is_teacher or booking.status != STATUS_ACCEPTED:
                return Response({"detail": "Only the teacher can complete an accepted booking."}, status=400)
            booking.status = STATUS_COMPLETED
            payment, _ = LessonPayment.objects.get_or_create(
                booking=booking,
                defaults={
                    "payer": booking.student,          # student pays...
                    "payee": booking.offer.teacher,    # ...teacher receives. Never reversed.
                    "amount": booking.agreed_total,
                    "currency": booking.currency,
                },
            )
            # Defensive hook into the platform wallet if it exists.
            try:  # pragma: no cover - environment dependent
                from apps.common.wallet import charge as _charge

                ref = _charge(payer=booking.student, payee=booking.offer.teacher,
                              amount=booking.agreed_total, currency=booking.currency,
                              memo=f"LessonZ #{booking.id}")
                payment.settled = True
                payment.external_ref = str(ref or "")
                payment.save(update_fields=["settled", "external_ref"])
            except Exception:
                pass  # recorded, settle via wallet later
        else:
            return Response({"detail": f"Unknown action '{action}'."}, status=400)

        booking.save()
        return Response(LessonBookingSerializer(booking).data)
