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
from decimal import Decimal

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    MIN_TEACH_RATING, VISIBILITY_CHOICES, LessonPost, LessonPostPurchase,
    get_skill_rating,
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
        # ?mine=1 needs to include UNPUBLISHED posts too — previously the
        # is_active=True filter ran BEFORE the mine filter, so a teacher who
        # unpublished their own post lost all visibility of it, including
        # the one place (their own "mine" list) they'd need in order to
        # publish it again. `visible_to()` already lets the teacher see
        # their own regardless of is_active; the queryset just never gave
        # it the chance to.
        mine = qp.get("mine") in ("1", "true")
        qs = LessonPost.objects.select_related("teacher")
        if mine:
            qs = qs.filter(teacher=request.user)
        else:
            qs = qs.filter(is_active=True)
        if qp.get("skill"):
            qs = qs.filter(skill__iexact=qp["skill"].strip())
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


class PostDetailView(APIView):
    """PATCH: fix a typo'd title/price/description/visibility instead of
    taking the post down and reposting. `media_ref`/`preview_ref` can be
    swapped too (a re-upload). `skill` is locked for the same reason as
    LessonOffer's: the rating snapshot was checked for this skill.

    DELETE: unpublish, never a hard delete. `LessonPostPurchase.post` is
    CASCADE — hard-deleting a post a student already paid to unlock would
    wipe their purchase record along with it.
    """

    permission_classes = [_Gate]

    def _mine(self, request, pk):
        try:
            return LessonPost.objects.get(pk=pk, teacher=request.user)
        except LessonPost.DoesNotExist:
            return None

    def patch(self, request, pk):
        post = self._mine(request, pk)
        if not post:
            return Response({"detail": "Not yours, or not here."}, status=status.HTTP_404_NOT_FOUND)

        d = request.data or {}
        if "skill" in d and str(d["skill"]).strip().lower() != post.skill:
            return Response(
                {"detail": "Can't change what skill this teaches — your rating was checked "
                            "for this one."},
                status=status.HTTP_409_CONFLICT,
            )

        fields = []
        if "title" in d:
            title = str(d["title"]).strip()
            if not title:
                return Response({"detail": "Title is required."}, status=status.HTTP_400_BAD_REQUEST)
            if len(title) > 140:
                return Response({"detail": "Title must be 140 characters or less."},
                                status=status.HTTP_400_BAD_REQUEST)
            post.title = title
            fields.append("title")
        if "description" in d:
            post.description = str(d["description"] or "")
            fields.append("description")
        if "media_ref" in d:
            media_ref = str(d["media_ref"] or "").strip()
            if not media_ref:
                return Response({"detail": "Media ref (upload id) is required."},
                                status=status.HTTP_400_BAD_REQUEST)
            post.media_ref = media_ref
            fields.append("media_ref")
        if "preview_ref" in d:
            post.preview_ref = str(d["preview_ref"] or "")
            fields.append("preview_ref")
        if "price" in d:
            try:
                price = Decimal(str(d["price"]))
            except Exception:
                return Response({"detail": "price must be a number."}, status=status.HTTP_400_BAD_REQUEST)
            if price <= Decimal("0"):
                return Response({"detail": "Price must be greater than $0."}, status=status.HTTP_400_BAD_REQUEST)
            post.price = price
            fields.append("price")
        if "currency" in d:
            post.currency = str(d["currency"] or "USD")[:8]
            fields.append("currency")
        if "visibility" in d and d["visibility"] in dict(VISIBILITY_CHOICES):
            post.visibility = d["visibility"]
            fields.append("visibility")
        if "is_active" in d:
            post.is_active = bool(d["is_active"])
            fields.append("is_active")

        if not fields:
            return Response({"detail": "Nothing to change."}, status=status.HTTP_400_BAD_REQUEST)
        post.save(update_fields=fields)
        return Response(LessonPostSerializer(post, context={"request": request}).data)

    def delete(self, request, pk):
        post = self._mine(request, pk)
        if not post:
            return Response({"detail": "Not yours, or not here."}, status=status.HTTP_404_NOT_FOUND)
        if not post.is_active:
            return Response({"detail": "Already unpublished."}, status=status.HTTP_400_BAD_REQUEST)
        post.is_active = False
        post.save(update_fields=["is_active"])
        return Response(LessonPostSerializer(post, context={"request": request}).data)
