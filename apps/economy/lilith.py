from django.db import transaction
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import get_user_model
from datetime import timedelta

from .models import LilithMission, LilithProgress, Wallet, Transaction as WalletTransaction

User = get_user_model()

# Mission journey stages and rewards
MISSION_STAGES = {
    "onboarding": {
        "name": "Welcome to Music ConnectZ",
        "days": (0, 7),
        "missions": [
            {
                "key": "complete_profile",
                "title": "Complete Your Profile",
                "description": "Let people know who you are. Add your top 3 skills and a bio.",
                "action": "profile_complete",
                "reward_spinaz": 50,
                "reward_energy": 25,
            },
            {
                "key": "message_new_user",
                "title": "Say Hi to a New Member",
                "description": "Message someone who joined this week. You might spark a collab.",
                "action": "message_new_user",
                "reward_spinaz": 100,
                "reward_energy": 50,
                "priority": True,
            },
            {
                "key": "rate_posts",
                "title": "Rate 3 Posts You Vibe With",
                "description": "Listening builds community. Rate some posts to help others improve.",
                "action": "rate_posts_count",
                "action_target": 3,
                "reward_spinaz": 75,
                "reward_energy": 30,
            },
            {
                "key": "take_boss_take",
                "title": "Submit a Boss Take",
                "description": "Record a vocal on a song. Let the AI coach help you improve.",
                "action": "submit_boss_take",
                "reward_spinaz": 150,
                "reward_energy": 75,
            },
        ]
    },
    "engagement": {
        "name": "Building Momentum",
        "days": (7, 30),
        "missions": [
            {
                "key": "message_new_users",
                "title": "Message 5 New Members This Week",
                "description": "Every new member is looking for their people. Help them find theirs.",
                "action": "message_new_users_weekly",
                "action_target": 5,
                "reward_spinaz": 200,
                "reward_energy": 100,
                "priority": True,
            },
            {
                "key": "detailed_comments",
                "title": "Leave 3 Detailed Comments",
                "description": "Help someone improve their craft. Real feedback moves people.",
                "action": "comment_with_substance",
                "action_target": 3,
                "reward_spinaz": 100,
                "reward_energy": 50,
            },
            {
                "key": "battle_entry",
                "title": "Enter Your First Battle",
                "description": "Test yourself against someone else. It's collaborative, not combative.",
                "action": "battle_entry",
                "reward_spinaz": 150,
                "reward_energy": 75,
            },
            {
                "key": "song_collab",
                "title": "Collaborate on a Song",
                "description": "Make something together. That's where the magic happens.",
                "action": "collab_complete",
                "reward_spinaz": 250,
                "reward_energy": 125,
                "priority": True,
            },
        ]
    },
    "active": {
        "name": "Community Builder",
        "days": (30, 365),
        "missions": [
            {
                "key": "mentor_role",
                "title": "Mentor a New Member to Their First Collab",
                "description": "Guide someone from signup to their first collaboration.",
                "action": "referred_user_collab",
                "reward_spinaz": 500,
                "reward_energy": 200,
                "priority": True,
            },
            {
                "key": "rate_10_posts",
                "title": "Rate 10 Posts This Week",
                "description": "Help the community find great work.",
                "action": "rate_posts_count",
                "action_target": 10,
                "reward_spinaz": 150,
                "reward_energy": 75,
            },
            {
                "key": "coach_others",
                "title": "Coach 3 Boss Takes",
                "description": "Share what you've learned. Help others improve.",
                "action": "coach_takes",
                "action_target": 3,
                "reward_spinaz": 200,
                "reward_energy": 100,
            },
        ]
    }
}

# Lilith's voice patterns
LILITH_VOICE = {
    "greeting_complete": "You did it. That matters. Keep going.",
    "greeting_in_progress": "You're working on something real. I believe in this.",
    "greeting_new": "There's something I think you're ready for.",
    "hint_message": "New members are waiting to meet you. You might be exactly who they need.",
    "hint_collab": "A collab is how you move from 'I make music' to 'we make music.'",
    "hint_rate": "Your honest thoughts help people improve. They're listening.",
    "hint_mentor": "You've learned enough to help someone else start. That's how communities grow.",
}

