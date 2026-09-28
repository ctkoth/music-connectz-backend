"""LessonZ: Lesson marketplace for coaches and students.

Path 3 of monetization — lesson marketplace. Coaches set per-minute rates and
students book lessons via Call. Ratings come from student reviews after the
lesson is complete. Verification counts actual completed lessons.

Three affordances:

  * `CoachProfile.average_rating` is computed on read from CoachReview rows,
    so a disputed review never orphans a cached number.
  * `verified_lesson_count` is incremented ONCE per Call that reaches
    STATUS_ENDED, not re-counted from CallZ rows on every read.
  * `featured_until` is a nullable timestamp — a coach with no students
    never touches the featured list, and a featured window that has passed
    is instantly cleared on next read.
"""
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Count, Avg, Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes

from .models import CoachProfile, CoachReview, Call, Wallet

User = get_user_model()


class CoachProfileView(APIView):
    """GET /api/economy/lessonz/profile/ — coach's profile.
    PATCH /api/economy/lessonz/profile/ — update coach profile.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get coach profile: rate, bio, verification, reviews."""
        try:
            coach_profile = request.user.coach_profile
        except CoachProfile.DoesNotExist:
            return Response(
                {"detail": "User is not a coach"},
                status=status.HTTP_404_NOT_FOUND
            )

        reviews = CoachReview.objects.filter(coach=request.user)
        avg_rating = None
        if reviews.exists():
            avg_rating = sum(r.rating for r in reviews) / reviews.count()

        return Response({
            "coach_id": request.user.id,
            "lesson_rate_cents_per_min": coach_profile.lesson_rate_cents_per_min,
            "bio": coach_profile.bio,
            "verified_lesson_count": coach_profile.verified_lesson_count,
            "average_rating": avg_rating,
            "review_count": reviews.count(),
            "featured_until": coach_profile.featured_until,
            "created_at": coach_profile.created_at,
        })

    def patch(self, request):
        """Update coach profile: rate, bio."""
        try:
            coach_profile = request.user.coach_profile
        except CoachProfile.DoesNotExist:
            # First time accessing LessonZ, auto-create profile
            coach_profile = CoachProfile.objects.create(user=request.user)

        # Update mutable fields
        if "lesson_rate_cents_per_min" in request.data:
            rate = request.data["lesson_rate_cents_per_min"]
            if isinstance(rate, int) and rate > 0:
                coach_profile.lesson_rate_cents_per_min = rate
            else:
                return Response(
                    {"lesson_rate_cents_per_min": "Must be a positive integer"},
                    status=status.HTTP_400_BAD_REQUEST
                )

        if "bio" in request.data:
            coach_profile.bio = request.data["bio"][:500]  # max_length check

        coach_profile.save()

        reviews = CoachReview.objects.filter(coach=request.user)
        avg_rating = None
        if reviews.exists():
            avg_rating = sum(r.rating for r in reviews) / reviews.count()

        return Response({
            "coach_id": request.user.id,
            "lesson_rate_cents_per_min": coach_profile.lesson_rate_cents_per_min,
            "bio": coach_profile.bio,
            "verified_lesson_count": coach_profile.verified_lesson_count,
            "average_rating": avg_rating,
            "review_count": reviews.count(),
            "featured_until": coach_profile.featured_until,
            "updated_at": coach_profile.updated_at,
        })


class CoachReviewsView(APIView):
    """GET /api/economy/lessonz/coach/<coach_id>/reviews/ — list coach reviews."""
    permission_classes = [AllowAny]

    def get(self, request, coach_id):
        """Get all reviews for a coach."""
        try:
            coach = User.objects.get(id=coach_id)
        except User.DoesNotExist:
            return Response(
                {"detail": "Coach not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        reviews = CoachReview.objects.filter(coach=coach).select_related("student")
        avg_rating = None
        if reviews.exists():
            avg_rating = sum(r.rating for r in reviews) / reviews.count()

        return Response({
            "coach_id": coach_id,
            "coach": coach.username,
            "review_count": reviews.count(),
            "average_rating": avg_rating,
            "reviews": [
                {
                    "id": r.id,
                    "student_id": r.student_id,
                    "student": r.student.username,
                    "rating": r.rating,
                    "text": r.text,
                    "created_at": r.created_at,
                }
                for r in reviews
            ]
        })


class StudentReviewView(APIView):
    """POST /api/economy/lessonz/review/ — post a review of a coach after lesson."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Create or update a review of a coach.

        Body: {
            "coach_id": <int>,
            "rating": <1-5>,
            "text": "<string>"
        }

        Only students can review coaches they've had a lesson with (verified via
        Call history). One review per (student, coach) pair; re-posting replaces it.
        """
        coach_id = request.data.get("coach_id")
        rating = request.data.get("rating")
        text = request.data.get("text", "")

        if not coach_id:
            return Response(
                {"coach_id": "Required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not rating or not isinstance(rating, int) or rating < 1 or rating > 5:
            return Response(
                {"rating": "Must be an integer from 1 to 5"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            coach = User.objects.get(id=coach_id)
        except User.DoesNotExist:
            return Response(
                {"detail": "Coach not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Verify student had a lesson with this coach (Call exists)
        lesson_exists = Call.objects.filter(
            caller=request.user,
            callee=coach,
            status=Call.STATUS_ENDED
        ).exists()

        if not lesson_exists:
            return Response(
                {"detail": "No completed lesson found with this coach"},
                status=status.HTTP_403_FORBIDDEN
            )

        # Create or update review
        review, created = CoachReview.objects.update_or_create(
            coach=coach,
            student=request.user,
            defaults={"rating": rating, "text": text[:500]}  # max_length check
        )

        return Response({
            "id": review.id,
            "coach_id": coach_id,
            "student_id": request.user.id,
            "rating": review.rating,
            "text": review.text,
            "created_at": review.created_at,
            "updated_at": review.updated_at,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([AllowAny])
def coaches_list_view(request):
    """GET /api/economy/lessonz/coaches/ — list coaches by rating and verification.

    Query params:
      - sort: "rating" (default), "lessons", "recent"
      - featured: true/false (featured_until > now)
    """
    sort = request.query_params.get("sort", "rating")
    featured_only = request.query_params.get("featured", "").lower() == "true"

    coaches = CoachProfile.objects.select_related("user").filter(
        verified_lesson_count__gt=0  # Only show coaches with at least one lesson
    )

    if featured_only:
        coaches = coaches.filter(featured_until__gt=timezone.now())

    # Sort
    if sort == "lessons":
        coaches = coaches.order_by("-verified_lesson_count")
    elif sort == "recent":
        coaches = coaches.order_by("-updated_at")
    else:  # "rating"
        # Sort by review count (as proxy for rating quality), then by recent
        coaches = coaches.annotate(
            review_count=Count("user__coach_reviews")
        ).order_by("-review_count", "-updated_at")

    data = []
    for coach_profile in coaches:
        reviews = CoachReview.objects.filter(coach=coach_profile.user)
        avg_rating = None
        if reviews.exists():
            avg_rating = sum(r.rating for r in reviews) / reviews.count()

        data.append({
            "coach_id": coach_profile.user_id,
            "coach": coach_profile.user.username,
            "lesson_rate_cents_per_min": coach_profile.lesson_rate_cents_per_min,
            "bio": coach_profile.bio,
            "verified_lesson_count": coach_profile.verified_lesson_count,
            "average_rating": avg_rating,
            "review_count": reviews.count(),
            "featured_until": coach_profile.featured_until,
        })

    return Response({"coaches": data})
