from rest_framework import serializers

from .models import (ApiKey, Build, Deployment, Environment, Repo, Snippet,
                     Task, Webhook)


def _ser(model_cls, flds, ro=None):
    meta = type("Meta", (), {"model": model_cls, "fields": flds,
                             "read_only_fields": ro or ["id", "created_at"]})
    return type(model_cls.__name__ + "Serializer", (serializers.ModelSerializer,), {"Meta": meta})


RepoSerializer = _ser(Repo, ["id", "name", "url", "branch", "created_at"])
BuildSerializer = _ser(Build, ["id", "repo", "commit", "status", "created_at"])
DeploymentSerializer = _ser(Deployment, ["id", "repo", "environment", "status", "created_at"])
EnvironmentSerializer = _ser(Environment, ["id", "name", "notes", "created_at"])
WebhookSerializer = _ser(Webhook, ["id", "url", "event", "active", "created_at"])
SnippetSerializer = _ser(Snippet, ["id", "title", "language", "code", "created_at"])
TaskSerializer = _ser(Task, ["id", "title", "done", "created_at"])


class ApiKeySerializer(serializers.ModelSerializer):
    """Read serializer — never exposes the secret, only the prefix."""
    class Meta:
        model = ApiKey
        fields = ["id", "label", "prefix", "revoked", "created_at"]
        read_only_fields = ["id", "prefix", "revoked", "created_at"]
