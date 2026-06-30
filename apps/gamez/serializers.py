from rest_framework import serializers

from .models import Game, OCCMedia


class GameSerializer(serializers.ModelSerializer):
    class Meta:
        model = Game
        fields = ["id", "title", "description", "genre", "subgenre", "engine", "status",
                  "occ_project_ref", "auto_mode", "tier_at_creation", "exported",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "tier_at_creation", "exported", "created_at", "updated_at"]


class OCCMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = OCCMedia
        fields = ["id", "game", "kind", "url", "source", "routed_to", "intelligence_ref", "created_at"]
        read_only_fields = ["id", "source", "routed_to", "intelligence_ref", "created_at"]
