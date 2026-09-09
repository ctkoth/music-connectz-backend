"""Daily habits — the daily return loop that converts trial to active."""
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Habit, UserPreferences


class HabitCreateView(APIView):
    """POST /api/economy/habits/ — create a new daily habit for onboarding."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Create a new habit for the user and save onboarding preferences."""
        data = request.data
        title = (data.get("title") or "").strip()
        app_key = (data.get("app_key") or "singz").strip()
        frequency = (data.get("frequency") or "daily").strip()

        if not title:
            return Response(
                {"detail": "Habit needs a title."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if frequency not in ["daily", "weekly"]:
            frequency = "daily"

        habit = Habit.objects.create(
            user=request.user,
            title=title,
            app_key=app_key,
            frequency=frequency,
        )

        # Save onboarding preferences if provided
        if data.get("notifications_enabled") is not None or data.get("language") or data.get("sound_enabled") is not None:
            prefs, _ = UserPreferences.objects.get_or_create(user=request.user)
            if data.get("notifications_enabled") is not None:
                prefs.notifications_enabled = data.get("notifications_enabled")
            if data.get("language"):
                prefs.language = data.get("language")
            if data.get("sound_enabled") is not None:
                prefs.sound_enabled = data.get("sound_enabled")
            prefs.save()

        return Response(
            {
                "id": habit.id,
                "title": habit.title,
                "frequency": habit.frequency,
                "app_key": habit.app_key,
                "created_at": habit.created_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )


class HabitCompleteView(APIView):
    """POST /api/economy/habits/{id}/complete/ — mark a habit as completed today."""
    permission_classes = [IsAuthenticated]

    def post(self, request, habit_id):
        """Mark a habit as completed today and return remaining energy."""
        try:
            habit = Habit.objects.get(id=habit_id, user=request.user)
        except Habit.DoesNotExist:
            return Response(
                {"detail": "Habit not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Mark as completed now
        habit.last_completed = timezone.now()
        habit.save()

        return Response(
            {
                "id": habit.id,
                "title": habit.title,
                "last_completed": habit.last_completed.isoformat(),
                "completed_today": True,
            },
            status=status.HTTP_200_OK,
        )
