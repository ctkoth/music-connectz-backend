from django.db.models import Q
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import get_user_model
from .models import (
    PersonalityResult, UserVybeZPreferences, UserVybeZSubstances, Wallet
)

User = get_user_model()


def calculate_compatibility_score(user1, user2, user1_prefs, user1_substances):
    """Calculate compatibility score between two users based on PersonalitieZ, PreferencesZ, SubstancesZ.

    Returns score 0-100.
    """
    score = 0

    # Personality compatibility (MBTI type affinity)
    try:
        p1 = PersonalityResult.objects.filter(user=user1).latest("created_at")
        p2 = PersonalityResult.objects.filter(user=user2).latest("created_at")
        if p1 and p2:
            # Same type is 100, adjacent types ~75, opposite ~25
            if p1.mbti_type == p2.mbti_type:
                score += 25  # Perfect type match
            elif abs(ord(p1.mbti_type[0]) - ord(p2.mbti_type[0])) <= 1:
                score += 15  # Similar personalities
            else:
                score += 5   # Different but compatible
    except PersonalityResult.DoesNotExist:
        score += 10  # No personality data, give partial score

    # Preferences compatibility
    try:
        u2_prefs = UserVybeZPreferences.objects.get(user=user2)

        # Check gender interest
        if u2_prefs.gender_interested != "everyone":
            # Simplified: just check if they're open to the interaction type
            score += 15  # +15 for meeting gender preference
        else:
            score += 20  # +20 for "everyone" preference

        # Check relationship type alignment
        if user1_prefs.relationship_type == u2_prefs.relationship_type:
            score += 20  # Perfect relationship alignment
        elif user1_prefs.relationship_type == "both" or u2_prefs.relationship_type == "both":
            score += 15  # One is flexible
        else:
            score += 5   # Mismatched

        # Check long-term preference
        if user1_prefs.long_term == u2_prefs.long_term:
            score += 20  # Perfect alignment
        elif user1_prefs.long_term == "either" or u2_prefs.long_term == "either":
            score += 15  # One is flexible
        else:
            score += 5   # Mismatched expectations
    except UserVybeZPreferences.DoesNotExist:
        score += 10  # No preference data

    # Substances compatibility
    try:
        u2_substances = UserVybeZSubstances.objects.get(user=user2)
        substance_matches = 0

        # Simple matching: prefer users with same/similar substance choices
        if user1_substances.alcohol != "prefer_not" and u2_substances.alcohol != "prefer_not":
            if user1_substances.alcohol == u2_substances.alcohol:
                substance_matches += 1

        if user1_substances.cannabis != "prefer_not" and u2_substances.cannabis != "prefer_not":
            if user1_substances.cannabis == u2_substances.cannabis:
                substance_matches += 1

        if user1_substances.tobacco != "prefer_not" and u2_substances.tobacco != "prefer_not":
            if user1_substances.tobacco == u2_substances.tobacco:
                substance_matches += 1

        score += min(substance_matches * 5, 15)  # Up to +15 for substance alignment
    except UserVybeZSubstances.DoesNotExist:
        score += 5  # No substance data

    return min(score, 100)  # Cap at 100


class VybeZConnectzFunnelView(APIView):
    """GET: Find compatible matches based on PersonalitieZ, PreferencesZ, SubstancesZ.

    Returns a list of suggested matches with compatibility scores.
    Cost: Free for basic viewing, future premium features may apply."""

    def get(self, request):
        """Get compatible matches for the current user."""
        user = request.user
        if not user.is_authenticated:
            return Response({"error": "Not authenticated"}, status=401)

        # Get user's preferences and substances
        try:
            user_prefs = UserVybeZPreferences.objects.get(user=user)
        except UserVybeZPreferences.DoesNotExist:
            return Response({
                "error": "preferences_not_set",
                "message": "Please set your preferences first",
                "redirect_to": "preferencesz"
            }, status=400)

        try:
            user_substances = UserVybeZSubstances.objects.get(user=user)
        except UserVybeZSubstances.DoesNotExist:
            user_substances = None  # Substances are optional

        # Get all other users (limit to 20 for now)
        all_users = User.objects.exclude(id=user.id).filter(
            is_active=True
        ).order_by("?")[:50]

        # Calculate compatibility for each user
        matches = []
        for other_user in all_users:
            try:
                other_prefs = UserVybeZPreferences.objects.get(user=other_user)
            except UserVybeZPreferences.DoesNotExist:
                continue  # Skip users without preferences

            try:
                other_substances = UserVybeZSubstances.objects.get(user=other_user)
            except UserVybeZSubstances.DoesNotExist:
                other_substances = None

            score = calculate_compatibility_score(
                user, other_user, user_prefs,
                user_substances or UserVybeZSubstances(user=user)
            )

            # Only return matches with reasonable compatibility (>40%)
            if score >= 40:
                try:
                    latest_personality = PersonalityResult.objects.filter(
                        user=other_user
                    ).latest("created_at")
                    personality_type = latest_personality.mbti_type
                except PersonalityResult.DoesNotExist:
                    personality_type = None

                matches.append({
                    "id": other_user.id,
                    "username": other_user.username,
                    "personality": personality_type,
                    "relationship_seeking": other_prefs.relationship_type,
                    "commitment": other_prefs.long_term,
                    "compatibility_score": score,
                })

        # Sort by compatibility score (highest first)
        matches.sort(key=lambda x: x["compatibility_score"], reverse=True)
        matches = matches[:10]  # Limit to top 10

        return Response({
            "your_personality": self._get_user_personality(user),
            "your_preferences": {
                "gender_interested": user_prefs.gender_interested,
                "relationship_type": user_prefs.relationship_type,
                "long_term": user_prefs.long_term,
            },
            "matches": matches,
            "total_matches": len(matches),
        })

    def _get_user_personality(self, user):
        """Get user's latest personality result."""
        try:
            latest = PersonalityResult.objects.filter(user=user).latest("created_at")
            return latest.mbti_type
        except PersonalityResult.DoesNotExist:
            return None


class VybeZConnectzStatsView(APIView):
    """GET: View matching statistics and profile completion."""

    def get(self, request):
        """Get user's VybeZ ConnectZ profile stats."""
        user = request.user
        if not user.is_authenticated:
            return Response({"error": "Not authenticated"}, status=401)

        profile_complete = {
            "personality": False,
            "preferences": False,
            "substances": False,
        }

        try:
            PersonalityResult.objects.filter(user=user).latest("created_at")
            profile_complete["personality"] = True
        except PersonalityResult.DoesNotExist:
            pass

        try:
            UserVybeZPreferences.objects.get(user=user)
            profile_complete["preferences"] = True
        except UserVybeZPreferences.DoesNotExist:
            pass

        try:
            UserVybeZSubstances.objects.get(user=user)
            profile_complete["substances"] = True
        except UserVybeZSubstances.DoesNotExist:
            pass

        completion_pct = (sum(profile_complete.values()) / 3) * 100

        return Response({
            "profile_complete": profile_complete,
            "completion_percentage": int(completion_pct),
            "ready_for_matching": profile_complete["personality"] and profile_complete["preferences"],
        })
