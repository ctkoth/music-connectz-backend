from django.db import transaction
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import UserPreferences, Wallet


PREFERENCE_OPTIONS = {
    "gender_interested": [
        {"text": "Men", "value": "men", "emoji": "👨"},
        {"text": "Women", "value": "women", "emoji": "👩"},
        {"text": "Non-binary", "value": "non_binary", "emoji": "🌈"},
        {"text": "Everyone", "value": "everyone", "emoji": "💫"},
    ],
    "relationship_type": [
        {"text": "Collaborations only", "value": "collabs", "emoji": "🎵"},
        {"text": "Dating / Romance", "value": "dating", "emoji": "💕"},
        {"text": "Both", "value": "both", "emoji": "🎭"},
    ],
    "long_term": [
        {"text": "Short-term / casual", "value": "short", "emoji": "🌪️"},
        {"text": "Long-term", "value": "long", "emoji": "🏠"},
        {"text": "Either", "value": "either", "emoji": "🔄"},
    ],
}


class PreferencesZView(APIView):
    """GET: Retrieve preference options and user's current preferences
       POST: Update user preferences
       Free (no cost)"""

    def get(self, request):
        """Get preference options and user's current preferences."""
        user = request.user
        if not user.is_authenticated:
            return Response({"error": "Not authenticated"}, status=401)

        prefs = UserPreferences.objects.filter(user=user).first()
        current_prefs = {}
        if prefs:
            current_prefs = {
                "gender_interested": prefs.gender_interested,
                "relationship_type": prefs.relationship_type,
                "long_term": prefs.long_term,
            }

        return Response({
            "options": PREFERENCE_OPTIONS,
            "current": current_prefs,
            "description": "Set your preferences for matching on VybeZ ConnectZ"
        })

    @transaction.atomic
    def post(self, request):
        """Update user preferences."""
        user = request.user
        if not user.is_authenticated:
            return Response({"error": "Not authenticated"}, status=401)

        gender_interested = request.data.get("gender_interested")
        relationship_type = request.data.get("relationship_type")
        long_term = request.data.get("long_term")

        # Validate selections
        if gender_interested and gender_interested not in [opt["value"] for opt in PREFERENCE_OPTIONS["gender_interested"]]:
            return Response({"error": "Invalid gender preference"}, status=400)
        if relationship_type and relationship_type not in [opt["value"] for opt in PREFERENCE_OPTIONS["relationship_type"]]:
            return Response({"error": "Invalid relationship type"}, status=400)
        if long_term and long_term not in [opt["value"] for opt in PREFERENCE_OPTIONS["long_term"]]:
            return Response({"error": "Invalid long-term preference"}, status=400)

        # Update or create preferences
        prefs, created = UserPreferences.objects.get_or_create(user=user)
        if gender_interested:
            prefs.gender_interested = gender_interested
        if relationship_type:
            prefs.relationship_type = relationship_type
        if long_term:
            prefs.long_term = long_term
        prefs.save()

        return Response({
            "success": True,
            "preferences": {
                "gender_interested": prefs.gender_interested,
                "relationship_type": prefs.relationship_type,
                "long_term": prefs.long_term,
            }
        })
