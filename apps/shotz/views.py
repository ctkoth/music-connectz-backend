"""ShotZ workspace views (owner-scoped CRUD). Youth-safe. Training via urls.py."""
from rest_framework import generics
from apps.common.agegate import YouthSafe
from .serializers import (ClipSerializer, FootageSerializer, LocationSerializer,
                          ProjectSerializer, RenderSerializer, ShotListItemSerializer,
                          StoryboardSerializer)
PERMS = [YouthSafe]

class OwnedListCreate(generics.ListCreateAPIView):
    permission_classes = PERMS
    def get_queryset(self): return self.serializer_class.Meta.model.objects.filter(owner=self.request.user)
    def perform_create(self, serializer): serializer.save(owner=self.request.user)

class OwnedDetail(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = PERMS
    def get_queryset(self): return self.serializer_class.Meta.model.objects.filter(owner=self.request.user)

class ProjectListCreateView(OwnedListCreate):  serializer_class = ProjectSerializer
class ProjectDetailView(OwnedDetail):          serializer_class = ProjectSerializer
class ClipListCreateView(OwnedListCreate):     serializer_class = ClipSerializer
class FootageListCreateView(OwnedListCreate):  serializer_class = FootageSerializer
class StoryboardListCreateView(OwnedListCreate):serializer_class = StoryboardSerializer
class ShotListView(OwnedListCreate):           serializer_class = ShotListItemSerializer
class LocationListCreateView(OwnedListCreate): serializer_class = LocationSerializer
class RenderListCreateView(OwnedListCreate):   serializer_class = RenderSerializer
