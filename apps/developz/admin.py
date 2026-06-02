from django.contrib import admin

from .models import (ApiKey, Build, Deployment, Environment, Repo, Snippet,
                     Task, Webhook)

for m in (Repo, Build, Deployment, Environment, Webhook, Snippet, Task):
    admin.site.register(m)


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("label", "prefix", "owner", "revoked", "created_at")
    readonly_fields = ("hashed", "prefix")
