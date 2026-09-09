"""Daily habits — the daily return loop that converts trial to active."""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Habit


class HabitCreateView(APIView):
    """POST /api/economy/habits/ — create a new daily habit for onboarding."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Create a new habit for the user."""
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
