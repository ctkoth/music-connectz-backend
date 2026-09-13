from django.db import transaction
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import UserSubstances


SUBSTANCE_OPTIONS = {
    "alcohol": [
        {"text": "Don't use", "value": "none", "emoji": "🚫"},
        {"text": "Occasionally", "value": "occasionally", "emoji": "🍺"},
        {"text": "Regularly", "value": "regularly", "emoji": "🍷"},
        {"text": "Prefer not to say", "value": "prefer_not", "emoji": "🤐"},
    ],
    "cannabis": [
        {"text": "Don't use", "value": "none", "emoji": "🚫"},
        {"text": "Occasionally", "value": "occasionally", "emoji": "🌿"},
        {"text": "Regularly", "value": "regularly", "emoji": "🍃"},
        {"text": "Prefer not to say", "value": "prefer_not", "emoji": "🤐"},
    ],
    "tobacco": [
        {"text": "Don't use", "value": "none", "emoji": "🚫"},
        {"text": "Occasionally", "value": "occasionally", "emoji": "🚬"},
        {"text": "Regularly", "value": "regularly", "emoji": "☁️"},
        {"text": "Prefer not to say", "value": "prefer_not", "emoji": "🤐"},
    ],
    "psychedelics": [
        {"text": "Never tried", "value": "never", "emoji": "🚫"},
        {"text": "Tried before", "value": "tried", "emoji": "🌌"},
        {"text": "Open to trying", "value": "open", "emoji": "🔮"},
        {"text": "Prefer not to say", "value": "prefer_not", "emoji": "🤐"},
    ],
}


class SubstancesZView(APIView):
    """GET: Retrieve substance use options and user's current selections
       POST: Update user substance preferences
       Free (no cost) — for personal use and matching filters"""

    def get(self, request):
        """Get substance options and user's current selections."""
        user = request.user
        if not user.is_authenticated:
            return Response({"error": "Not authenticated"}, status=401)

        substances = UserSubstances.objects.filter(user=user).first()
        current_substances = {}
        if substances:
            current_substances = {
                "alcohol": substances.alcohol,
                "cannabis": substances.cannabis,
                "tobacco": substances.tobacco,
                "psychedelics": substances.psychedelics,
            }

        return Response({
            "options": SUBSTANCE_OPTIONS,
            "current": current_substances,
            "description": "Substance use preferences for compatible matching (private)"
        })

    @transaction.atomic
    def post(self, request):
        """Update user substance preferences."""
        user = request.user
        if not user.is_authenticated:
            return Response({"error": "Not authenticated"}, status=401)

        alcohol = request.data.get("alcohol")
        cannabis = request.data.get("cannabis")
        tobacco = request.data.get("tobacco")
        psychedelics = request.data.get("psychedelics")

        # Validate all selections
        valid_alcohol = [opt["value"] for opt in SUBSTANCE_OPTIONS["alcohol"]]
        valid_cannabis = [opt["value"] for opt in SUBSTANCE_OPTIONS["cannabis"]]
        valid_tobacco = [opt["value"] for opt in SUBSTANCE_OPTIONS["tobacco"]]
        valid_psychedelics = [opt["value"] for opt in SUBSTANCE_OPTIONS["psychedelics"]]

        if alcohol and alcohol not in valid_alcohol:
            return Response({"error": "Invalid alcohol preference"}, status=400)
        if cannabis and cannabis not in valid_cannabis:
            return Response({"error": "Invalid cannabis preference"}, status=400)
        if tobacco and tobacco not in valid_tobacco:
            return Response({"error": "Invalid tobacco preference"}, status=400)
        if psychedelics and psychedelics not in valid_psychedelics:
            return Response({"error": "Invalid psychedelics preference"}, status=400)

        # Update or create substance record
        substances, created = UserSubstances.objects.get_or_create(user=user)
        if alcohol:
            substances.alcohol = alcohol
        if cannabis:
            substances.cannabis = cannabis
        if tobacco:
            substances.tobacco = tobacco
        if psychedelics:
            substances.psychedelics = psychedelics
        substances.save()

        return Response({
            "success": True,
            "substances": {
                "alcohol": substances.alcohol,
                "cannabis": substances.cannabis,
                "tobacco": substances.tobacco,
                "psychedelics": substances.psychedelics,
            }
        })
