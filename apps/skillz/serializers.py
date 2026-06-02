from rest_framework import serializers

from .models import Attempt, Drill, SkillProgress, SkillTrack
from .utils import level_for_xp


class DrillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Drill
        fields = ["id", "track", "title", "prompt", "kind", "difficulty", "xp_reward", "order"]


class TrackSerializer(serializers.ModelSerializer):
    drill_count = serializers.IntegerField(source="drillz.count", read_only=True)
    # progress fields injected by the view (per requesting user)
    level = serializers.SerializerMethodField()
    total_xp = serializers.SerializerMethodField()
    xp_into_level = serializers.SerializerMethodField()
    xp_to_next = serializers.SerializerMethodField()
    streak_days = serializers.SerializerMethodField()

    class Meta:
        model = SkillTrack
        fields = ["id", "app_key", "key", "title", "persona_skill", "description",
                  "emoji", "color", "order", "drill_count",
                  "level", "total_xp", "xp_into_level", "xp_to_next", "streak_days"]

    def _prog(self, obj):
        return (self.context.get("progress_map") or {}).get(obj.id)

    def get_total_xp(self, obj):
        p = self._prog(obj); return p.total_xp if p else 0

    def get_level(self, obj):
        return level_for_xp(self.get_total_xp(obj))[0]

    def get_xp_into_level(self, obj):
        return level_for_xp(self.get_total_xp(obj))[1]

    def get_xp_to_next(self, obj):
        return level_for_xp(self.get_total_xp(obj))[2]

    def get_streak_days(self, obj):
        p = self._prog(obj); return p.streak_days if p else 0


class AttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attempt
        fields = ["id", "drill", "score", "xp_earned", "passed", "created_at"]
        read_only_fields = ["id", "xp_earned", "passed", "created_at"]
