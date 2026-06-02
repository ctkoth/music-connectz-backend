"""WriteZ workspace views (owner-scoped CRUD). Youth-safe.
Training endpoints come from the SkillZ engine via urls.py.
"""
from rest_framework import generics

from apps.common.agegate import YouthSafe

from .models import BarSet, Brief, Hook, Project, Reference, RhymeStack, Version
from .serializers import (BarSetSerializer, BriefSerializer, HookSerializer,
                          ProjectSerializer, ReferenceSerializer,
                          RhymeStackSerializer, VersionSerializer)

PERMS = [YouthSafe]


class OwnedListCreate(generics.ListCreateAPIView):
    permission_classes = PERMS

    def get_queryset(self):
        return self.serializer_class.Meta.model.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class OwnedDetail(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = PERMS

    def get_queryset(self):
        return self.serializer_class.Meta.model.objects.filter(owner=self.request.user)


class ProjectListCreateView(OwnedListCreate):  serializer_class = ProjectSerializer
class ProjectDetailView(OwnedDetail):          serializer_class = ProjectSerializer
class HookListCreateView(OwnedListCreate):     serializer_class = HookSerializer
class BarListCreateView(OwnedListCreate):      serializer_class = BarSetSerializer
class RhymeListCreateView(OwnedListCreate):    serializer_class = RhymeStackSerializer
class ReferenceListCreateView(OwnedListCreate):serializer_class = ReferenceSerializer
class BriefListCreateView(OwnedListCreate):    serializer_class = BriefSerializer


class VersionListCreateView(generics.ListCreateAPIView):
    serializer_class = VersionSerializer
    permission_classes = PERMS

    def get_queryset(self):
        qs = Version.objects.filter(project__owner=self.request.user)
        pid = self.request.query_params.get("project")
        return qs.filter(project_id=pid) if pid else qs
