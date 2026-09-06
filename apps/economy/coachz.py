"""CoachZ: Teaching studio for voice coaches to rate student takes."""
from django.utils import timezone
from django.db.models import Count, Avg, Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    CoachProfile, StudentRelationship, TakeRating, Post, Transaction, User
)


class CoachStudioView(APIView):
    """GET /api/economy/coachz/studio/ — coach's dashboard."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get coach studio info: students, takes, portfolio."""
        try:
            coach_profile = request.user.coach_profile
        except CoachProfile.DoesNotExist:
            # First time accessing CoachZ, auto-create profile
            coach_profile = CoachProfile.objects.create(user=request.user)

        # Get all students
        students = StudentRelationship.objects.filter(
            coach=request.user
        ).select_related("student").order_by("-joined_at")

        # Get all rated takes
        rated_takes = TakeRating.objects.filter(
            coach=request.user
        ).select_related("take").order_by("-created_at")[:50]

        # Calculate stats
        today = timezone.localdate()
        takes_rated_today = TakeRating.objects.filter(
            coach=request.user,
            created_at__date=today
        ).count()

        return Response({
            "coach": {
                "user_id": request.user.id,
                "name": request.user.profile.display_name or request.user.username,
                "bio": coach_profile.bio,
                "students_count": coach_profile.students_count,
                "takes_rated": coach_profile.takes_rated,
                "referral_spinaz_earned": coach_profile.referral_spinaz_earned,
            },
            "students": [
                {
                    "id": rel.student.id,
                    "name": rel.student.profile.display_name or rel.student.username,
                    "joined_at": rel.joined_at,
                    "takes_submitted": rel.takes_submitted,
                    "takes_rated": rel.takes_rated,
                }
                for rel in students
            ],
            "activity": {
                "takes_rated_today": takes_rated_today,
                "total_takes_rated": coach_profile.takes_rated,
                "recent_ratings": [
                    {
                        "take_id": tr.take_id,
                        "student_id": tr.take.user_id,
                        "pitch": tr.pitch_accuracy,
                        "timing": tr.timing_accuracy,
                        "tone": tr.tone_quality,
                        "notes": tr.notes,
                        "created_at": tr.created_at,
                    }
                    for tr in rated_takes
                ]
            }
        })

    def patch(self, request):
        """PATCH /api/economy/coachz/studio/ — update coach profile."""
        coach_profile = request.user.coach_profile

        if "bio" in request.data:
            coach_profile.bio = str(request.data["bio"])[:500]

        if "specializations" in request.data:
            specs = request.data.get("specializations", [])
            coach_profile.specializations = [str(s)[:100] for s in specs[:10]]

        coach_profile.save(update_fields=["bio", "specializations"])

        return Response({"updated": True})


class RateStudentTakeView(APIView):
    """POST /api/economy/coachz/rate/ — coach rates a student take."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Rate a student take with dimensions (pitch, timing, tone).

        Request:
        {
            "take_id": 123,
            "pitch_accuracy": 85,
            "timing_accuracy": 90,
            "tone_quality": 88,
            "notes": "Great breath control on the bridge!"
        }
        """
        take_id = request.data.get("take_id")
        pitch = request.data.get("pitch_accuracy")
        timing = request.data.get("timing_accuracy")
        tone = request.data.get("tone_quality")
        notes = request.data.get("notes", "")[:1000]

        # Get the take
        try:
            take = Post.objects.get(id=take_id)
        except Post.DoesNotExist:
            return Response(
                {"detail": "Take not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Verify coach-student relationship
        if not StudentRelationship.objects.filter(
            coach=request.user, student=take.user
        ).exists():
            return Response(
                {"detail": "Not coaching this student"},
                status=status.HTTP_403_FORBIDDEN
            )

        # Create or update rating
        rating, created = TakeRating.objects.get_or_create(
            coach=request.user,
            take=take,
            defaults={
                "pitch_accuracy": pitch,
                "timing_accuracy": timing,
                "tone_quality": tone,
                "notes": notes,
            }
        )

        if not created:
            # Update existing rating
            rating.pitch_accuracy = pitch
            rating.timing_accuracy = timing
            rating.tone_quality = tone
            rating.notes = notes
            rating.save()

        # Update student relationship
        rel = StudentRelationship.objects.get(coach=request.user, student=take.user)
        rel.takes_rated += 1
        rel.save(update_fields=["takes_rated"])

        # Update coach profile
        coach_profile = request.user.coach_profile
        coach_profile.takes_rated = TakeRating.objects.filter(
            coach=request.user
        ).count()
        coach_profile.save(update_fields=["takes_rated"])

        # Award coach 🍥 spinaz for rating
        Transaction.objects.create(
            user=request.user,
            kind=Transaction.KIND_EARN,
            resource=Transaction.RES_SPINAZ,
            amount=5,
            note=f"Rated student take: {take.title or 'Untitled'}"
        )

        return Response({
            "rating_id": rating.id,
            "created": created,
            "reward": {
                "spinaz": 5,
                "note": "💯 Thanks for coaching!"
            }
        }, status=status.HTTP_201_CREATED)


class AddStudentView(APIView):
    """POST /api/economy/coachz/add-student/ — invite a student to coach."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Add a student to your coaching studio.

        Request:
        {
            "student_id": 456,
            "referral_code": "coach_abc123"  # optional
        }
        """
        student_id = request.data.get("student_id")

        # Get the student
        try:
            student = User.objects.get(id=student_id)
        except User.DoesNotExist:
            return Response(
                {"detail": "Student not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check if already coaching
        rel, created = StudentRelationship.objects.get_or_create(
            student=student,
            coach=request.user,
        )

        if not created:
            return Response(
                {"detail": "Already coaching this student"},
                status=status.HTTP_409_CONFLICT
            )

        # Update counts
        coach_profile = request.user.coach_profile
        coach_profile.students_count += 1
        coach_profile.save(update_fields=["students_count"])

        # Award referral bonus 🍥
        bonus_spinaz = 50
        Transaction.objects.create(
            user=request.user,
            kind=Transaction.KIND_EARN,
            resource=Transaction.RES_SPINAZ,
            amount=bonus_spinaz,
            note=f"New student: {student.username}"
        )

        coach_profile.referral_spinaz_earned += bonus_spinaz
        coach_profile.save(update_fields=["referral_spinaz_earned"])

        return Response({
            "relationship_id": rel.id,
            "student_id": student.id,
            "reward": {
                "spinaz": bonus_spinaz,
                "note": "🎁 New student joined your studio!"
            }
        }, status=status.HTTP_201_CREATED)
