from rest_framework import serializers

from .models import BarSet, Brief, Hook, Project, Reference, RhymeStack, Version


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ["id", "title", "kind", "genre", "mood", "body", "status",
                  "is_public", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class HookSerializer(serializers.ModelSerializer):
    class Meta:
        model = Hook
        fields = ["id", "project", "text", "vibe", "created_at"]
        read_only_fields = ["id", "created_at"]


class BarSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = BarSet
        fields = ["id", "project", "text", "scheme", "created_at"]
        read_only_fields = ["id", "created_at"]


class RhymeStackSerializer(serializers.ModelSerializer):
    class Meta:
        model = RhymeStack
        fields = ["id", "seed", "words", "created_at"]
        read_only_fields = ["id", "created_at"]


class ReferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reference
        fields = ["id", "title", "url", "note", "created_at"]
        read_only_fields = ["id", "created_at"]


class BriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brief
        fields = ["id", "client", "requirements", "status", "created_at"]
        read_only_fields = ["id", "created_at"]


class VersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Version
        fields = ["id", "project", "label", "snapshot", "created_at"]
        read_only_fields = ["id", "created_at"]
