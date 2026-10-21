import math
from decimal import Decimal

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    METHOD_CALLZ, METHOD_IN_PERSON, METHOD_REMOTE, MIN_TEACH_RATING, MODE_CHOICES,
    MODE_HOUR, STATUS_ACCEPTED, STATUS_CANCELLED, STATUS_COMPLETED, STATUS_DECLINED,
    STATUS_REQUESTED, LessonBooking, LessonOffer, LessonPayment,
    get_skill_rating, get_user_tier,
)
from .serializers import LessonBookingSerializer, LessonOfferSerializer


class AdultVerifiedOnly(BasePermission):
    """LessonZ arranges paid 1:1 contact, so it answers to the same real gate
    BattleZ money-betting and LookmaxZ use: `Profile.verified_18plus` —
    Stripe Identity, never a self-reported birthday.

    This used to be `from apps.common.gates import AdultVerifiedOnly`, with a
    second fallback import of the same name from `apps.common.tiergate`, both
    inside bare `except Exception: pass`. Neither module has ever existed in
    this codebase — there is no `apps/common` directory at all — so both
    imports always raised ImportError and `_Gate` was plain `IsAuthenticated`
    the entire time. Every claim in this module's own docstring ("LessonZ is
    AGE-GATED... paid 1:1 contact between users is adult-verified only") was
    false: any signed-in member, minor or unverified adult, could publish an
    offer, book one, or act on a booking. That's the platform's own ScoutZ
    rule (no adult-to-minor contact) broken on the one surface that pays for
    1:1 contact by the hour.
    """

    message = ("LessonZ is 18+ ID-verified only — live 1:1 paid lessons need Stripe "
               "Identity verification on your profile before you can teach or book one.")

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        from apps.economy.models import profile_for

        return bool(profile_for(request.user).verified_18plus)


_Gate = AdultVerifiedOnly


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
        # ?mine=1 is the teacher's own "my offers" panel — it has to show
        # UNPUBLISHED ones too (is_active=False), or unpublishing an offer
        # would make it invisible to the one person who's allowed to edit
        # it back. Everyone else only ever sees what's actually live.
        mine = qp.get("mine") in ("1", "true")
        qs = LessonOffer.objects.select_related("teacher")
        if mine:
            qs = qs.filter(teacher=request.user)
        else:
            qs = qs.filter(is_active=True)

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
        if str(data.get("callz_ok")).lower() in ("1", "true") and get_user_tier(request.user) != "statz":
            return Response(
                {"detail": "Offering lessons over CallZ is StatZ-exclusive. "
                           "Publish without CallZ, or upgrade to StatZ."},
                status=status.HTTP_403_FORBIDDEN,
            )
        from apps.economy.gates import clean_gates
        ser = LessonOfferSerializer(data=data)
        ser.is_valid(raise_exception=True)
        ser.save(teacher=request.user, skill=skill, rating_snapshot=rating,
                 gates=clean_gates(data.get("gates")))
        return Response(ser.data, status=status.HTTP_201_CREATED)