def get_mission_stage(user):
    """Determine user's current mission stage based on account age."""
    account_age = (timezone.now() - user.date_joined).days

    if account_age < 7:
        return "onboarding"
    elif account_age < 30:
        return "engagement"
    else:
        return "active"

def get_active_missions(user):
    """Get missions for user's current stage."""
    stage = get_mission_stage(user)
    stage_data = MISSION_STAGES[stage]

    missions = []
    for mission_def in stage_data["missions"]:
        mission = LilithMission.objects.filter(
            user=user,
            key=mission_def["key"]
        ).first()

        if not mission:
            mission = LilithMission.objects.create(
                user=user,
                key=mission_def["key"],
                stage=stage,
                title=mission_def["title"],
                description=mission_def["description"],
                action=mission_def["action"],
                action_target=mission_def.get("action_target", 1),
                reward_spinaz=mission_def["reward_spinaz"],
                reward_energy=mission_def["reward_energy"],
                is_priority=mission_def.get("priority", False),
            )

        missions.append(mission)

    return missions

def check_mission_completion(user, action_key, count=1):
    """Check and award completed missions based on user action."""
    missions = LilithMission.objects.filter(
        user=user,
        action=action_key,
        completed_at__isnull=True
    )

    for mission in missions:
        progress = LilithProgress.objects.filter(mission=mission).first()
        if not progress:
            progress = LilithProgress.objects.create(mission=mission, progress=0)

        progress.progress = min(progress.progress + count, mission.action_target)
        progress.save()

        if progress.progress >= mission.action_target:
            award_mission(user, mission)

def award_mission(user, mission):
    """Award mission rewards and mark as complete."""
    mission.completed_at = timezone.now()
    mission.save()

    wallet = Wallet.objects.get(user=user)

    # Award SpinaZ
    if mission.reward_spinaz > 0:
        wallet.spinaz += mission.reward_spinaz
        WalletTransaction.objects.create(
            user=user,
            kind="lilith_spinaz",
            amount_spinaz=mission.reward_spinaz,
            note=f"Lilith mission: {mission.title}",
        )

    # Award Energy
    if mission.reward_energy > 0:
        wallet.energy += mission.reward_energy
        WalletTransaction.objects.create(
            user=user,
            kind="lilith_energy",
            amount_energy=mission.reward_energy,
            note=f"Lilith mission: {mission.title}",
        )

    wallet.save()

class LilithMissionsView(APIView):
    """GET: Retrieve active missions for user with progress.

    Returns personalized missions based on user's journey stage
    (onboarding → engagement → active community member).
    Free — no cost to view or complete."""

    def get(self, request):
        """Get active missions and progress for current user."""
        user = request.user
        if not user.is_authenticated:
            return Response({"error": "Not authenticated"}, status=401)

        stage = get_mission_stage(user)
        missions_list = get_active_missions(user)

        missions_data = []
        for mission in missions_list:
            progress = LilithProgress.objects.filter(mission=mission).first()
            progress_count = progress.progress if progress else 0

            missions_data.append({
                "id": mission.id,
                "key": mission.key,
                "title": mission.title,
                "description": mission.description,
                "action": mission.action,
                "action_target": mission.action_target,
                "progress": progress_count,
                "completed": mission.completed_at is not None,
                "is_priority": mission.is_priority,
                "reward_spinaz": mission.reward_spinaz,
                "reward_energy": mission.reward_energy,
            })

        # Greeting message from Lilith
        completed_count = sum(1 for m in missions_list if m.completed_at)
        if completed_count == 0:
            greeting = LILITH_VOICE["greeting_new"]
        elif completed_count < len(missions_list) // 2:
            greeting = LILITH_VOICE["greeting_in_progress"]
        else:
            greeting = LILITH_VOICE["greeting_complete"]

        return Response({
            "stage": stage,
            "stage_name": MISSION_STAGES[stage]["name"],
            "greeting": greeting,
            "missions": missions_data,
            "completed_count": completed_count,
            "total_count": len(missions_list),
        })
