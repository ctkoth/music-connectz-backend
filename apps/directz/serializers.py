from rest_framework import serializers

from .models import DirectZDraft


class DirectZDraftSerializer(serializers.ModelSerializer):
    class Meta:
        model = DirectZDraft
        fields = ("id", "focus", "drill_key", "title", "notes", "scene_count", "score", "created_at")
        read_only_fields = ("id", "created_at")
