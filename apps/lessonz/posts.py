"""Lesson POSTS — recorded lessons anyone within owner-set visibility can pay
to unlock.

Safety model (matches the platform's ScoutZ rule — no adult-to-minor contact
channels):
- CREATING posts (teaching) is ADULT-GATED + requires rating >= 6.
- VIEWING and UNLOCKING posts requires only authentication — students may be
  minors, because a post is one-to-many recorded content with no contact
  channel, live session, or location exchange.
- Payment is one-directional: the student pays the teacher. Never reversed.
"""
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    MIN_TEACH_RATING, LessonPost, LessonPostPurchase, get_skill_rating,
)
from .serializers import LessonPostCreateSerializer, LessonPostSerializer
from .views import _Gate  # platform adult gate (defensive import lives there)


class PostListCreateView(APIView):
    """GET: browse posts you're allowed to see (visibility-filtered).
    POST: publish a recorded lesson (ADULTS ONLY + rating >= 6)."""

    def get_permissions(self):
        # Browsing is open to all authenticated users (minors included).
        # Publishing goes through the adult gate.
        return [IsAuthenticated()] if self.request.method == "GET" else [_Gate()]

    def get(self, request):
        qp = request.query_params
        qs = LessonPost.objects.filter(is_active=True).select_related("teacher")
        if qp.get("skill"):
            qs = qs.filter(skill__iexact=qp["skill"].strip())
        if qp.get("mine") in ("1", "true"):
            qs = qs.filter(teacher=request.user)
        rows = [p for p in qs[:300] if p.visible_to(request.user)]
        ser = LessonPostSerializer(rows, many=True, context={"request": request})
        return Response(ser.data)

    def post(self, request):
        data = request.data or {}
        skill = (data.get("skill") or "").strip().lower()
        rating = get_skill_rating(request.user, skill) if skill else 0
        if rating < MIN_TEACH_RATING:
            return Response(
                {"detail": f"You need a rating of {MIN_TEACH_RATING}+ in '{skill}' "
                           f"to post lessons (yours: {rating})."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ser = LessonPostCreateSerializer(data=data)
        ser.is_valid(raise_exception=True)
        post = ser.save(teacher=request.user, skill=skill, rating_snapshot=rating)
        out = LessonPostSerializer(post, context={"request": request})
        return Response(out.data, status=status.HTTP_201_CREATED)


class PostUnlockView(APIView):
    """POST /posts/<id>/unlock/ — pay the teacher's price, unlock the media.

    Minors allowed: recorded content, no contact channel. One-way payment.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        try:
            post = LessonPost.objects.select_related("teacher").get(pk=pk, is_active=True)
        except LessonPost.DoesNotExist:
            return Response({"detail": "Post not found."}, status=404)
        if not post.visible_to(request.user):
            return Response({"detail": "This lesson isn't available to you."}, status=403)
        if post.teacher_id == request.user.id:
            return Response({"detail": "You own this lesson."}, status=400)

        purchase, created = LessonPostPurchase.objects.get_or_create(
            post=post, student=request.user,
            defaults={"amount": post.price, "currency": post.currency},
        )
        if created:
            try:  # pragma: no cover - platform wallet hook
                from apps.common.wallet import charge as _charge

                ref = _charge(payer=request.user, payee=post.teacher,
                              amount=post.price, currency=post.currency,
                              memo=f"LessonZ post #{post.id}")
                purchase.settled = True
                purchase.external_ref = str(ref or "")
                purchase.save(update_fields=["settled", "external_ref"])
            except Exception:
                pass

        out = LessonPostSerializer(post, context={"request": request})
        return Response(out.data, status=200 if not created else 201)
