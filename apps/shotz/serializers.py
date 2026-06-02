from rest_framework import serializers
from .models import Clip, Footage, Location, Project, Render, ShotListItem, Storyboard

def _ser(m, flds):
    meta = type("Meta", (), {"model": m, "fields": flds, "read_only_fields": ["id", "created_at"]})
    return type(m.__name__ + "Serializer", (serializers.ModelSerializer,), {"Meta": meta})

ProjectSerializer = _ser(Project, ["id","title","kind","status","notes","created_at","updated_at"])
ClipSerializer = _ser(Clip, ["id","project","name","url","duration_s","created_at"])
FootageSerializer = _ser(Footage, ["id","name","url","tag","created_at"])
StoryboardSerializer = _ser(Storyboard, ["id","project","title","frames","created_at"])
ShotListItemSerializer = _ser(ShotListItem, ["id","project","shot","captured","created_at"])
LocationSerializer = _ser(Location, ["id","name","address","notes","created_at"])
RenderSerializer = _ser(Render, ["id","project","label","status","output_url","created_at"])
