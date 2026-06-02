"""DevelopZ views — youth-safe dev console. API keys are hashed at rest."""
import secrets

from django.contrib.auth.hashers import make_password
from rest_framework import generics, status
from rest_framework.response import Response

from apps.common.agegate import YouthSafe

from .models import (ApiKey, Build, Deployment, Environment, Repo, Snippet,
                     Task, Webhook)
from .serializers import (ApiKeySerializer, BuildSerializer, DeploymentSerializer,
                          EnvironmentSerializer, RepoSerializer, SnippetSerializer,
                          TaskSerializer, WebhookSerializer)

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


class RepoListCreateView(OwnedListCreate):        serializer_class = RepoSerializer
class RepoDetailView(OwnedDetail):                serializer_class = RepoSerializer
class BuildListCreateView(OwnedListCreate):       serializer_class = BuildSerializer
class DeploymentListCreateView(OwnedListCreate):  serializer_class = DeploymentSerializer
class EnvironmentListCreateView(OwnedListCreate): serializer_class = EnvironmentSerializer
class WebhookListCreateView(OwnedListCreate):     serializer_class = WebhookSerializer
class SnippetListCreateView(OwnedListCreate):     serializer_class = SnippetSerializer
class TaskListCreateView(OwnedListCreate):        serializer_class = TaskSerializer


class ApiKeyListCreateView(generics.ListCreateAPIView):
    """GET lists keys (prefix only). POST mints a key, returns the secret ONCE."""
    serializer_class = ApiKeySerializer
    permission_classes = PERMS

    def get_queryset(self):
        return ApiKey.objects.filter(owner=self.request.user)

    def create(self, request, *args, **kwargs):
        label = request.data.get("label", "key")
        token = "mcz_" + secrets.token_urlsafe(32)
        obj = ApiKey.objects.create(
            owner=request.user, label=label,
            prefix=token[:12], hashed=make_password(token))
        data = ApiKeySerializer(obj).data
        data["secret"] = token  # shown once; not stored in plaintext
        data["warning"] = "Copy this now — it will not be shown again."
        return Response(data, status=status.HTTP_201_CREATED)
