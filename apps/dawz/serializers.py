from rest_framework import serializers

from .models import DawProposal


class DawProposalSerializer(serializers.ModelSerializer):
    vote_count = serializers.IntegerField(source="votes.count", read_only=True)
    you_voted = serializers.SerializerMethodField()

    class Meta:
        model = DawProposal
        fields = ["id", "key", "name", "emoji", "color", "comparable_to", "tagline",
                  "description", "features", "status", "order", "vote_count", "you_voted"]

    def get_you_voted(self, obj):
        uid = self.context.get("voted_daw_id")
        return uid == obj.id