class OfferDetailView(APIView):
    """A teacher could publish an offer and never see it again — no detail
    route existed at all, so a price typo or wanting to raise a rate meant
    nothing could be done short of a database edit by hand. Not even a
    read: the teacher had no way to confirm what they'd actually published.

    PATCH: fix it in place. Each booking already froze its own
    `agreed_total` at `compute_total()` time, so editing the offer
    afterward never touches what a student already agreed to pay — same
    reasoning as VenueZ's listing edit. `skill` is locked: the rating that
    was checked at publish time was checked for THIS skill, and changing it
    afterward would leave a rating-gated listing nobody re-checked.

    DELETE: unpublish, never a hard delete. `LessonBooking.offer` is
    CASCADE, so deleting an offer with real bookings on it would destroy
    every one of those students' booking history along with the listing —
    the same mistake flagged for MerchZ (`MerchPurchase.item` is CASCADE
    too). Unpublishing just stops new bookings; it can be turned back on.
    """

    permission_classes = [_Gate]

    def _mine(self, request, pk):
        try:
            return LessonOffer.objects.get(pk=pk, teacher=request.user)
        except LessonOffer.DoesNotExist:
            return None

    def patch(self, request, pk):
        offer = self._mine(request, pk)
        if not offer:
            return Response({"detail": "Not yours, or not here."}, status=status.HTTP_404_NOT_FOUND)

        d = request.data or {}
        if "skill" in d and str(d["skill"]).strip().lower() != offer.skill:
            return Response(
                {"detail": "Can't change what skill this teaches — your rating was checked "
                            "for this one. Unpublish this and make a new offer for a "
                            "different skill instead."},
                status=status.HTTP_409_CONFLICT,
            )
        if str(d.get("callz_ok")).lower() in ("1", "true") and get_user_tier(request.user) != "statz":
            return Response(
                {"detail": "Offering lessons over CallZ is StatZ-exclusive."},
                status=status.HTTP_403_FORBIDDEN,
            )

        fields = []
        if "title" in d:
            title = str(d["title"]).strip()
            if not title:
                return Response({"detail": "Title is required."}, status=status.HTTP_400_BAD_REQUEST)
            if len(title) > 140:
                return Response({"detail": "Title must be 140 characters or less."},
                                status=status.HTTP_400_BAD_REQUEST)
            offer.title = title
            fields.append("title")
        if "description" in d:
            offer.description = str(d["description"] or "")
            fields.append("description")
        if "pricing_mode" in d and d["pricing_mode"] in dict(MODE_CHOICES):
            offer.pricing_mode = d["pricing_mode"]
            fields.append("pricing_mode")
        if "price" in d:
            try:
                price = Decimal(str(d["price"]))
            except Exception:
                return Response({"detail": "price must be a number."}, status=status.HTTP_400_BAD_REQUEST)
            if price <= Decimal("0"):
                return Response({"detail": "Price must be greater than $0."}, status=status.HTTP_400_BAD_REQUEST)
            offer.price = price
            fields.append("price")
        if "currency" in d:
            offer.currency = str(d["currency"] or "USD")[:8]
            fields.append("currency")
        if "city" in d:
            offer.city = str(d["city"] or "")[:80]
            fields.append("city")
        if "latitude" in d:
            offer.latitude = d["latitude"]
            fields.append("latitude")
        if "longitude" in d:
            offer.longitude = d["longitude"]
            fields.append("longitude")
        if "remote_ok" in d:
            offer.remote_ok = bool(d["remote_ok"])
            fields.append("remote_ok")
        if "in_person_ok" in d:
            offer.in_person_ok = bool(d["in_person_ok"])
            fields.append("in_person_ok")
        if "callz_ok" in d:
            offer.callz_ok = bool(d["callz_ok"])
            fields.append("callz_ok")
        if "gates" in d:
            from apps.economy.gates import clean_gates
            offer.gates = clean_gates(d["gates"])
            fields.append("gates")
        if "is_active" in d:
            offer.is_active = bool(d["is_active"])
            fields.append("is_active")

        if not offer.remote_ok and not offer.in_person_ok:
            return Response({"detail": "A lesson has to be offered some way — remote or in person."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not fields:
            return Response({"detail": "Nothing to change."}, status=status.HTTP_400_BAD_REQUEST)
        offer.save(update_fields=fields)
        return Response(LessonOfferSerializer(offer).data)

    def delete(self, request, pk):
        offer = self._mine(request, pk)
        if not offer:
            return Response({"detail": "Not yours, or not here."}, status=status.HTTP_404_NOT_FOUND)
        if not offer.is_active:
            return Response({"detail": "Already unpublished."}, status=status.HTTP_400_BAD_REQUEST)
        offer.is_active = False
        offer.save(update_fields=["is_active"])
        return Response(LessonOfferSerializer(offer).data)


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
        if offer.gates:
            from apps.economy.gates import failing_gate, member_metrics, refusal
            from apps.economy.models import profile_for
            origin = (offer.latitude, offer.longitude) if offer.latitude is not None else (None, None)
            failed = failing_gate(member_metrics(profile_for(request.user), origin), offer.gates)
            if failed:
                return Response(refusal(failed, offer.gates), status=403)

        method = (data.get("method") or METHOD_IN_PERSON).strip()
        if method == METHOD_IN_PERSON and not offer.in_person_ok:
            return Response({"detail": "This teacher doesn't offer in-person lessons."}, status=400)
        if method == METHOD_REMOTE and not offer.remote_ok:
            return Response({"detail": "This teacher doesn't offer remote lessons."}, status=400)
        if method == METHOD_CALLZ:
            if not offer.callz_ok:
                return Response({"detail": "This teacher doesn't offer CallZ lessons."}, status=400)
            if get_user_tier(request.user) != "statz":
                return Response(
                    {"detail": "CallZ lessons are StatZ-exclusive. Upgrade to StatZ to book over CallZ."},
                    status=403,
                )

        ser = LessonBookingSerializer(data=data)
        ser.is_valid(raise_exception=True)
        booking = ser.save(
            student=request.user,
            offer=offer,
            pricing_mode=data.get("pricing_mode") or offer.pricing_mode,
            currency=offer.currency,
            method=method,
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
            payment, created = LessonPayment.objects.get_or_create(
                booking=booking,
                defaults={
                    "payer": booking.student,          # student pays...
                    "payee": booking.offer.teacher,    # ...teacher receives. Never reversed.
                    "amount": booking.agreed_total,
                    "currency": booking.currency,
                },
            )
            # This used to hook into `apps.common.wallet.charge`, which has
            # never existed in this codebase — the bare except swallowed the
            # ImportError every time, so `LessonPayment` rows were created
            # with `settled=False` and no money EVER moved. "Complete" looked
            # like it worked (200, a payment row, a completed booking) while
            # the student was never charged and the teacher was never paid.
            # `pay_between` is the platform's real one-way wallet move
            # (money_cents, not dollars), the same primitive MerchZ/CallZ use.
            if created and payment.amount > 0:
                from apps.economy.models import pay_between

                amount_cents = int((payment.amount * 100).to_integral_value())
                moved = pay_between(booking.student, booking.offer.teacher, amount_cents,
                                     note=f"LessonZ #{booking.id} · {booking.offer.title}"[:200])
                if moved is not None:
                    payment.settled = True
                    payment.save(update_fields=["settled"])
                # moved is None (insufficient balance): the booking still
                # completes — the lesson happened — but the payment stays
                # unsettled rather than blocking the teacher from marking a
                # lesson they already gave as done. LogZ/LessonZ's own
                # history can surface an unsettled payment for the teacher
                # to chase; that's a follow-on screen, not this endpoint's job.
        else:
            return Response({"detail": f"Unknown action '{action}'."}, status=400)

        booking.save()
        return Response(LessonBookingSerializer(booking).data)
