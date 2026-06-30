from rest_framework import serializers

from .models import Badge, Drill, EarnedBadge, TrainingProfile


class DrillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Drill
        fields = ("key", "title", "description", "category", "xp", "icon", "order")


class BadgeSerializer(serializers.ModelSerializer):
    earned = serializers.SerializerMethodField()

    class Meta:
        model = Badge
        fields = ("code", "name", "description", "icon", "rule", "threshold", "earned")

    def get_earned(self, obj):
        earned_codes = self.context.get("earned_codes", set())
        return obj.code in earned_codes


class TrainingProfileSerializer(serializers.ModelSerializer):
    level = serializers.IntegerField(read_only=True)
    xp_into_level = serializers.IntegerField(read_only=True)
    xp_to_next_level = serializers.IntegerField(read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    badges = serializers.SerializerMethodField()

    class Meta:
        model = TrainingProfile
        fields = (
            "app_key",
            "username",
            "xp",
            "level",
            "xp_into_level",
            "xp_to_next_level",
            "current_streak",
            "longest_streak",
            "drills_completed",
            "last_active",
            "badges",
        )

    def get_badges(self, obj):
        return [
            {
                "code": eb.badge.code,
                "name": eb.badge.name,
                "icon": eb.badge.icon,
                "earned_at": eb.earned_at,
            }
            for eb in obj.earned_badges.select_related("badge").all()
        ]


class LeaderboardEntrySerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    level = serializers.IntegerField(read_only=True)

    class Meta:
        model = TrainingProfile
        fields = ("username", "xp", "level", "current_streak", "longest_streak")
