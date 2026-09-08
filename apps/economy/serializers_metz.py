from rest_framework import serializers
from .models import PracticeSession, DrumPattern, ToolPreference, PatternShare, DrillTake


class PracticeSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PracticeSession
        fields = ["id", "kind", "duration_seconds", "bpm", "notes", "created_at"]
        read_only_fields = ["id", "created_at"]


class DrumPatternSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = DrumPattern
        fields = [
            "id",
            "name",
            "kit_name",
            "bpm",
            "pattern_length",
            "pattern_data",
            "is_public",
            "shares_count",
            "owner_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "shares_count", "created_at", "updated_at"]


class ToolPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ToolPreference
        fields = ["metz_settings", "tunerz_settings", "chordz_settings", "drumz_settings"]


class PatternShareSerializer(serializers.ModelSerializer):
    sharer_name = serializers.CharField(source="shared_by.username", read_only=True)
    pattern_name = serializers.CharField(source="pattern.name", read_only=True)

    class Meta:
        model = PatternShare
        fields = ["id", "pattern", "pattern_name", "sharer_name", "created_at"]
        read_only_fields = ["id", "created_at"]


class DrillTakeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DrillTake
        fields = [
            "id",
            "weak_note",
            "original_frequency",
            "original_cents_off",
            "accuracy_percent",
            "duration_seconds",
            "final_frequency",
            "final_cents_off",
            "improvement",
            "key_context",
            "bpm_context",
            "created_at",
        ]
        read_only_fields = ["id", "improvement", "created_at"]
