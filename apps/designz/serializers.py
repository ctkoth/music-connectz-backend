from rest_framework import serializers

from .models import Asset, BrandKit, Comment, Palette, Project, Template, Version


class ProjectSerializer(serializers.ModelSerializer):
    asset_count = serializers.IntegerField(source="assetz.count", read_only=True)

    class Meta:
        model = Project
        fields = ["id", "title", "description", "status", "width", "height",
                  "cover_url", "canvas", "is_public", "asset_count",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "asset_count", "created_at", "updated_at"]


class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = ["id", "project", "name", "file_url", "kind", "size_bytes", "created_at"]
        read_only_fields = ["id", "created_at"]


class TemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Template
        fields = ["id", "title", "category", "thumbnail_url", "data", "is_public", "created_at"]
        read_only_fields = ["id", "created_at"]


class BrandKitSerializer(serializers.ModelSerializer):
    class Meta:
        model = BrandKit
        fields = ["id", "name", "colors", "fonts", "logo_url", "created_at"]
        read_only_fields = ["id", "created_at"]


class PaletteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Palette
        fields = ["id", "name", "colors", "created_at"]
        read_only_fields = ["id", "created_at"]


class CommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comment
        fields = ["id", "project", "body", "created_at"]
        read_only_fields = ["id", "created_at"]


class VersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Version
        fields = ["id", "project", "label", "snapshot", "created_at"]
        read_only_fields = ["id", "created_at"]
