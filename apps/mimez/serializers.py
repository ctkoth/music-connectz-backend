from rest_framework import serializers

from .models import MimeZSubmission


class MimeZSubmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MimeZSubmission
        fields = ("id", "kind", "drill_key", "caption", "media_ref", "score", "created_at")
        read_only_fields = ("id", "created_at")
